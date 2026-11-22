"""Binary-safe value decoding and LDIF encoding."""

import base64

from ldap_console.values import decode_value, ldif_encode_line, render_for_json


def test_known_binary_attribute_never_text_decoded():
    raw = b"\xff\xd8\xff\xe0binary"
    decoded = decode_value(raw, "jpegPhoto")
    assert decoded.kind == "binary"
    assert base64.b64decode(decoded.base64) == raw
    assert decoded.size == len(raw)


def test_attribute_options_still_classified_binary():
    assert decode_value(b"\xff\xfe", "jpegPhoto;binary").kind == "binary"


def test_invalid_utf8_falls_back_to_binary_without_replacement_chars():
    raw = "caf".encode() + b"\xff\xe9"
    decoded = decode_value(raw, "description")
    assert decoded.kind == "binary"
    assert decoded.utf8_error is not None
    assert "ufffd" not in (decoded.base64 or "")  # no U+FFFD substitution path
    assert base64.b64decode(decoded.base64) == raw


def test_valid_utf8_is_text():
    decoded = decode_value("héllo ☃".encode("utf-8"), "cn")
    assert decoded.kind == "text" and decoded.text == "héllo ☃"


def test_render_payload_shapes():
    text = render_for_json(b"abc", "cn")
    assert text == {"kind": "text", "size": 3, "value": "abc"}
    binary = render_for_json(b"\x00\x01", "userCertificate")
    assert binary["kind"] == "binary" and binary["base64"] == "AAE="


def test_ldif_binary_value_uses_double_colon():
    line = ldif_encode_line("jpegPhoto", b"\xff\xd8\xff")
    assert line.startswith("jpegPhoto:: ")
    assert base64.b64decode(line.split(":: ", 1)[1]) == b"\xff\xd8\xff"


def test_ldif_text_value_single_colon():
    line = ldif_encode_line("cn", "Doe, John".encode())
    assert line == "cn: Doe, John"


def test_ldif_leading_space_forces_base64():
    line = ldif_encode_line("description", b" starts with space")
    assert ":: " in line


def test_ldif_long_line_is_folded():
    raw = b"x" * 100
    line = ldif_encode_line("description", raw)
    first, second = line.split("\n", 1)
    assert len(first) == 76 and second.startswith(" ")


def test_ldif_unicode_text_stays_utf8():
    line = ldif_encode_line("sn", "Müller".encode("utf-8"))
    assert line == "sn: Müller"
