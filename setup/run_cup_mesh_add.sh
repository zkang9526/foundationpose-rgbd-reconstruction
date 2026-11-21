#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
export FP_RUN_NOTE="${FP_RUN_NOTE:-Fixed cup AND ID6 marker (black side 30mm, DICT_5X5_50); only camera moves. First-frame anchored relative ADD/ADD-S, no absolute GT.}"
exec /usr/bin/python3 "$ROOT/setup/run_logged.py" --root "$ROOT" \
  --label cup_mesh_relative_add_capture \
  --note "$FP_RUN_NOTE" \
  -- "$ROOT/.camera-venv/bin/python" -B -u "$ROOT/setup/run_cup_mesh_add.py" "$@"
