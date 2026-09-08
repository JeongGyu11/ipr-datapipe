#!/usr/bin/env bash
set -euo pipefail

config_path="${CRAWLER_CONFIG_PATH:-/app/config.container.yaml}"
if [[ ! -f "${config_path}" ]]; then
  echo "crawler config not found: ${config_path}" >&2
  exit 78
fi

exec xvfb-run \
  --auto-servernum \
  --server-args="${XVFB_SERVER_ARGS:--screen 0 1440x900x24 -ac +extension RANDR}" \
  /app/.venv/bin/python /app/main.py --config "${config_path}" "$@"
