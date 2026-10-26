#!/usr/bin/env bash
# Use the existing verified native environment, with independent run evidence.
set -euo pipefail
OBJ_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export OMP_NUM_THREADS=4
exec bash "$OBJ_ROOT/setup/run_logged.sh" --root "$OBJ_ROOT" --cwd "$OBJ_ROOT" \
  --label obj_open3d_environment_check --note synthetic_ICP_pose_graph_TSDF_OBJ_only \
  -- /home/ni/anaconda3/envs/foundationpose/bin/python -B -u \
  "$OBJ_ROOT/setup/verify_obj_environment.py" "$@"
