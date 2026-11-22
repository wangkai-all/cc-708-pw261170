#!/usr/bin/env bash
# Start the Vite dev server (proxies /api to the backend on 127.0.0.1:8000).
set -euo pipefail
cd "$(dirname "$0")"
exec npm run dev "$@"
