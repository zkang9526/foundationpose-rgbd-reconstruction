#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
exec /usr/bin/python3 "$ROOT/setup/run_logged.py" --root "$ROOT" --label ubuntu_realsense_viewer_gui --note "Native Viewer for camera framing; stop before FoundationPose; no calibration or firmware action" -- /usr/bin/env LD_LIBRARY_PATH=/data/ZJC/foundationPos/foundationpose_data/tools/realsense_viewer_20261018_v2/root/usr/lib/x86_64-linux-gnu /data/ZJC/foundationPos/foundationpose_data/tools/realsense_viewer_20261018_v2/root/usr/bin/realsense-viewer "$@"
