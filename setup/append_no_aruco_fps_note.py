#!/usr/bin/env python3
"""Append the no-marker live FPS entry without replacing existing guides."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
args = p.parse_args()
root = args.root.resolve(strict=True)
marker = '<!-- CUP-NO-ARUCO-FPS-START-20261015 -->'
text = ('2026-10-15用户先测试FPS、暂不贴ArUco。可用 `bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000`，不传任何ArUco参数，仍自动留档；Ubuntu打开 `http://127.0.0.1:8765`，相机对准完整杯子，停稳、冻结、框选并检查Mask、初始化后再移动。当前会话已启动时直接打开页面，避免重复占用端口/相机。初次检查镜头朝天花板，等待目标入镜，尚无本次杯子跟踪FPS；问题待现场复验，不标记已解决。见[启动与记录](reports/CUP_NO_ARUCO_FPS_START_20261015.md)和[问题处理](reports/CUP_NO_ARUCO_FPS_ISSUES_20261015.md)。')
for name in ('REPRODUCTION_GUIDE.md', 'D435i_connection.md'):
    path = root / name
    old = path.read_text(encoding='utf-8')
    if marker not in old:
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n' + marker + '\n' + text + '\n')
print('No-ArUco FPS start note appended; no inference configuration changed')
