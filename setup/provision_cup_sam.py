"""Install pinned official SAM source and checkpoint without changing Python packages."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

root = Path('/data/ZJC/foundationPos/foundationpose_data')
source = root / 'tools/segment-anything'
checkpoint = root / 'checkpoints/sam/sam_vit_b_01ec64.pth'
url = 'https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth'
source.parent.mkdir(parents=True, exist_ok=True)
checkpoint.parent.mkdir(parents=True, exist_ok=True)
if not source.exists():
    subprocess.run(['git', 'clone', 'https://github.com/facebookresearch/segment-anything.git', str(source)], check=True)
commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
subprocess.run(['git', '-C', str(source), 'checkout', '--detach', commit], check=True)
if not checkpoint.exists():
    partial = checkpoint.with_suffix('.download')
    with urllib.request.urlopen(url, timeout=60) as response, partial.open('xb') as dest:
        expected = int(response.headers['Content-Length'])
        count = 0
        while True:
            block = response.read(4 * 1024 * 1024)
            if not block:
                break
            dest.write(block)
            count += len(block)
        if count != expected or count < 300_000_000:
            raise RuntimeError('Checkpoint download length mismatch')
    partial.rename(checkpoint)
digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
manifest = checkpoint.parent / 'installation.json'
info = dict(source_url='https://github.com/facebookresearch/segment-anything', commit=commit,
            checkpoint_url=url, checkpoint_sha256=digest, checkpoint_bytes=checkpoint.stat().st_size,
            model_type='vit_b', dependency_packages_modified=False)
if manifest.exists() and json.loads(manifest.read_text()) != info:
    raise RuntimeError('Existing SAM installation manifest differs')
manifest.write_text(json.dumps(info, indent=2) + '\n')
code = "import sys;sys.path.insert(0,'/data/tools/segment-anything');from segment_anything import SamPredictor,sam_model_registry;import torch;print(torch.__version__,torch.cuda.is_available())"
subprocess.run(['docker', 'exec', 'foundationpose', '/opt/conda/envs/my/bin/python', '-c', code], check=True)
print(json.dumps(info, indent=2))
