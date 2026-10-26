#!/usr/bin/env bash
# Verify successful file checking and a deliberately failed command are archived.
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
cd "$ROOT"
export FP_RUN_NOTE='记录器验证：读取此前30帧短测数据，验证自动留档；不采集新相机画面'
bash "$ROOT/setup/run_d435i_format_check.sh" \
  "$ROOT/foundationpose_data/camera_capture_format_check_20261013"
set +e
bash "$ROOT/setup/run_logged.sh" --label logging_expected_failure \
  --note '记录器预期失败测试：人为退出7，检查stdout/stderr及失败证据；不是实际相机或模型故障' -- \
  /usr/bin/python3 -c 'import sys; print("LOGGER_STDOUT_MARKER", flush=True); print("LOGGER_STDERR_MARKER", file=sys.stderr, flush=True); sys.exit(7)'
failure_code=$?
set -e
if [ "$failure_code" -ne 7 ]; then
  printf 'Expected exit 7, got %s\n' "$failure_code" >&2
  exit 1
fi
python3 "$ROOT/setup/verify_logging_outputs.py"
