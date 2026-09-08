#!/usr/bin/env bash
set -euo pipefail

exec xvfb-run \
  --auto-servernum \
  --server-args="${XVFB_SERVER_ARGS:--screen 0 1440x900x24 -ac +extension RANDR}" \
  /app/.venv/bin/python -m uvicorn "${APP_MODULE:-app.api.main:app}" \
    --host "${API_HOST:-0.0.0.0}" \
    --port 8000 \
    --workers 1 \
    --log-level "${API_LOG_LEVEL:-info}"
