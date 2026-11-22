"""HTTP routes exposed to the Svelte frontend."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import dn_utils
from ..config import settings
from ..exporters import export_json, export_ldif
from ..service import LdapConsoleService, SearchGuardError, SearchQuery

router = APIRouter(prefix="/api", tags=["console"])
_service = LdapConsoleService()


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class FieldFilter(BaseModel):
    attribute: str
    value: str = ""
    match: str = Field(default="exact",
                       pattern="^(exact|substring|starts|present)$")


class RangeFault(BaseModel):
    kind: str = Field(pattern="^(gap|overlap|stall)$")
    attribute: str


class SearchRequest(BaseModel):
    base_dn: str
    scope: str = Field(default="sub", pattern="^(base|one|sub)$")
    attributes: list[str] = Field(default_factory=lambda: ["*"])
    object_class: str | None = None
    field_filters: list[FieldFilter] = Field(default_factory=list)
    raw_filter: str | None = None
    size_limit: int = Field(default=100, ge=1, le=settings.max_search_entries)
    range_fault: RangeFault | None = None
    format: str = Field(default="json", pattern="^(json|ldif)$")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/config")
def get_config() -> dict[str, Any]:
    """Everything the UI needs to render its selectors (allowed bases only)."""
    return {
        "naming_context": settings.naming_context,
        "allowed_search_bases": list(settings.allowed_search_bases),
        "scopes": [
            {"value": "base", "label": "base — the entry itself only"},
            {"value": "one", "label": "one — immediate children"},
            {"value": "sub", "label": "sub — whole subtree"},
        ],
        "ranged_attributes": sorted(settings.ranged_attributes),
        "binary_attributes": sorted(settings.binary_attributes),
        "dn_valued_attributes": sorted(settings.dn_valued_attributes),
        "range_page_size": settings.range_page_size,
        "range_threshold": settings.range_threshold,
        "fault_kinds": ["gap", "overlap", "stall"],
    }


@router.post("/search")
def search(request: SearchRequest):
    query = SearchQuery(
        base_dn=request.base_dn,
        scope=request.scope,
        attributes=request.attributes,
        object_class=request.object_class,
        field_filters=[f.model_dump() for f in request.field_filters],
        raw_filter=request.raw_filter,
        size_limit=request.size_limit,
        range_fault=request.range_fault.model_dump() if request.range_fault else None,
    )
    try:
        payload = _service.search(query)
    except SearchGuardError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SearchFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if request.format == "ldif":
        body = export_ldif(payload)
        filename = f"ldap-search-{quote(request.base_dn, safe='')}.ldif"
        return Response(
            content=body,
            media_type="text/ldif; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return payload


@router.get("/entries/lookup")
def lookup_entry(dn: str):
    try:
        return _service.get_entry(dn)
    except SearchGuardError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no such entry: {dn}")
    except SearchFailed as exc:  # pragma: no cover
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/aliases/resolve")
def resolve_alias(dn: str) -> dict[str, Any]:
    try:
        return _service.resolve_alias(dn)
    except SearchGuardError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/dn/parse")
def parse_dn_endpoint(dn: str) -> dict[str, Any]:
    """Expose the library-based DN parser for the UI's DN inspector."""
    parsed = dn_utils.safe_parse(dn)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"invalid DN: {dn}")
    return {
        "dn": parsed.render(),
        "rdns": [
            {
                "multi_valued": rdn.is_multi_valued,
                "avas": [{"type": attr, "value": value} for attr, value in rdn.avas],
                "rendered": rdn.rendered(),
            }
            for rdn in parsed.rdns
        ],
        "parent": parsed.render_parent() or None,
    }


@router.post("/export")
def export(request: SearchRequest):
    """Convenience endpoint forcing a downloadable export regardless of view."""
    request.format = "ldif" if request.format != "json" else "json"
    return search(request)


@router.get("/attributes/binary")
def binary_value(dn: str, attribute: str, index: int = Query(0, ge=0)):
    """Stream one raw binary value (never UTF-8 decoded) for download."""
    try:
        entry = _service.get_entry(dn)
    except SearchGuardError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no such entry: {dn}")
    attr = entry["attributes"].get(attribute)
    if attr is None:
        raise HTTPException(status_code=404,
                            detail=f"attribute {attribute} absent on {dn}")
    if index >= len(attr["values"]):
        raise HTTPException(status_code=404, detail="value index out of range")
    value = attr["values"][index]
    if value["kind"] != "binary":
        raise HTTPException(status_code=409,
                            detail=f"{attribute}[{index}] is not binary")
    import base64

    raw = base64.b64decode(value["base64"])
    ext = "bin"
    if attribute.lower() in {"jpegphoto", "photo", "thumbnailphoto"}:
        ext = "jpg"
    elif attribute.lower() in {"usercertificate", "cacertificate"}:
        ext = "der"
    filename = f"{attribute}-{index}.{ext}"
    return Response(
        content=raw,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
