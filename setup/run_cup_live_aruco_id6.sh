#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
export FP_RUN_NOTE="${FP_RUN_NOTE:-User confirmed ArUco ID 6, measured BLACK outer side 30 mm; cup and marker fixed, move only camera; first-frame aligned drift, no independent absolute mesh calibration.}"
exec bash "$ROOT/setup/run_cup_live_fast.sh" \
  --aruco-id 6 --aruco-dictionary DICT_5X5_50 --aruco-marker-length-m 0.030 --aruco-fixed-scene "$@"
