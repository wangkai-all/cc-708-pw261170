"""Relationship classification and alias cycle handling."""

from ldap_console.relationships import (
    AliasResolver,
    extract_relationships,
    parse_ldap_url,
)
from ldap_console.service import LdapConsoleService, SearchQuery

ROOT = "dc=demo,dc=local"


def _service() -> LdapConsoleService:
    return LdapConsoleService()


def test_alias_loop_is_blocked_but_entries_remain():
    svc = _service()
    resolution = svc.resolve_alias("cn=alias-a,ou=aliases,dc=demo,dc=local")
    assert resolution["status"] == "cycle"
    # The chain names both aliases; the cycle path closes back onto alias-a.
    assert "cn=alias-b,ou=aliases,dc=demo,dc=local" in resolution["chain"]
    cycle = resolution["cycle_path"]
    assert cycle[0] == "cn=alias-a,ou=aliases,dc=demo,dc=local"
    assert cycle[-1] == "cn=alias-a,ou=aliases,dc=demo,dc=local"
    assert len(cycle) >= 3
    # Entries still exist and still appear in searches.
    res = svc.search(SearchQuery(base_dn="ou=aliases,dc=demo,dc=local", scope="one"))
    dns = {e["dn"] for e in res["entries"]}
    assert "cn=alias-a,ou=aliases,dc=demo,dc=local" in dns
    assert "cn=alias-b,ou=aliases,dc=demo,dc=local" in dns


def test_self_alias_is_a_cycle():
    svc = _service()
    resolution = svc.resolve_alias("cn=alias-self,ou=aliases,dc=demo,dc=local")
    assert resolution["status"] == "cycle"


def test_healthy_alias_resolves_to_concrete_entry():
    svc = _service()
    resolution = svc.resolve_alias("cn=john-alias,ou=aliases,dc=demo,dc=local")
    assert resolution["status"] == "resolved"
    assert "Doe" in resolution["resolved_dn"]


def test_dangling_alias_reported_not_deleted():
    svc = _service()
    resolution = svc.resolve_alias("cn=dangling-alias,ou=aliases,dc=demo,dc=local")
    assert resolution["status"] == "dangling"
    entry = svc.get_entry("cn=dangling-alias,ou=aliases,dc=demo,dc=local")
    assert entry["kind"] == "alias"


def test_referral_objects_are_external_and_classified_separately():
    svc = _service()
    entry = svc.get_entry("cn=partner-directory,ou=externals,dc=demo,dc=local")
    assert entry["kind"] == "referral"
    refs = [r for r in entry["relationships"] if r["kind"] == "referral"]
    assert len(refs) == 2
    assert all(not r["inside_root"] for r in refs)
    assert all(r["external_url"].startswith(("ldap://", "ldaps://")) for r in refs)


def test_cross_root_dn_attribute_is_external_ref_not_member():
    svc = _service()
    entry = svc.get_entry("cn=erin,ou=people,dc=demo,dc=local")
    ext = [r for r in entry["relationships"] if r["target_dn"].endswith("dc=partner,dc=com")]
    assert ext and ext[0]["kind"] == "external-ref"
    assert ext[0]["status"] == "external"


def test_unresolved_member_kept_and_flagged():
    svc = _service()
    entry = svc.get_entry("cn=dave,ou=people,dc=demo,dc=local")
    manager = [r for r in entry["relationships"] if r["attribute"] == "manager"]
    assert manager and manager[0]["status"] == "unresolved"
    assert manager[0]["kind"] == "member"


def test_regular_membership_distinct_from_alias():
    svc = _service()
    entry = svc.get_entry("cn=admins,ou=groups,dc=demo,dc=local")
    members = [r for r in entry["relationships"] if r["kind"] == "member"]
    assert len(members) == 2
    assert all(r["status"] == "present" for r in members)


def test_ldap_url_parsing():
    parsed = parse_ldap_url("ldap://host.example:1389/dc=x,dc=y??sub")
    assert parsed == {
        "scheme": "ldap",
        "host": "host.example",
        "port": "1389",
        "base_dn": "dc=x,dc=y",
    }
    assert parse_ldap_url("https://host") is None


def test_resolver_visits_each_dn_once_case_insensitively():
    # Build a tiny synthetic DIT to exercise the visited-set directly.
    # Emulate the mock DIT's CaseInsensitiveDict attribute keys.
    class CIDict(dict):
        def get(self, key, default=None):
            low = key.lower()
            for k, v in self.items():
                if k.lower() == low:
                    return v
            return default

    dit = {
        "cn=a,dc=demo,dc=local": CIDict({
            "objectClass": [b"alias"],
            "aliasedObjectName": [b"CN=B,dc=demo,dc=local"],
        }),
        "cn=b,dc=demo,dc=local": CIDict({
            "objectClass": [b"alias"],
            "aliasedObjectName": [b"cn=a,dc=demo,dc=local"],
        }),
    }

    def get_entry(dn: str):
        # Emulate a case-insensitive DIT lookup.
        return next(
            (attrs for key, attrs in dit.items() if key.lower() == dn.lower()),
            None,
        )

    resolver = AliasResolver(get_entry, ROOT)
    result = resolver.resolve("cn=a,dc=demo,dc=local")
    assert result.status == "cycle"
    # Case difference in the link does not defeat detection.
    assert len(result.chain) == 2
