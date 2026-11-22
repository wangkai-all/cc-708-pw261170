#!/usr/bin/env bash
# Serve the built Svelte bundle and the API from one FastAPI origin.
# Requires `npm run build` (in frontend/) to have produced frontend/dist.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn --app-dir backend/app \
  ldap_console.main:create_app --factory \
  --host 127.0.0.1 --port "${PORT:-8000}" "$@"
