#!/usr/bin/env bash
set -eu
cd /data/ZJC/foundationPos
camera_python=/data/ZJC/foundationPos/.camera-venv/bin/python
bash setup/run_logged.sh --label cup_windows_receive_sha256 --note '核对 Windows 杯子检查图、原始深度、内参和报告，检查8个文件SHA256。' -- "$camera_python" setup/finalize_transfer.py --root foundationpose_data/windows_captures/cup_check_20261013_152557
bash setup/run_logged.sh --label cup_windows_import_run_records --note '追加 Windows 杯子检查和同步档案；不覆盖历史索引。' -- "$camera_python" setup/import_windows_run_records.py
bash setup/run_logged.sh --label cup_windows_session_notes --note '补录目标杯子、背光、原始深度修正以及启动帧问题，保留全部成功与失败证据。' -- "$camera_python" setup/append_manual_records.py --event-id WINDOWS-CUP-CHECK-20261013-152557 --experiment reports/cup_check_experiment_notes_20261013.md --issues reports/cup_check_issue_notes_20261013.md
