#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
export FP_RUN_NOTE="${FP_RUN_NOTE:-Red-painted cup72 candidate, metric vertex RGB; SAM2 first-frame mask and automatic reacquisition; fixed cup and ID6 30mm black-side marker, move only camera; geometry and absolute 6D accuracy not accepted.}"
exec bash "$ROOT/setup/run_cup_live_aruco_id6.sh" \
  --mesh-profile redcup72 --mask-backend sam2 --auto-reacquire --cup-yaw-init "$@"
