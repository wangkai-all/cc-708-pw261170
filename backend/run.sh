#!/usr/bin/env bash
# Start the LDAP reception console backend (demo directory only, no network).
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/app${PYTHONPATH:+:$PYTHONPATH}"
exec ../.venv/bin/uvicorn ldap_console.main:create_app --factory \
  --host 127.0.0.1 --port "${PORT:-8000}" "$@"
