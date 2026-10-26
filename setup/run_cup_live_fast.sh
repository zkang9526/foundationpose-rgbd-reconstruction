#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
exec /usr/bin/python3 "$ROOT/setup/run_logged.py" --root "$ROOT" \
  --label cup_live_fast_rgbd_aruco \
  --note "${FP_RUN_NOTE:-D435i latest-frame 30Hz; frozen RGB SAM box/points by default; official FP 2 iterations; optional measured ArUco reference; no absolute GT.}" \
  -- "$ROOT/.camera-venv/bin/python" -B -u "$ROOT/setup/run_cup_live_fast.py" "$@"
