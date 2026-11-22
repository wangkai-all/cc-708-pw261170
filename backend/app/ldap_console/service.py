"""Application service layer: searches, range assembly and entry reads.

All LDAP access goes through the bundled demo directory. The search guard
rejects any base outside the configured allowed bases, so collection settings
cannot be redirected at another server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ldap3 import ALL_ATTRIBUTES, BASE, LEVEL, SUBTREE
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from . import dn_utils
from .config import settings
from .demo_directory import get_directory
from .ranged import (
    DemoRangeService,
    RangeAssembler,
    RangeResult,
    describe_coverage,
)
from .relationships import AliasResolver, Relationship, classify_entry, extract_relationships
from .values import render_for_json

_SCOPE_IDS = {"base": BASE, "one": LEVEL, "sub": SUBTREE}

# Fault injection is a demo-only test hook applied to the range conversation,
# letting the UI show how a bad segment is detected. It never touches the DIT.
_FAULT_KINDS = {"gap", "overlap", "stall"}


class SearchGuardError(ValueError):
    pass


class SearchFailed(RuntimeError):
    pass


@dataclass
class SearchQuery:
    base_dn: str
    scope: str = "sub"
    attributes: list[str] = field(default_factory=lambda: ["*"])
    object_class: str | None = None
    field_filters: list[dict[str, str]] = field(default_factory=list)
    raw_filter: str | None = None
    size_limit: int = 100
    # Demo-only range fault injection: {"kind": "gap"|"overlap"|"stall",
    # "attribute": "member"}
    range_fault: dict[str, str] | None = None


def _validate_base(base_dn: str, scope: str) -> str:
    parsed = dn_utils.safe_parse(base_dn)
    if parsed is None:
        raise SearchGuardError(f"invalid search base DN: {base_dn!r}")
    rendered = parsed.render()
    # Hard boundary: nothing outside the demo naming context may be queried,
    # regardless of how the request was constructed.
    if not dn_utils.is_descendant_or_self(rendered, settings.naming_context):
        raise SearchGuardError(
            "collection settings only permit the bundled demo directory; "
            f"base {rendered!r} is outside the naming context"
        )
    # Subtree/one-level searches may only start at the configured collection
    # points, preventing the UI from being turned into an arbitrary crawler.
    if scope in ("sub", "one") and not any(
        dn_utils.equal(rendered, allowed) for allowed in settings.allowed_search_bases
    ):
        raise SearchGuardError(
            f"scope {scope!r} searches are restricted to the configured search "
            f"bases; {rendered!r} is not one of them"
        )
    return rendered


def _build_filter(query: SearchQuery) -> str:
    parts: list[str] = []
    if query.object_class:
        parts.append(f"(objectClass={escape_filter_chars(query.object_class)})")
    for ff in query.field_filters:
        attr = ff["attribute"].strip()
        value = ff["value"]
        match = ff.get("match", "exact")
        if not attr:
            continue
        safe = escape_filter_chars(value)
        if match == "substring":
            parts.append(f"({attr}=*{safe}*)")
        elif match == "starts":
            parts.append(f"({attr}={safe}*)")
        elif match == "present":
            parts.append(f"({attr}=*)")
        else:
            parts.append(f"({attr}={safe})")
    if query.raw_filter:
        # Raw filters are only accepted if they are syntactically a single
        # parenthesized expression; the mock parser does the real validation.
        rf = query.raw_filter.strip()
        if not (rf.startswith("(") and rf.endswith(")")):
            raise SearchGuardError("raw filter must be a parenthesized LDAP filter")
        parts.append(rf)
    if not parts:
        return "(objectClass=*)"
    if len(parts) == 1:
        return parts[0]
    return "(&" + "".join(parts) + ")"


class LdapConsoleService:
    """Facade used by the HTTP layer; one instance is shared app-wide."""

    def __init__(self) -> None:
        self._directory = get_directory()
        self._range_service = DemoRangeService()

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #

    def search(self, query: SearchQuery) -> dict[str, Any]:
        base = _validate_base(query.base_dn, query.scope)
        if query.scope not in _SCOPE_IDS:
            raise SearchGuardError(f"unknown scope {query.scope!r}")
        if query.size_limit > settings.max_search_entries:
            raise SearchGuardError(
                f"size limit {query.size_limit} exceeds maximum {settings.max_search_entries}"
            )
        ldap_filter = _build_filter(query)
        want_all = not query.attributes or "*" in query.attributes

        conn = self._directory.connect()
        try:
            requested = ALL_ATTRIBUTES if want_all else list(query.attributes)
            # The demo mock treats size_limit as an all-or-nothing cap, so
            # paging is applied here: fetch everything the filter matches
            # (bounded by the hard maximum) and slice to the requested limit.
            conn.search(
                base,
                ldap_filter,
                search_scope=_SCOPE_IDS[query.scope],
                attributes=requested,
                size_limit=settings.max_search_entries,
            )
            all_responses = list(conn.response)
            total_matches = len(all_responses)
            responses = all_responses[:query.size_limit]
        except LDAPException as exc:
            raise SearchFailed(str(exc)) from exc
        finally:
            conn.unbind()

        entries = [self._hydrate_entry(resp, query.range_fault) for resp in responses]
        return {
            "base_dn": base,
            "scope": query.scope,
            "filter": ldap_filter,
            "count": len(entries),
            "total_matches": total_matches,
            "truncated": total_matches > len(entries),
            "entries": entries,
        }

    # ------------------------------------------------------------------ #
    # Single entry (used by the entry detail / alias expansion views)
    # ------------------------------------------------------------------ #

    def get_entry(self, dn: str) -> dict[str, Any]:
        parsed = dn_utils.safe_parse(dn)
        if parsed is None:
            raise SearchGuardError(f"invalid DN: {dn!r}")
        if not dn_utils.is_descendant_or_self(parsed.render(), settings.naming_context):
            raise SearchGuardError("entries outside the demo root are not retrievable")
        conn = self._directory.connect()
        try:
            conn.search(parsed.render(), "(objectClass=*)", search_scope=BASE,
                        attributes=ALL_ATTRIBUTES)
            if not conn.response:
                raise KeyError(dn)
            return self._hydrate_entry(conn.response[0], None)
        except LDAPException as exc:
            raise SearchFailed(str(exc)) from exc
        finally:
            conn.unbind()

    def resolve_alias(self, dn: str) -> dict[str, Any]:
        parsed = dn_utils.safe_parse(dn)
        if parsed is None:
            raise SearchGuardError(f"invalid DN: {dn!r}")
        resolver = AliasResolver(self._raw_entry, settings.naming_context)
        result = resolver.resolve(parsed.render())
        payload: dict[str, Any] = {
            "alias_dn": result.alias_dn,
            "status": result.status,
            "chain": list(result.chain),
            "resolved_dn": result.resolved_dn,
        }
        if result.cycle_path:
            payload["cycle_path"] = list(result.cycle_path)
        return payload

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _raw_entry(self, dn: str) -> dict[str, list[bytes]] | None:
        conn = self._directory.connect()
        try:
            conn.search(dn, "(objectClass=*)", search_scope=BASE,
                        attributes=ALL_ATTRIBUTES)
            if not conn.response:
                return None
            return conn.response[0]["raw_attributes"]
        except LDAPException:
            return None
        finally:
            conn.unbind()

    def _hydrate_entry(self, response: dict[str, Any],
                       range_fault: dict[str, str] | None) -> dict[str, Any]:
        dn = response["dn"]
        raw_attrs: dict[str, list[bytes]] = response["raw_attributes"]
        entry_kind = classify_entry(raw_attrs, dn, settings.naming_context)

        attributes_out: dict[str, Any] = {}
        range_reports: dict[str, Any] = {}

        for attr_name in sorted(raw_attrs.keys(), key=str.lower):
            base_name = attr_name.split(";", 1)[0]
            raw_values = list(raw_attrs[attr_name])
            range_result = self._assemble_attribute(
                dn, base_name, raw_values, range_fault
            )
            if range_result is not None:
                range_reports[base_name] = self._range_report(range_result)
                values = range_result.values
                complete = range_result.complete and not range_result.faults
            else:
                values = raw_values
                complete = True

            decoded = [render_for_json(v, base_name) for v in values]
            attributes_out[base_name] = {
                "type": base_name,
                "syntax": "binary" if any(d["kind"] == "binary" for d in decoded) else "text",
                "multi_valued": len(decoded) > 1,
                "complete": complete,
                "values": decoded,
            }

        relationships = extract_relationships(
            raw_attrs, settings.naming_context, self._directory.exists
        )
        return {
            "dn": dn,
            "kind": entry_kind,
            "object_class": [
                v.decode("utf-8", "ignore") for v in raw_attrs.get("objectClass", [])
            ],
            "attributes": attributes_out,
            "range_reports": range_reports,
            "relationships": [self._relationship_payload(r) for r in relationships],
        }

    def _assemble_attribute(
        self,
        dn: str,
        attribute: str,
        raw_values: list[bytes],
        range_fault: dict[str, str] | None,
    ) -> RangeResult | None:
        """Run the range conversation when the demo service segments this attr."""
        if not self._range_service.should_segment(attribute, len(raw_values)):
            return None

        service = self._range_service
        fault = self._select_fault(range_fault, attribute)

        # A fetcher that re-reads the full entry and asks the demo service to
        # slice it, mimicking round-trips to a range-capable LDAP server.
        full_values = self._full_attribute_values(dn, attribute)
        controller = _FaultController(fault) if fault else None

        def fetcher(request_tag: str):
            option = request_tag if "range=" in request_tag else None
            segment = service.serve(attribute, full_values, option)
            if segment is None or controller is None:
                return segment
            return controller.corrupt(segment)

        assembler = RangeAssembler(fetcher)
        return assembler.fetch(attribute)

    def _select_fault(self, range_fault: dict[str, str] | None,
                      attribute: str) -> str | None:
        if not range_fault:
            return None
        if range_fault.get("attribute", attribute) != attribute:
            return None
        kind = range_fault.get("kind", "")
        return kind if kind in _FAULT_KINDS else None

    def _full_attribute_values(self, dn: str, attribute: str) -> list[bytes]:
        raw = self._raw_entry(dn)
        if raw is None:
            return []
        return list(raw.get(attribute, []))

    @staticmethod
    def _range_report(result: RangeResult) -> dict[str, Any]:
        return {
            "attribute": result.attribute,
            "complete": result.complete and not result.faults,
            "reason": result.reason,
            "coverage": describe_coverage(result.segments),
            "segments": [
                {
                    "index": i,
                    "request_tag": seg.request_tag,
                    "response_tag": seg.response_tag,
                    "low": seg.low,
                    "high": seg.high,
                    "count": seg.count,
                    "expected_next_low": seg.expected_next_low,
                }
                for i, seg in enumerate(result.segments)
            ],
            "faults": [
                {"kind": f.kind, "detail": f.detail, "segment_index": f.segment_index}
                for f in result.faults
            ],
        }

    @staticmethod
    def _relationship_payload(rel: Relationship) -> dict[str, Any]:
        return {
            "kind": rel.kind,
            "attribute": rel.attribute,
            "target_dn": rel.target_dn,
            "external_url": rel.external_url,
            "inside_root": rel.inside_root,
            "status": rel.status,
        }


class _FaultController:
    """Demo-only corruption of range segments, scoped to one assembly.

    The first segment is always delivered intact so the receiver has context;
    corruption starts on the second segment, exercising gap / overlap / stall
    detection without touching the underlying DIT.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls = 0

    def corrupt(self, segment):
        from .ranged import RangeTag

        tag, chunk = segment
        self.calls += 1
        if self.calls < 2:
            return segment
        parsed = RangeTag.parse(tag)
        attr = tag.split(";", 1)[0]

        if self.kind == "gap":
            # Jump low forward without sending the skipped values.
            new_low = parsed.low + 2
            high_text = "*" if parsed.high is None else str(parsed.high)
            return f"{attr};range={new_low}-{high_text}", chunk
        if self.kind == "overlap":
            new_low = max(0, parsed.low - 2)
            high_text = "*" if parsed.high is None else str(parsed.high)
            return f"{attr};range={new_low}-{high_text}", chunk
        if self.kind == "stall":
            # Empty, open-ended segment: boundary cannot advance.
            return f"{attr};range={parsed.low}-*", []
        return segment
