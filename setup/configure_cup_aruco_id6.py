#!/usr/bin/env python3
"""Append the ID6 protocol and recorder sources without replacing host-specific files."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
args = p.parse_args()
root = args.root.resolve(strict=True)
logger = root / 'setup/run_logged.py'
text = logger.read_text(encoding='utf-8-sig')
names = ('inspect_cup_aruco_scene.py', 'run_cup_live_aruco_id6.sh', 'cup_live_control.py', 'configure_cup_aruco_id6.py',
         'verify_cup_aruco_id6.py', 'analyze_cup_aruco_id6.py', 'finalize_cup_aruco_id6.py',
         'review_saved_cup_aruco.py', 'verify_cup_review_download.py', 'verify_cup_dashboard_restart.py',
         'filter_cup_reference_stability.py')
missing = [name for name in names if repr(name) not in text and ('"' + name + '"') not in text]
if missing:
    text = text.replace('SOURCE_NAMES = (', 'SOURCE_NAMES = (\n    ' + ', '.join(map(repr, missing)) + ',', 1)
    with logger.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
marker = '<!-- CUP-ARUCO-ID6-30MM-20261015 -->'
guide = root / 'REPRODUCTION_GUIDE.md'
if marker not in guide.read_text(encoding='utf-8-sig'):
    with guide.open('a', encoding='utf-8') as stream:
        stream.write('\n' + marker + '''
## 固定杯子/码，只移动相机：ID 6、黑边实测30 mm

现场原始RGB已识别为5×5家族（ID6可由DICT_5X5_50解码；不声称知道打印时选的完整字典大小）。
Ubuntu运行：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_aruco_id6.sh --duration-seconds 1200 --max-frames 6000
```
打开 http://127.0.0.1:8765 ，首次冻结、框选完整杯子及杯把，生成并检查SAM Mask，再初始化。
初始化期间相机停稳；进入跟踪后先静止30秒，再缓慢移动30秒、较快移动30秒，最后返回停稳10秒。
杯子和码全程固定，记录各阶段的实际时间；计划时长本身不代表已执行阶段。
码短边至少25像素才进入参考求解，建议40像素以上；页面初始化前显示码尺寸/有效性。
DICT_5X5_50、ID6、0.030m和fixed-scene由专用入口设置；通用入口默认4×4/ID0保持可用。
所有误差来自同一推理RGB，失跟或参考拒绝时留空，不把缺失数据当零误差。
结束自动生成会话evaluation_summary/report.json和aruco_errors.csv；原始RGB-D、角点、矩阵、时间戳和失败记录保留。
这些是首帧对齐后的相对漂移，不能作为绝对6D精度；绝对值需独立T_marker_from_original_mesh标定。
''')
guide_text = guide.read_text(encoding='utf-8-sig')
updated = guide_text.replace('bash setup/run_cup_live_aruco_id6.sh --duration-seconds 600 --max-frames 4500',
                             'bash setup/run_cup_live_aruco_id6.sh --duration-seconds 1200 --max-frames 6000')
if updated != guide_text:
    with guide.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(updated)
restart_marker = '<!-- CUP-DASHBOARD-RESTART-20261015 -->'
if restart_marker not in guide.read_text(encoding='utf-8-sig'):
    with guide.open('a', encoding='utf-8') as stream:
        stream.write('\n' + restart_marker + '''
重新启动后，waiting_for_roi表示模型和图像已就绪，需重新冻结、框选、生成Mask并确认初始化。
页面识别新的会话目录后清除旧冻结/框选/提示点/Mask版本；第一次使用更新后刷新一次页面。
本次修改只改善提示和会话切换，不复用上一轮Mask，不改变FoundationPose姿态估计或精度门限。
''')
print('ID6 sources and reproduction note appended:', root)
