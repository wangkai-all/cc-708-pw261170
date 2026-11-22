"""Binary-safe value handling for LDAP attribute values.

LDAP attribute values arrive as bytes. Text attributes are decoded with
**strict** UTF-8; any failure means the value is kept as binary and presented
as base64 rather than being force-decoded (which would produce replacement
characters and silently corrupt data). Attributes with known binary syntaxes
never attempt text decoding at all.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from .config import settings

# RFC 2849 LDIF-safe: a value must be base64 encoded when it contains
# non-printable characters, starts with a space/colon/<, or ends with space.
_LDIF_UNSAFE_CHARS = set(range(0x00, 0x20)) | {0x7F}


@dataclass(frozen=True)
class DecodedValue:
    kind: str  # "text" | "binary"
    text: str | None = None
    base64: str | None = None
    size: int = 0
    utf8_error: str | None = None


def is_binary_attribute(attribute_name: str) -> bool:
    base = attribute_name.split(";", 1)[0].strip().lower()
    return base in settings.binary_attributes


def decode_value(raw: bytes, attribute_name: str) -> DecodedValue:
    """Decode one raw attribute value without ever forcing UTF-8."""
    if not isinstance(raw, (bytes, bytearray)):
        # ldap3 occasionally pre-formats some values; normalize defensively.
        raw = str(raw).encode("utf-8")
    raw = bytes(raw)

    if is_binary_attribute(attribute_name):
        return DecodedValue(
            kind="binary",
            base64=base64.b64encode(raw).decode("ascii"),
            size=len(raw),
        )

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return DecodedValue(
            kind="binary",
            base64=base64.b64encode(raw).decode("ascii"),
            size=len(raw),
            utf8_error=f"strict utf-8 failed at byte {exc.start}: {exc.reason}",
        )
    return DecodedValue(kind="text", text=text, size=len(raw))


def render_for_json(raw: bytes, attribute_name: str) -> dict[str, object]:
    decoded = decode_value(raw, attribute_name)
    payload: dict[str, object] = {"kind": decoded.kind, "size": decoded.size}
    if decoded.kind == "text":
        payload["value"] = decoded.text
    else:
        payload["base64"] = decoded.base64
        if decoded.utf8_error:
            payload["utf8_error"] = decoded.utf8_error
    return payload


def ldif_encode_line(attribute_name: str, raw: bytes) -> str:
    """Render one attribute value as an RFC 2849 LDIF line (folded at 76)."""
    needs_b64 = _needs_base64(raw)
    if needs_b64:
        encoded = base64.b64encode(raw).decode("ascii")
        head = f"{attribute_name}:: "
    else:
        encoded = raw.decode("utf-8")
        head = f"{attribute_name}: "
    return _fold(head + encoded)


def _needs_base64(raw: bytes) -> bool:
    if not raw:
        return False
    # Anything that is not valid strict UTF-8 is binary for LDIF purposes:
    # RFC 2849 requires the base64 form rather than a lossy text decode.
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return True
    if raw[0] in (ord(" "), ord(":"), ord("<")):
        return True
    if raw[-1] == ord(" "):
        return True
    return any(byte in _LDIF_UNSAFE_CHARS for byte in raw)


def _fold(line: str) -> str:
    if len(line) <= 76:
        return line
    chunks = [line[:76]]
    rest = line[76:]
    while rest:
        chunks.append(" " + rest[:75])
        rest = rest[75:]
    return "\n".join(chunks)
