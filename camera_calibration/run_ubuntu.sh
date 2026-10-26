#!/usr/bin/env bash
set -Eeuo pipefail
CALIBRATION_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$CALIBRATION_DIR/.." && pwd)"
CALIBRATION_ACTION="${1:-capture}"
if [[ $# -gt 0 ]]; then shift; fi
CALIBRATION_STAMP="$(date +%Y%m%d_%H%M%S_%N)"
case "$CALIBRATION_ACTION" in
  capture|snapshot)
    CALIBRATION_OUTPUT="$CALIBRATION_DIR/sessions/ubuntu_$CALIBRATION_STAMP"
    CALIBRATION_ARGS=("$CALIBRATION_DIR/capture.py" --output "$CALIBRATION_OUTPUT")
    if [[ "$CALIBRATION_ACTION" == snapshot ]]; then CALIBRATION_ARGS+=(--snapshot); fi
    ;;
  analyze)
    if [[ $# -lt 1 ]]; then echo 'Usage: run_ubuntu.sh analyze SESSION_DIRECTORY' >&2; exit 2; fi
    CALIBRATION_INPUT="$1"; shift
    CALIBRATION_ARGS=("$CALIBRATION_DIR/analyze.py" --input "$CALIBRATION_INPUT" --output "$CALIBRATION_DIR/results/analysis_$CALIBRATION_STAMP")
    ;;
  *) echo 'Action must be capture, snapshot, or analyze' >&2; exit 2 ;;
esac
/usr/bin/python3 -B -u "$PROJECT_DIR/setup/run_logged.py" --root "$PROJECT_DIR" --cwd "$PROJECT_DIR" \
  --label "checkerboard_$CALIBRATION_ACTION" \
  --note "${FP_RUN_NOTE:-Isolated checkerboard verification; actual pattern and reported spacing recorded from board.json; no device calibration writes.}" \
  -- "$PROJECT_DIR/.camera-venv/bin/python" -B -u "${CALIBRATION_ARGS[@]}" "$@"
if [[ "$CALIBRATION_ACTION" == capture ]]; then
  /usr/bin/python3 -B -u "$PROJECT_DIR/setup/run_logged.py" --root "$PROJECT_DIR" --cwd "$PROJECT_DIR" \
    --label checkerboard_analysis --note "Checkerboard diagnostic candidates; no device calibration writes" \
    -- "$PROJECT_DIR/.camera-venv/bin/python" -B -u "$CALIBRATION_DIR/analyze.py" \
    --input "$CALIBRATION_OUTPUT" --output "$CALIBRATION_DIR/results/ubuntu_$CALIBRATION_STAMP"
fi
