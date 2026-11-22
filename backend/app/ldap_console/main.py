"""FastAPI application wiring for the LDAP reception console."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import console

# Repository layout: backend/app/ldap_console/main.py -> frontend/dist
_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="LDAP Reception Console",
        version="1.0.0",
        description=(
            "Read-only console over the bundled demo LDAP directory. "
            "Supports scoped searches, range-segmented attributes, alias "
            "cycle detection, external referrals and binary-safe values."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(console.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "naming_context": settings.naming_context}

    # Serve the built Svelte bundle single-origin when it exists. In
    # development, `npm run dev` serves the frontend on :5173 and proxies
    # /api here instead, so missing dist is entirely normal.
    if _FRONTEND_DIST.is_dir():
        assets = _FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=assets),
                name="assets",
            )

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(_FRONTEND_DIST / "index.html")

        @app.get("/favicon.ico", include_in_schema=False)
        def favicon():
            icon = _FRONTEND_DIST / "favicon.ico"
            if icon.exists():
                return FileResponse(icon)
            return JSONResponse(status_code=404, content={})

    @app.exception_handler(Exception)
    async def unhandled(_request, exc):  # pragma: no cover - defensive
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return app
