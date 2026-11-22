"""The bundled demo LDAP directory, backed by an ldap3 in-process mock.

Nothing here talks to a real LDAP socket. ldap3's ``MOCK_SYNC`` strategy
keeps a DIT in memory, parses RFC 4511 search filters and matches entries the
same way its real strategies do. The demo adds:

* entries exercising escaped DNs, multi-valued RDNs, binary attributes,
  alias loops and referral objects;
* large multi-valued attributes that the *service layer* (see
  :mod:`ldap_console.ranged`) segments with ``;range=`` result tags, because
  ldap3's mock itself does not implement range retrieval.

The DIT is rebuilt per process and shared read-only; every request gets a
fresh :class:`~ldap3.Connection` bound to the same in-memory server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ldap3 import ALL_ATTRIBUTES, BASE, LEVEL, SUBTREE, Connection, MOCK_SYNC, Server
from ldap3.core.exceptions import LDAPException

from .config import DEMO_NAMING_CONTEXT

# Search-scope constants exposed to the API as stable strings.
SCOPES = {
    "base": BASE,
    "one": LEVEL,
    "sub": SUBTREE,
}

ROOT = DEMO_NAMING_CONTEXT  # "dc=demo,dc=local"


@dataclass(frozen=True)
class DemoEntry:
    dn: str
    object_class: list[str]
    attributes: dict[str, object]


# A 12-byte payload that is deliberately not valid UTF-8 (0xFF 0xD8 are the
# JPEG SOI marker); any text decoder attempt would fail.
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\xff"
_CERT_BYTES = b"\x30\x82\x01\x10\x30\x81\xff\xa0\x03\x02\x01\x02\xff\xfe"


def _build_entries() -> list[DemoEntry]:
    entries: list[DemoEntry] = [
        # ---- naming context -------------------------------------------------
        DemoEntry(ROOT, ["top", "domainDNS"], {"dc": "demo", "name": "Demo Directory"}),
        # ---- organisational units ------------------------------------------
        DemoEntry(f"ou=people,{ROOT}", ["top", "organizationalUnit"], {"ou": "people"}),
        DemoEntry(f"ou=groups,{ROOT}", ["top", "organizationalUnit"], {"ou": "groups"}),
        DemoEntry(f"ou=aliases,{ROOT}", ["top", "organizationalUnit"], {"ou": "aliases"}),
        DemoEntry(f"ou=externals,{ROOT}", ["top", "organizationalUnit"], {"ou": "externals"}),
        DemoEntry(f"ou=devices,{ROOT}", ["top", "organizationalUnit"], {"ou": "devices"}),
        # ---- people ---------------------------------------------------------
        # Escaped DN: the comma inside the cn value is part of the value, not a
        # RDN separator. Splitting this DN on ',' would corrupt it.
        DemoEntry(
            f"cn=Doe\\, John,ou=people,{ROOT}",
            ["top", "person", "inetOrgPerson"],
            {
                "cn": "Doe, John",
                "sn": "Doe",
                "givenName": "John",
                "mail": ["john.doe@demo.local", "j.doe@example.net"],
                "telephoneNumber": ["+1-555-0100", "+1-555-0101"],
                "title": "Engineer, Platform",
                "jpegPhoto": _JPEG_BYTES,
            },
        ),
        # Multi-valued RDN: cn AND uid together name this entry.
        DemoEntry(
            f"cn=alice+uid=alice99,ou=people,{ROOT}",
            ["top", "person", "inetOrgPerson"],
            {
                "cn": "alice",
                "uid": "alice99",
                "sn": "Nguyen",
                "mail": "alice@demo.local",
                "title": "Directory Architect",
                "seeAlso": f"cn=Doe\\, John,ou=people,{ROOT}",
            },
        ),
        DemoEntry(
            f"cn=bob,ou=people,{ROOT}",
            ["top", "person", "inetOrgPerson"],
            {
                "cn": "bob",
                "uid": "bob42",
                "sn": "Okafor",
                "mail": "bob@demo.local",
                "title": "Operator",
                "manager": f"cn=alice+uid=alice99,ou=people,{ROOT}",
                "userCertificate": _CERT_BYTES,
            },
        ),
        # Name containing every character that must be escaped in an RDN.
        # The wire DN is produced via ldap3's escape_rdn (hand-crafting the
        # backslashes double-escapes the value inside ldap3's mock DIT).
        DemoEntry(
            f"cn=Carol \\\"C\\\"\\+Cao\\, \\<retired\\>\\;,ou=people,{ROOT}",
            ["top", "person", "inetOrgPerson"],
            {
                "cn": 'Carol "C"+Cao, <retired>;',
                "sn": "Cao",
                "mail": "carol@demo.local",
                "title": "Escaping Test Case",
            },
        ),
        DemoEntry(
            f"cn=dave,ou=people,{ROOT}",
            ["top", "person", "inetOrgPerson"],
            {
                "cn": "dave",
                "uid": "dave7",
                "sn": "Lindqvist",
                "mail": "dave@demo.local",
                # Points at an entry that does not exist: an unresolved regular
                # membership/reference, kept but flagged, never deleted.
                "manager": f"cn=ghost,ou=people,{ROOT}",
            },
        ),
        # ---- groups ---------------------------------------------------------
        # 10 members -> above the demo range threshold, served in range pages.
        DemoEntry(
            f"cn=all-staff,ou=groups,{ROOT}",
            ["top", "groupOfNames"],
            {
                "cn": "all-staff",
                "member": [f"cn=user{i:02d},ou=people,{ROOT}" for i in range(10)],
                "owner": f"cn=alice+uid=alice99,ou=people,{ROOT}",
            },
        ),
        # Small group: below threshold, returned without range segmentation.
        DemoEntry(
            f"cn=admins,ou=groups,{ROOT}",
            ["top", "groupOfNames"],
            {
                "cn": "admins",
                "member": [
                    f"cn=alice+uid=alice99,ou=people,{ROOT}",
                    f"cn=bob,ou=people,{ROOT}",
                ],
            },
        ),
        # ---- devices: multi-valued segmented non-DN attribute ---------------
        DemoEntry(
            f"cn=router-01,ou=devices,{ROOT}",
            ["top", "device", "ieee802Device"],
            {
                "cn": "router-01",
                "serialNumber": "RTR-001",
                "revisionHistory": [f"rev-{i:03d}: firmware change" for i in range(11)],
                "auditLog": [f"event-{i:03d}" for i in range(7)],
            },
        ),
        # ---- aliases --------------------------------------------------------
        # alias loop A -> B -> A. Entries stay in the DIT; expansion is what
        # gets blocked when the cycle is detected.
        DemoEntry(
            f"cn=alias-a,ou=aliases,{ROOT}",
            ["top", "alias"],
            {
                "cn": "alias-a",
                "aliasedObjectName": f"cn=alias-b,ou=aliases,{ROOT}",
            },
        ),
        DemoEntry(
            f"cn=alias-b,ou=aliases,{ROOT}",
            ["top", "alias"],
            {
                "cn": "alias-b",
                "aliasedObjectName": f"cn=alias-a,ou=aliases,{ROOT}",
            },
        ),
        # Self-referential alias: one-entry cycle.
        DemoEntry(
            f"cn=alias-self,ou=aliases,{ROOT}",
            ["top", "alias"],
            {
                "cn": "alias-self",
                "aliasedObjectName": f"cn=alias-self,ou=aliases,{ROOT}",
            },
        ),
        # Healthy alias resolving to a real person.
        DemoEntry(
            f"cn=john-alias,ou=aliases,{ROOT}",
            ["top", "alias"],
            {
                "cn": "john-alias",
                "aliasedObjectName": f"cn=Doe\\, John,ou=people,{ROOT}",
            },
        ),
        # Dangling alias: target missing, entry retained and reported.
        DemoEntry(
            f"cn=dangling-alias,ou=aliases,{ROOT}",
            ["top", "alias"],
            {
                "cn": "dangling-alias",
                "aliasedObjectName": f"cn=nobody,ou=people,{ROOT}",
            },
        ),
        # ---- referrals / cross-root references ------------------------------
        # A referral *object* in the local DIT pointing at another naming
        # context. Shown as an external reference, never auto-followed.
        DemoEntry(
            f"cn=partner-directory,ou=externals,{ROOT}",
            ["top", "referral"],
            {
                "cn": "partner-directory",
                "ref": [
                    "ldap://other.example.com:389/dc=partner,dc=com??sub",
                    "ldaps://backup.example.com:636/dc=partner,dc=com",
                ],
            },
        ),
        DemoEntry(
            f"ou=remote-users,ou=externals,{ROOT}",
            ["top", "referral", "organizationalUnit"],
            {
                "ou": "remote-users",
                "ref": ["ldap://other.example.com/dc=remote,dc=org??one"],
            },
        ),
        # A normal person carrying a DN-valued attribute that leaves the root.
        # This is *not* a referral object: the cross-root value is classified
        # as an external reference by the relationship layer.
        DemoEntry(
            f"cn=erin,ou=people,{ROOT}",
            ["top", "person", "inetOrgPerson"],
            {
                "cn": "erin",
                "uid": "erin5",
                "sn": "Petrov",
                "mail": "erin@demo.local",
                "seeAlso": "cn=external-contact,ou=partners,dc=partner,dc=com",
            },
        ),
    ]
    return entries


_ENTRIES = _build_entries()


class DemoDirectory:
    """Owns the single in-memory ldap3 server and opens connections to it."""

    def __init__(self) -> None:
        self._server = Server("demo-directory.local")
        bootstrap = Connection(self._server, client_strategy=MOCK_SYNC)
        bootstrap.bind()
        failed: list[tuple[str, str]] = []
        for entry in _ENTRIES:
            ok = bootstrap.add(entry.dn, entry.object_class, entry.attributes)
            if not ok:
                failed.append((entry.dn, str(bootstrap.result)))
        if failed:  # pragma: no cover - construction-time misconfiguration
            raise RuntimeError(f"demo DIT bootstrap failed: {failed}")
        # The mock can report add success while storing an entry under a
        # mangled key (e.g. a hand-double-escaped DN), so verify retrievability
        # of every declared entry rather than trusting the add result alone.
        missing: list[str] = []
        for entry in _ENTRIES:
            bootstrap.search(entry.dn, "(objectClass=*)", search_scope=BASE)
            if not bootstrap.response:
                missing.append(entry.dn)
        if missing:  # pragma: no cover - construction-time misconfiguration
            raise RuntimeError(f"demo DIT entries not retrievable after add: {missing}")
        bootstrap.unbind()
        self._bootstrap_entries = list(_ENTRIES)

    def connect(self) -> Connection:
        """Return a new connection bound to the shared in-memory server."""
        conn = Connection(
            self._server,
            client_strategy=MOCK_SYNC,
            raise_exceptions=True,
        )
        conn.bind()
        return conn

    def all_dns(self) -> list[str]:
        return [e.dn for e in self._bootstrap_entries]

    def exists(self, dn: str) -> bool:
        conn = self.connect()
        try:
            conn.search(dn, "(objectClass=*)", search_scope=BASE, attributes=ALL_ATTRIBUTES)
            return bool(conn.response)
        except LDAPException:
            return False
        finally:
            conn.unbind()


_directory: DemoDirectory | None = None


def get_directory() -> DemoDirectory:
    """Process-wide singleton (the mock DIT is read-only after bootstrap)."""
    global _directory
    if _directory is None:
        _directory = DemoDirectory()
    return _directory


# Allow test isolation to force a rebuild if ever needed.
def reset_directory() -> None:  # pragma: no cover - test helper
    global _directory
    _directory = None
    if "LDAP_DEMO_DISABLE_CACHE" in os.environ:
        get_directory()
