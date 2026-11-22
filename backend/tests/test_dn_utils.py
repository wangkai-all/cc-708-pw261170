"""DN parsing, escaping, case-insensitive comparison and multi-valued RDNs."""

import pytest

from ldap_console import dn_utils
from ldap_console.dn_utils import InvalidDN, RDN


def test_parse_escaped_comma_does_not_split_value():
    dn = r"cn=Doe\, John,ou=people,dc=demo,dc=local"
    parsed = dn_utils.parse(dn)
    assert len(parsed.rdns) == 4
    leaf = parsed.leaf_rdn
    assert not leaf.is_multi_valued
    assert leaf.primary == ("cn", r"Doe\, John")
    # A naive comma split would produce 5 fragments; the parser produces 4.
    assert dn.count(",") == 4 and len(parsed.rdns) == 4


def test_hex_escape_inside_value():
    parsed = dn_utils.parse(r"cn=R \2B D,ou=eng,dc=demo,dc=local")
    assert parsed.leaf_rdn.primary[1] == r"R \2B D"
    assert dn_utils.leaf_value(r"cn=R \2B D,ou=eng,dc=demo,dc=local") == "R + D"


def test_multi_valued_rdn_parsed_as_set():
    parsed = dn_utils.parse("cn=alice+uid=alice99,ou=people,dc=demo,dc=local")
    leaf = parsed.leaf_rdn
    assert leaf.is_multi_valued
    assert dict(leaf.avas) == {"cn": "alice", "uid": "alice99"}
    # Reversed AVA order must still compare equal.
    reversed_dn = dn_utils.parse("uid=alice99+cn=alice,ou=people,dc=demo,dc=local")
    assert parsed == reversed_dn


def test_case_insensitive_equality():
    a = "CN=Alice,OU=People,DC=demo,DC=local"
    b = "cn=alice,ou=people,dc=demo,dc=local"
    assert dn_utils.equal(a, b)
    # Original spelling is preserved for display.
    assert dn_utils.normalize(a) == a


def test_case_insensitive_multi_rdn_value():
    a = dn_utils.parse("cn=ALICE+uid=Alice99,dc=demo,dc=local")
    b = dn_utils.parse("CN=alice+UID=alice99,DC=demo,DC=local")
    assert a == b


def test_is_descendant_respects_escapes_and_case():
    child = r"cn=Doe\, John,OU=people,dc=demo,dc=local"
    assert dn_utils.is_descendant_or_self(child, "dc=demo,dc=local")
    assert dn_utils.is_descendant_or_self("dc=demo,dc=local", "dc=demo,dc=local")
    assert not dn_utils.is_descendant_or_self(
        "cn=x,ou=people,dc=other,dc=local", "dc=demo,dc=local"
    )
    # A suffix string match would get this wrong; the parser gets it right.
    assert not dn_utils.is_descendant_or_self(
        "cn=dc=demo,dc=local,ou=trick,dc=other,dc=com", "dc=demo,dc=local"
    )


def test_escape_and_build_roundtrip():
    value = 'a,b+c"d\\e<f>g;h=i'
    escaped = dn_utils.escape_dn_value(value)
    dn = dn_utils.build_dn([("cn", value)], "ou=people,dc=demo,dc=local")
    assert dn == f"cn={escaped},ou=people,dc=demo,dc=local"
    assert dn_utils.leaf_value(dn) == value


def test_build_multi_valued_rdn():
    dn = dn_utils.build_dn(
        [("cn", "alice"), ("uid", "alice99")], "ou=people,dc=demo,dc=local"
    )
    assert dn == "cn=alice+uid=alice99,ou=people,dc=demo,dc=local"
    assert dn_utils.parse(dn).leaf_rdn.is_multi_valued


def test_invalid_dns_rejected():
    for bad in ("", "   ", "cn=unclosed,ou=", "cn=,"):
        with pytest.raises(InvalidDN):
            dn_utils.parse(bad)
    assert dn_utils.safe_parse("not-a-dn-but-parseable=x") is not None


def test_parent_and_leaf_value():
    parsed = dn_utils.parse(r"cn=Doe\, John,ou=people,dc=demo,dc=local")
    assert parsed.parent().render() == "ou=people,dc=demo,dc=local"
    assert dn_utils.leaf_value(parsed.render()) == "Doe, John"


def test_rdn_hash_contract():
    r1 = RDN((("cn", "a"), ("uid", "b")))
    r2 = RDN((("uid", "b"), ("cn", "a")))
    assert hash(r1) == hash(r2) and r1 == r2


def test_rdn_with_all_escaped_special_characters_roundtrips():
    # Comma, plus, quote, angle brackets and semicolon all inside one value.
    plain = 'Carol "C"+Cao, <retired>;'
    dn = dn_utils.build_dn([("cn", plain)], "ou=people,dc=demo,dc=local")
    parsed = dn_utils.parse(dn)
    assert len(parsed.rdns) == 4  # not split by the escaped comma/semicolon
    assert dn_utils.leaf_value(dn) == plain


def test_demo_directory_entry_is_retrievable():
    # Guards against the mock storing an entry under a mangled (double-escaped) key.
    from ldap_console.demo_directory import get_directory

    directory = get_directory()
    target = (
        r'cn=Carol \"C\"\+Cao\, \<retired\>\;,ou=people,dc=demo,dc=local'
    )
    assert directory.exists(target)
    # Every declared bootstrap entry must be retrievable by its declared DN.
    from ldap_console.demo_directory import _ENTRIES

    for entry in _ENTRIES:
        assert directory.exists(entry.dn), entry.dn
