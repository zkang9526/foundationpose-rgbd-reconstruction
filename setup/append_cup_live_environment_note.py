#!/usr/bin/env python3
"""Append verified live setup status to guides; preserve existing server history."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--verification', type=Path, required=True)
args = p.parse_args()
root = args.root.resolve(strict=True)
proof = json.loads(args.verification.read_text(encoding='utf-8'))
if not proof.get('passed') or proof['packages']['opencv-python-headless'] != '4.11.0.86':
    raise ValueError('Need the successful actual GPU/HTTP replay proof')
marker = '<!-- CUP-LIVE-SETUP-20261014 -->'
link = '[Ubuntu实时杯子位姿初跑](reports/CUP_LIVE_POSE_20261014.md)'
notes = {
    'Ubuntu_environment.md': '2026-10-14：独立Ubuntu `.camera-venv`新增 `opencv-python-headless==4.11.0.86`，NumPy1.26.4、SDK2.55.1.6486、Pillow12.3.0保持；pip check及实际CPU/GPU导入通过。主机USB采集+现有FoundationPose容器文件桥接，不改GPU/模型环境或容器USB权限。GPU/HTTP回放验证通过；现场相机、实时FPS与位姿精度尚未验证。说明见' + link + '。',
    'D435i_connection.md': '2026-10-14新增Ubuntu直连实时入口：`bash setup/run_cup_live.sh`，需D435i接Ubuntu USB3；本次探测设备0，现场硬件验证待接机。浏览器首次冻结/框选Mask，官方register后track；自动记录实际推理RGB-D/K/SDK时间戳/姿态/叠图。离线GPU/HTTP测试通过，不能当相机对齐或6D精度验收。说明见' + link + '。',
    'REPRODUCTION_GUIDE.md': 'Ubuntu直连实时初跑新增 `bash setup/run_cup_live.sh`，自动双层留档；默认10分钟或2000个处理帧。浏览器框选初始化后跟踪，保存每个实际推理帧，丢弃积压相机帧并记录处理节奏。停止/暂停/重初始化回放测试通过，实际相机未连接时不能称现场验证完成。操作见' + link + '。',
    'AGENTS.md': '- 2026-10-14按用户新增Ubuntu直连D435i实时位姿初跑入口`setup/run_cup_live.sh`。主机采集/浏览器同冻结帧ROI+GrabCut初始化，现有官方容器register/track，保存实际推理原RGB-D、K、时间戳、矩阵、叠图、控制与失败记录。重复照片GPU/HTTP/推理中停止留档验证通过；现场相机尚未接入，实时FPS与准确度未验收。候选网格缺陷保留，首次Mask需检查；不自动生成可靠6D标签或宣称自动杯子检测。见`reports/CUP_LIVE_POSE_20261014.md`。',
}
for name, text in notes.items():
    path = root / name
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    if marker not in old:
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n' + marker + '\n' + text + '\n')
if os.name == 'posix':
    folder = root / 'foundationpose_data/camera_setup'
    folder.mkdir(parents=True, exist_ok=True)
    current = folder / 'requirements.lock.txt'
    backup = folder / 'requirements.before_live_20261014.lock.txt'
    if current.exists() and not backup.exists():
        shutil.copy2(current, backup)
    result = subprocess.run([str(root / '.camera-venv/bin/python'), '-m', 'pip', 'freeze'],
                            check=True, text=True, stdout=subprocess.PIPE)
    (folder / 'requirements_live_20261014.lock.txt').write_text(result.stdout, encoding='utf-8')
    current.write_text(result.stdout, encoding='utf-8')
print(json.dumps(dict(passed=True, guides_appended=list(notes),
                      proof_sha256=hashlib.sha256(args.verification.read_bytes()).hexdigest(),
                      ubuntu_camera_lock_updated=os.name == 'posix', server_history_replaced=False)))
