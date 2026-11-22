"""Runtime configuration for the LDAP reception console.

The console is deliberately locked to the bundled demo directory. There is no
way for a client to point the backend at an arbitrary LDAP host: the only
"server" ever connected to is the in-process ldap3 mock defined in
``demo_directory``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# The single naming context the demo directory serves.
DEMO_NAMING_CONTEXT = "dc=demo,dc=local"

# Search bases offered in the web UI. Every one must be inside the naming
# context; the search guard rejects anything outside this set.
ALLOWED_SEARCH_BASES: tuple[str, ...] = (
    "dc=demo,dc=local",
    "ou=people,dc=demo,dc=local",
    "ou=groups,dc=demo,dc=local",
    "ou=aliases,dc=demo,dc=local",
    "ou=externals,dc=demo,dc=local",
    "ou=devices,dc=demo,dc=local",
)

# Attributes that are always treated as binary (RFC 4517 syntaxes commonly
# used in demo directories). Any *other* attribute whose bytes fail strict
# UTF-8 decoding is also kept binary rather than forced to text.
BINARY_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "jpegphoto",
        "photo",
        "thumbnailphoto",
        "usercertificate",
        "cacertificate",
        "certificaterevocationlist",
        "objectsid",
        "objectguid",
    }
)

# Attributes whose values are DNs naming other entries (regular membership /
# manager links, kept separately from aliases and referrals).
DN_VALUED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "member",
        "uniquemember",
        "manager",
        "owner",
        "memberof",
        "seealso",
        "roleoccupant",
    }
)

# Object classes that mark an entry as an alias (RFC 4512).
ALIAS_OBJECT_CLASSES: frozenset[str] = frozenset({"alias", "aliasobject"})

# Object classes that mark a referral object.
REFERRAL_OBJECT_CLASSES: frozenset[str] = frozenset({"referral", "extensibleobject"})

# Attributes whose values are segmented by the demo service using range tags.
# This is a service-specific contract of the demo directory, not an LDAP
# guarantee: real servers may not support range retrieval at all.
RANGED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "member",
        "revisionhistory",
        "auditlog",
    }
)

# Demo service page size for range segmentation.
RANGE_PAGE_SIZE = 3

# Above this number of values a ranged attribute is segmented even when the
# client did not explicitly request a range (mirrors AD behaviour, which the
# demo service emulates).
RANGE_THRESHOLD = 4


@dataclass(frozen=True)
class Settings:
    naming_context: str = DEMO_NAMING_CONTEXT
    allowed_search_bases: tuple[str, ...] = field(default=ALLOWED_SEARCH_BASES)
    binary_attributes: frozenset[str] = field(default=BINARY_ATTRIBUTES)
    dn_valued_attributes: frozenset[str] = field(default=DN_VALUED_ATTRIBUTES)
    alias_object_classes: frozenset[str] = field(default=ALIAS_OBJECT_CLASSES)
    referral_object_classes: frozenset[str] = field(default=REFERRAL_OBJECT_CLASSES)
    ranged_attributes: frozenset[str] = field(default=RANGED_ATTRIBUTES)
    range_page_size: int = field(default=int(os.getenv("LDAP_DEMO_RANGE_PAGE_SIZE", RANGE_PAGE_SIZE)))
    range_threshold: int = field(default=int(os.getenv("LDAP_DEMO_RANGE_THRESHOLD", RANGE_THRESHOLD)))
    max_search_entries: int = field(default=int(os.getenv("LDAP_DEMO_MAX_ENTRIES", 200)))


settings = Settings()
