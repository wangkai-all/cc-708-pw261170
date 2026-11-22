"""Entry-to-entry relationship classification and alias expansion.

Three relationship kinds are kept distinct end to end:

* ``alias``     — the entry itself has an alias object class and an
                  ``aliasedObjectName`` (RFC 4512). Following it means
                  *dereferencing* to another entry's content.
* ``referral``  — a referral object (or a DN-valued attribute) pointing at a
                  naming context outside the demo root. Surfaced as an
                  external reference and **never auto-followed**.
* ``member``    — ordinary DN-valued attributes (member, manager, owner, ...)
                  naming entries inside the demo root.

Alias expansion walks the ``aliasedObjectName`` chain with a visited set: a
cycle (including a self-loop) blocks further expansion with an explicit
``cycle`` status, but every alias entry remains in the directory and in the
search results — nothing is deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from . import dn_utils
from .config import settings


@dataclass(frozen=True)
class Relationship:
    kind: str          # alias | referral | member | external-ref | unresolved
    attribute: str
    target_dn: str
    external_url: str | None = None
    inside_root: bool = True
    # Filled in for alias chains by the resolver:
    resolved_dn: str | None = None
    status: str = "present"  # present | resolved | cycle | dangling | external
    cycle_path: tuple[str, ...] | None = None


def classify_entry(entry_attrs: dict[str, list[bytes]], dn: str,
                   root: str) -> str:
    """Return the structural kind of one entry."""
    ocs = [v.decode("utf-8", "ignore").lower() for v in entry_attrs.get("objectClass", [])]
    if any(oc in settings.alias_object_classes for oc in ocs):
        return "alias"
    if "ref" in entry_attrs or any(oc in settings.referral_object_classes for oc in ocs):
        return "referral"
    return "entry"


def parse_ldap_url(url: str) -> dict[str, str] | None:
    """Extract host/port/base DN from an ldap:// / ldaps:// referral URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("ldap", "ldaps"):
        return None
    base_dn = parsed.path.lstrip("/")
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname or "",
        "port": str(parsed.port or (636 if parsed.scheme == "ldaps" else 389)),
        "base_dn": base_dn,
    }


def extract_relationships(
    entry_attrs: dict[str, list[bytes]],
    root: str,
    exists_check,
) -> list[Relationship]:
    """Build the relationship list for one entry's raw attributes.

    ``exists_check(dn) -> bool`` reports whether a DN names an entry in the
    local demo DIT.
    """
    rels: list[Relationship] = []
    kind = classify_entry(entry_attrs, "", root)

    # 1) Alias target (structural).
    if kind == "alias":
        for raw in entry_attrs.get("aliasedobjectname", []):
            target = raw.decode("utf-8", "ignore")
            inside = dn_utils.is_descendant_or_self(target, root)
            rels.append(
                Relationship(
                    kind="alias",
                    attribute="aliasedObjectName",
                    target_dn=target,
                    inside_root=inside,
                    status="present" if inside else "external",
                )
            )

    # 2) Referral URLs (structural or standalone ref attribute).
    for raw in entry_attrs.get("ref", []):
        url = raw.decode("utf-8", "ignore")
        parsed_url = parse_ldap_url(url)
        target_dn = parsed_url["base_dn"] if parsed_url else url
        rels.append(
            Relationship(
                kind="referral",
                attribute="ref",
                target_dn=target_dn,
                external_url=url,
                inside_root=False,
                status="external",
            )
        )

    # 3) Ordinary DN-valued attributes.
    for attr, raw_values in entry_attrs.items():
        base_attr = attr.split(";", 1)[0].lower()
        if base_attr not in settings.dn_valued_attributes:
            continue
        if base_attr in ("ref", "aliasedobjectname"):
            continue
        for raw in raw_values:
            target = raw.decode("utf-8", "ignore")
            if not dn_utils.safe_parse(target):
                continue
            inside = dn_utils.is_descendant_or_self(target, root)
            if not inside:
                rels.append(
                    Relationship(
                        kind="external-ref",
                        attribute=base_attr,
                        target_dn=target,
                        inside_root=False,
                        status="external",
                    )
                )
                continue
            status = "present" if exists_check(target) else "unresolved"
            rels.append(
                Relationship(
                    kind="member",
                    attribute=base_attr,
                    target_dn=target,
                    inside_root=True,
                    status=status,
                )
            )
    return rels


@dataclass
class AliasResolution:
    alias_dn: str
    status: str  # resolved | cycle | dangling | external | not-an-alias
    chain: tuple[str, ...]
    resolved_dn: str | None = None
    cycle_path: tuple[str, ...] | None = None


class AliasResolver:
    """Walks aliasedObjectName chains with cycle detection.

    The resolver only reads the demo DIT. Cross-root targets stop the walk and
    are reported as external rather than followed.
    """

    MAX_HOPS = 32

    def __init__(self, get_entry, root: str) -> None:
        # get_entry(dn) -> raw attribute dict (case-insensitive keys) or None
        self._get_entry = get_entry
        self._root = root

    def resolve(self, alias_dn: str) -> AliasResolution:
        chain: list[str] = []
        visited: set[str] = set()
        current = alias_dn

        def lookup(dn: str):
            # DIT keys are case-insensitive names; normalize via the parser
            # (which also resolves escaped forms), lowercasing attribute
            # types too, before the lookup so a target spelled with different
            # casing still resolves.
            parsed = dn_utils.safe_parse(dn)
            if parsed is None:
                return None
            normalized = ",".join(
                "+".join(f"{attr.lower()}={value}" for attr, value in rdn.avas)
                for rdn in parsed.rdns
            ).lower()
            return self._get_entry(normalized)

        for _ in range(self.MAX_HOPS):
            parsed = dn_utils.safe_parse(current)
            if parsed is None:
                return AliasResolution(alias_dn, "dangling", tuple(chain))

            key = parsed.render().lower()
            if key in visited:
                # Cycle: block expansion, keep every entry.
                cycle_start = next(
                    (i for i, dn in enumerate(chain)
                     if dn_utils.equal(dn, current)),
                    len(chain),
                )
                cycle_path = tuple(chain[cycle_start:] + [current])
                return AliasResolution(
                    alias_dn=alias_dn,
                    status="cycle",
                    chain=tuple(chain),
                    cycle_path=cycle_path,
                )
            visited.add(key)
            chain.append(current)

            entry = lookup(current)
            if entry is None:
                return AliasResolution(alias_dn, "dangling", tuple(chain))

            ocs = [v.decode("utf-8", "ignore").lower()
                   for v in entry.get("objectClass", [])]
            if not any(oc in settings.alias_object_classes for oc in ocs):
                # Reached a concrete object.
                return AliasResolution(
                    alias_dn=alias_dn,
                    status="resolved",
                    chain=tuple(chain),
                    resolved_dn=current,
                )

            targets = entry.get("aliasedobjectname", [])
            if not targets:
                return AliasResolution(alias_dn, "dangling", tuple(chain))
            current = targets[0].decode("utf-8", "ignore")

            if not dn_utils.is_descendant_or_self(current, self._root):
                return AliasResolution(
                    alias_dn=alias_dn,
                    status="external",
                    chain=tuple(chain),
                    resolved_dn=current,
                )

        return AliasResolution(alias_dn, "cycle", tuple(chain))  # pragma: no cover
