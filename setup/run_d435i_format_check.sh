#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
exec /usr/bin/python3 "$ROOT/setup/run_logged.py" \
  --label d435i_format_check --note "${FP_RUN_NOTE:-}" -- \
  "$ROOT/.camera-venv/bin/python" "$ROOT/setup/check_capture_files.py" "$@"
