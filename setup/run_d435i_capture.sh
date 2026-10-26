#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
exec /usr/bin/python3 "$ROOT/setup/run_logged.py" \
  --label d435i_capture --note "${FP_RUN_NOTE:-}" -- \
  "$ROOT/.camera-venv/bin/python" "$ROOT/setup/capture_d435i.py" "$@"
