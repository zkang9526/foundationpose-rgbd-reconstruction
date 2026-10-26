"""Read-only SAM/dependency and current-session inventory; no secrets."""
import json
import subprocess
from pathlib import Path

root = Path('/data/ZJC/foundationPos')
for exe in ['/home/ni/anaconda3/envs/foundationpose/bin/python', str(root / '.camera-venv/bin/python')]:
    code = "import importlib.util,json;print(json.dumps({x:bool(importlib.util.find_spec(x)) for x in ['torch','torchvision','segment_anything']}))"
    result = subprocess.run([exe, '-c', code], capture_output=True, text=True)
    print(exe, result.returncode, result.stdout, result.stderr)
print(subprocess.run(['docker', 'exec', 'foundationpose', '/opt/conda/envs/my/bin/python', '-c',
    "import torch,torchvision,importlib.util;print(torch.__version__,torchvision.__version__,torch.cuda.is_available(),bool(importlib.util.find_spec('segment_anything')))"], capture_output=True, text=True).stdout)
for base in [root / 'foundationpose_data', root / 'weights', root / 'checkpoints']:
    if base.exists():
        for pattern in ['*sam*.pth', '*sam*.pt']:
            print('weights', [str(p) for p in base.rglob(pattern)])
sessions = root / 'foundationpose_data/live_sessions'
for p in sorted(sessions.glob('cup*'), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
    print('session', p.name)
    for name in ['session_report.json', 'worker_report.json']:
        if (p / name).exists():
            print(name, (p / name).read_text()[:2400])
print(subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,memory.total','--format=csv'],capture_output=True,text=True).stdout)
