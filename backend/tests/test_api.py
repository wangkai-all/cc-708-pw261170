"""End-to-end HTTP tests against the FastAPI app."""

import base64

import pytest
from fastapi.testclient import TestClient

from ldap_console.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_health_and_config(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["naming_context"] == "dc=demo,dc=local"

    config = client.get("/api/config").json()
    assert "dc=demo,dc=local" in config["allowed_search_bases"]
    assert {s["value"] for s in config["scopes"]} == {"base", "one", "sub"}
    assert "member" in config["ranged_attributes"]


def test_subtree_search_returns_demo_entries(client):
    resp = client.post("/api/search", json={
        "base_dn": "dc=demo,dc=local",
        "scope": "sub",
    })
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] >= 20
    dns = [e["dn"] for e in payload["entries"]]
    assert any("Doe\\, John" in d for d in dns)          # escaped DN
    assert any("+uid=alice99" in d for d in dns)         # multi-valued RDN


def test_search_guard_blocks_foreign_root(client):
    resp = client.post("/api/search", json={
        "base_dn": "dc=attacker,dc=com",
        "scope": "sub",
    })
    assert resp.status_code == 403
    assert "demo directory" in resp.json()["detail"]


def test_subtree_search_blocked_from_arbitrary_entry_base(client):
    resp = client.post("/api/search", json={
        "base_dn": "cn=bob,ou=people,dc=demo,dc=local",
        "scope": "sub",
    })
    assert resp.status_code == 403


def test_base_scope_on_single_entry_allowed(client):
    resp = client.post("/api/search", json={
        "base_dn": "cn=bob,ou=people,dc=demo,dc=local",
        "scope": "base",
    })
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_field_filter_and_escaped_filter_chars(client):
    resp = client.post("/api/search", json={
        "base_dn": "ou=people,dc=demo,dc=local",
        "scope": "sub",
        "field_filters": [
            {"attribute": "sn", "value": "Okafor", "match": "exact"}
        ],
    })
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 1 and entries[0]["dn"].startswith("cn=bob")


def test_range_segments_complete_in_search_payload(client):
    resp = client.post("/api/search", json={
        "base_dn": "ou=groups,dc=demo,dc=local",
        "scope": "one",
    })
    group = next(
        e for e in resp.json()["entries"]
        if e["dn"].startswith("cn=all-staff")
    )
    report = group["range_reports"]["member"]
    assert report["complete"] is True
    assert report["coverage"]["missing_indices"] == []
    assert report["coverage"]["total_values"] == 10
    assert len(group["attributes"]["member"]["values"]) == 10
    # Segment inspection data is exposed per segment.
    assert report["segments"][0]["request_tag"] == "member"
    assert report["segments"][-1]["response_tag"] == "member;range=9-9"


@pytest.mark.parametrize("kind", ["gap", "overlap", "stall"])
def test_injected_range_faults_are_reported(client, kind):
    resp = client.post("/api/search", json={
        "base_dn": "ou=groups,dc=demo,dc=local",
        "scope": "one",
        "range_fault": {"kind": kind, "attribute": "member"},
    })
    group = next(
        e for e in resp.json()["entries"]
        if e["dn"].startswith("cn=all-staff")
    )
    faults = group["range_reports"]["member"]["faults"]
    assert any(f["kind"] == kind for f in faults)
    # The attribute must be marked incomplete until fully reassembled.
    assert group["attributes"]["member"]["complete"] is False


def test_binary_value_download_is_raw_bytes(client):
    dn = r"cn=Doe\, John,ou=people,dc=demo,dc=local"
    resp = client.get("/api/attributes/binary", params={
        "dn": dn, "attribute": "jpegPhoto", "index": 0
    })
    assert resp.status_code == 200
    assert resp.content[:2] == b"\xff\xd8"  # JPEG SOI, not UTF-8 text
    assert "attachment" in resp.headers["content-disposition"]


def test_binary_endpoint_refuses_text_attribute(client):
    resp = client.get("/api/attributes/binary", params={
        "dn": "cn=bob,ou=people,dc=demo,dc=local",
        "attribute": "cn", "index": 0,
    })
    assert resp.status_code == 409


def test_alias_resolution_endpoint(client):
    resp = client.get("/api/aliases/resolve", params={
        "dn": "cn=alias-a,ou=aliases,dc=demo,dc=local"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "cycle"


def test_dn_parse_endpoint_multi_valued(client):
    resp = client.get("/api/dn/parse", params={
        "dn": "cn=alice+uid=alice99,ou=people,dc=demo,dc=local"
    })
    data = resp.json()
    leaf = data["rdns"][0]
    assert leaf["multi_valued"] is True
    assert {a["type"] for a in leaf["avas"]} == {"cn", "uid"}


def test_dn_parse_rejects_garbage(client):
    resp = client.get("/api/dn/parse", params={"dn": ""})
    assert resp.status_code in (400, 422)


def test_ldif_export_contains_attribute_types_and_binary_marker(client):
    resp = client.post("/api/search", json={
        "base_dn": "ou=people,dc=demo,dc=local",
        "scope": "sub",
        "format": "ldif",
    })
    assert resp.status_code == 200
    assert "text/ldif" in resp.headers["content-type"]
    body = resp.text
    assert "dn: cn=Doe\\, John,ou=people,dc=demo,dc=local" in body
    assert "jpegPhoto:: " in body  # binary base64 form
    assert "objectClass: " in body
    # Decode the exported binary value to confirm integrity.
    line = next(l for l in body.splitlines() if l.startswith("jpegPhoto:: "))
    exported = base64.b64decode(line.split(":: ", 1)[1])
    assert exported[:2] == b"\xff\xd8"


def test_json_export_carries_attribute_syntax(client):
    resp = client.post("/api/search", json={
        "base_dn": "ou=people,dc=demo,dc=local",
        "scope": "sub",
    })
    john = next(
        e for e in resp.json()["entries"] if "Doe" in e["dn"]
    )
    assert john["attributes"]["jpegPhoto"]["syntax"] == "binary"
    assert john["attributes"]["cn"]["syntax"] == "text"
    assert john["attributes"]["mail"]["multi_valued"] is True


def test_referral_shown_as_external_not_followed(client):
    resp = client.post("/api/search", json={
        "base_dn": "ou=externals,dc=demo,dc=local",
        "scope": "one",
    })
    partner = next(
        e for e in resp.json()["entries"]
        if e["dn"].startswith("cn=partner-directory")
    )
    assert partner["kind"] == "referral"
    assert all(r["status"] == "external" for r in partner["relationships"])


def test_size_limit_enforced(client):
    resp = client.post("/api/search", json={
        "base_dn": "dc=demo,dc=local",
        "scope": "sub",
        "size_limit": 5,
    })
    assert resp.json()["truncated"] is True
    assert len(resp.json()["entries"]) == 5
