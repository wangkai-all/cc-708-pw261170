"""Result exporters.

Two formats, both carrying the attribute *type* alongside values:

* JSON: structured document with per-value syntax (text/binary), range
  reports and relationship classification.
* LDIF (RFC 2849): line-based export where binary and unsafe values use the
  ``attr:: <base64>`` form. Values are re-fetched as raw bytes so no
  pre-decoded text is re-encoded blindly.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from .values import ldif_encode_line


def export_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)


def export_ldif(search_payload: dict[str, Any]) -> str:
    lines: list[str] = ["# LDIF export from demo LDAP reception console"]
    lines.append(f"# search base: {search_payload['base_dn']}")
    lines.append(f"# scope: {search_payload['scope']}  filter: {search_payload['filter']}")
    lines.append("version: 1")
    lines.append("")

    for entry in search_payload["entries"]:
        lines.append(f"dn: {entry['dn']}")
        # objectClass first, then remaining attributes sorted by name.
        attrs = entry["attributes"]
        ordered = sorted(attrs.items(), key=lambda kv: (kv[0].lower() != "objectclass",
                                                        kv[0].lower()))
        for attr_name, attr in ordered:
            for value in attr["values"]:
                raw = _raw_from_value(value)
                lines.append(ldif_encode_line(attr_name, raw))
        if entry.get("range_reports"):
            for name, report in entry["range_reports"].items():
                lines.append(
                    f"# range-report: {name} complete={report['complete']} "
                    f"segments={report['coverage'].get('segments', 0)} "
                    f"faults={[f['kind'] for f in report['faults']]}"
                )
        for rel in entry.get("relationships", []):
            lines.append(
                f"# relationship: kind={rel['kind']} attr={rel['attribute']} "
                f"target={rel['target_dn']} status={rel['status']}"
            )
        lines.append("")
    return "\n".join(lines)


def _raw_from_value(value: dict[str, Any]) -> bytes:
    if value["kind"] == "binary":
        return base64.b64decode(value["base64"])
    return str(value["value"]).encode("utf-8")
