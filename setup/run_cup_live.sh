#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
exec /usr/bin/python3 "$ROOT/setup/run_logged.py" --root "$ROOT" \
  --label cup_live_rgbd_pose \
  --note "${FP_RUN_NOTE:-Direct Ubuntu D435i; candidate cup mesh; manual first-frame ROI; estimated pose, no GT.}" \
  -- "$ROOT/.camera-venv/bin/python" -B -u "$ROOT/setup/run_cup_live.py" "$@"
