"""Isolated SAM2.1 environment; never upgrade FoundationPose or camera Python."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

root = Path('/data/ZJC/foundationPos')
data = root / 'foundationpose_data'
source = data / 'tools/sam2'
env = data / 'environments/sam2'
expected_commit = '2b90b9f5ceec907a1c18123530e92e794ad901a4'
source.parent.mkdir(parents=True, exist_ok=True)
env.parent.mkdir(parents=True, exist_ok=True)
if not source.exists():
    subprocess.run(['git', 'clone', '--depth', '1', '--filter=blob:none', '--no-checkout', 'https://github.com/facebookresearch/sam2.git', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'sparse-checkout', 'init', '--cone'], check=True)
    subprocess.run(['git', '-C', str(source), 'sparse-checkout', 'set', 'sam2'], check=True)
commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
if commit != expected_commit:
    subprocess.run(['git', '-C', str(source), 'fetch', '--depth', '1', 'origin', expected_commit], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', expected_commit], check=True)
    commit = expected_commit
subprocess.run(['git', '-C', str(source), 'checkout', '--detach', commit], check=True)
assets_only = '--assets-only' in sys.argv
if not assets_only and not (env / 'bin/python').exists():
    subprocess.run(['/home/ni/anaconda3/envs/foundationpose/bin/python', '-m', 'venv', '--system-site-packages', str(env)], check=True)
child = os.environ.copy()
child.update(PIP_CACHE_DIR=str(data / 'cache/pip_sam2'), SAM2_BUILD_CUDA='0')
cached_wheel = data / 'cache/sam2_wheels/torch-2.5.1+cu121-cp311-cp311-linux_x86_64.whl'
torch_requirement = str(cached_wheel) if cached_wheel.exists() else 'torch==2.5.1+cu121'
if cached_wheel.exists() and hashlib.sha256(cached_wheel.read_bytes()).hexdigest() != 'c8ab8c92eab928a93c483f83ca8c63f13dafc10fc93ad90ed2dcb7c82ea50410':
    raise RuntimeError('Cached Torch wheel differs from official index SHA')
if not assets_only:
    subprocess.run([str(env / 'bin/python'), '-m', 'pip', 'install', '--index-url', 'https://download.pytorch.org/whl/cu121',
                    torch_requirement, 'torchvision==0.20.1+cu121', 'torchaudio==2.5.1+cu121'], env=child, check=True)
    subprocess.run([str(env / 'bin/python'), '-m', 'pip', 'install', 'hydra-core==1.3.2', 'iopath==0.1.10', 'tqdm>=4.66.1'], env=child, check=True)
# Source imported explicitly; image prediction needs no optional CUDA component.
checkpoint = data / 'checkpoints/sam2/sam2.1_hiera_tiny.pt'
checkpoint.parent.mkdir(parents=True, exist_ok=True)
url = 'https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt'
if not checkpoint.exists():
    partial = checkpoint.with_suffix('.download')
    with urllib.request.urlopen(url, timeout=60) as response, partial.open('xb') as stream:
        expected = int(response.headers['Content-Length'])
        count = 0
        while True:
            block = response.read(4 * 1024 ** 2)
            if not block:
                break
            stream.write(block)
            count += len(block)
        if count != expected:
            raise ValueError('Checkpoint length mismatch')
    partial.rename(checkpoint)
if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != '7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69':
    raise RuntimeError('SAM2 checkpoint differs from validated baseline SHA')
info = dict(source_url='https://github.com/facebookresearch/sam2', commit=commit, checkpoint_url=url,
            checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(), checkpoint_bytes=checkpoint.stat().st_size,
            model_type='sam2.1_hiera_tiny', config='configs/sam2.1/sam2.1_hiera_t.yaml',
            environment=str(env), inherited_base='/home/ni/anaconda3/envs/foundationpose',
            original_environments_modified=False, optional_cuda_extension=False)
if assets_only:
    (checkpoint.parent / 'asset_download.json').write_text(json.dumps(info, indent=2) + '\n')
    print('SAM2 official checkpoint downloaded:', info['checkpoint_sha256'])
    sys.exit(0)
code = "import torch,sys;sys.path.insert(0," + repr(str(source)) + ");from sam2.build_sam import build_sam2;print(torch.__version__,torch.cuda.is_available())"
sys.path.insert(0, str(root / 'setup'))
from sam2_runtime_environment import sam2_runtime_environment
runtime, libraries = sam2_runtime_environment(root)
subprocess.run([str(env / 'bin/python'), '-c', code], check=True, env=runtime)
info.update(runtime_validated=True, runtime_library_directories=libraries)
(checkpoint.parent / 'installation.json').write_text(json.dumps(info, indent=2) + '\n')
print(json.dumps(info))
