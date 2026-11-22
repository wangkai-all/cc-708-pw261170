"""Distinguished Name handling built on ldap3's RFC 4514 parser.

The rules implemented here follow the library's interpretation of LDAP DNs:

* A DN is **never** split on commas with ``str.split(',')`` — commas may be
  escaped (``\\,``) or hex-escaped (``\\2c``) inside an RDN value, and RDNs
  may themselves be multi-valued (joined by ``+``). ``ldap3.utils.dn.parse_dn``
  performs the state-machine parse.
* Attribute *types* and RDN *values* are compared case-insensitively per
  RFC 4512/RFC 4517 (DN is a canonicalized, case-insensitive name); the
  original spelling is preserved for display.
* Multi-valued RDNs (``cn=...+uid=...``) are compared as *sets* of AVA
  pairs, so the order of AVAs does not matter.
* ``escape_dn_value`` / ``build_dn`` produce correctly escaped DNs for values
  supplied by the web UI (which arrive as plain, unescaped strings).
"""

from __future__ import annotations

from dataclasses import dataclass

from ldap3.core.exceptions import LDAPInvalidDnError
from ldap3.utils.dn import escape_rdn, parse_dn, to_dn


class InvalidDN(ValueError):
    """Raised when input cannot be parsed as a distinguished name."""


@dataclass(frozen=True)
class RDN:
    """One Relative Distinguished Name, possibly multi-valued.

    ``avas`` holds ``(attribute_type, raw_escaped_value)`` tuples in parse
    order. Comparison is order-independent for multi-valued RDNs.
    """

    avas: tuple[tuple[str, str], ...]

    @property
    def is_multi_valued(self) -> bool:
        return len(self.avas) > 1

    @property
    def primary(self) -> tuple[str, str]:
        """First AVA, the conventional 'primary' component of an RDN."""
        return self.avas[0]

    def rendered(self) -> str:
        """Render the RDN back to wire text (escapes preserved)."""
        return "+".join(f"{attr}={value}" for attr, value in self.avas)

    def _key(self) -> frozenset[tuple[str, str]]:
        # Case-insensitive type and value; multi-valued RDN -> unordered set.
        return frozenset((attr.lower(), value.lower()) for attr, value in self.avas)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RDN):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


@dataclass(frozen=True)
class ParsedDN:
    """A DN parsed into its ordered chain of RDNs (leaf first, root last)."""

    rdns: tuple[RDN, ...]
    raw: str

    @property
    def leaf_rdn(self) -> RDN:
        return self.rdns[0]

    def parent(self) -> "ParsedDN | None":
        if len(self.rdns) <= 1:
            return None
        return ParsedDN(self.rdns[1:], self.render_parent())

    def render(self) -> str:
        return ",".join(rdn.rendered() for rdn in self.rdns)

    def render_parent(self) -> str:
        return ",".join(rdn.rendered() for rdn in self.rdns[1:])

    def _key(self) -> tuple[frozenset[tuple[str, str]], ...]:
        return tuple(rdn._key() for rdn in self.rdns)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ParsedDN):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


def parse(dn: str) -> ParsedDN:
    """Parse a wire-format DN using ldap3's state machine.

    Raises :class:`InvalidDN` on malformed input instead of letting ldap3's
    own exception type leak across the package boundary.
    """
    if not isinstance(dn, str) or not dn.strip():
        raise InvalidDN("empty DN")
    try:
        parsed = parse_dn(dn, escape=False)
    except LDAPInvalidDnError as exc:  # pragma: no cover - ldap3 raises subclass
        raise InvalidDN(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise InvalidDN(f"unparseable DN {dn!r}: {exc}") from exc

    rdns: list[RDN] = []
    current: list[tuple[str, str]] = []
    for attr, value, separator in parsed:
        current.append((attr, value))
        if separator == ",":  # '+' means another AVA belongs to the same RDN
            rdns.append(RDN(tuple(current)))
            current = []
    if current:
        rdns.append(RDN(tuple(current)))
    if not rdns:
        raise InvalidDN(f"no RDNs found in {dn!r}")
    return ParsedDN(tuple(rdns), dn)


def safe_parse(dn: str) -> ParsedDN | None:
    try:
        return parse(dn)
    except InvalidDN:
        return None


def normalize(dn: str) -> str:
    """Return a canonical rendering (whitespace trimmed, original escapes kept)."""
    return parse(dn).render()


def equal(dn_a: str, dn_b: str) -> bool:
    """Case-insensitive DN equality, multi-valued-RDN aware."""
    pa, pb = safe_parse(dn_a), safe_parse(dn_b)
    if pa is None or pb is None:
        return False
    return pa == pb


def is_descendant_or_self(maybe_child: str, ancestor: str) -> bool:
    """True when ``maybe_child`` is inside ``ancestor`` (or equal to it).

    Comparison goes through the parser so that escaped commas, hex escapes,
    case differences and multi-valued RDNs are handled correctly.
    """
    child, base = safe_parse(maybe_child), safe_parse(ancestor)
    if child is None or base is None:
        return False
    if len(child.rdns) < len(base.rdns):
        return False
    # RDN chains are leaf-first; the suffix must match the ancestor chain.
    suffix = child.rdns[len(child.rdns) - len(base.rdns):]
    return tuple(suffix) == base.rdns


def escape_dn_value(value: str) -> str:
    """Escape a *plain* RDN value supplied by UI code (RFC 4514 section 2.4)."""
    return escape_rdn(value)


def build_dn(rdn_parts: list[tuple[str, str]], parent_dn: str | None = None) -> str:
    """Build a wire DN from plain (un-escaped) attribute/value pairs.

    ``rdn_parts`` with more than one element produces a multi-valued RDN.
    """
    if not rdn_parts:
        raise InvalidDN("at least one RDN AVA is required")
    rdn = "+".join(f"{attr}={escape_rdn(value)}" for attr, value in rdn_parts)
    if parent_dn:
        return f"{rdn},{normalize(parent_dn)}"
    return rdn


def leaf_value(dn: str) -> str:
    """Return the (un-escaped) value of the leaf RDN's primary AVA."""
    parsed = parse(dn)
    _, raw_value = parsed.leaf_rdn.primary
    # ldap3 keeps escapes in parse_dn output; to_dn round-trips and
    # parse_dn(..., escape=True) would strip them. Use a controlled unescape.
    return _unescape_rdn_value(raw_value)


def _unescape_rdn_value(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in {",", "+", '"', "\\", "<", ">", ";", "=", "#", " "}:
                out.append(nxt)
                i += 2
                continue
            # hex escape: two hex digits
            if i + 2 < len(raw):
                hex_pair = raw[i + 1:i + 3]
                try:
                    out.append(chr(int(hex_pair, 16)))
                    i += 3
                    continue
                except ValueError:
                    pass
        out.append(ch)
        i += 1
    return "".join(out)


def join_rdn(value_rdn: str, parent_dn: str) -> str:
    """Join an already-escaped RDN string with a parsed parent DN."""
    parent = normalize(parent_dn)
    return f"{value_rdn},{parent}"


def reorder_to_dn(rdn_strings: list[str]) -> str:
    """Normalize a DN given as already-escaped RDN fragments."""
    return to_dn(rdn_strings)
