"""Small immutable hashed recovery evidence bundle; full source sessions stay put."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from sam2_runtime_environment import sam2_runtime_environment

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
root = args.root.resolve(strict=True)
output = args.output.resolve()
output.relative_to(root / 'foundationpose_data')
output.mkdir(parents=True, exist_ok=False)
data = root / 'foundationpose_data'
sources = [data / 'derived' / name for name in [
    'reacquisition_shift_test_20261015_v1', 'reacquisition_real_return_20261015_v1',
    'sam2_first_frame_verification_20261015_v1', 'cup_sam_sam2_comparison_20261015_v1',
    'reacquisition_tracking_regression_20261015_v1', 'reacquisition_final_real_return_20261015_v2']]
selected = []
for source in sources:
    if not source.exists():
        continue
    selected += [source / 'report.json']
    selected += list(source.glob('*.jpg')) + list(source.glob('recovered*.png'))
    session = source / 'session'
    if not session.exists():
        continue
    selected += [session / n for n in ['session.json', 'worker_report.json', 'K.txt', 'frame_events.jsonl',
        'recovery_events.jsonl', 'initialization_checks.jsonl', 'target_reference.json', 'controls.jsonl', 'evaluation_summary/report.json']]
    selected += list((session / 'worker_code').glob('*.py'))
    selected += list((session / 'mask_attempts').glob('*/target_selection.json'))
    selected += list((session / 'mask_attempts').glob('*/result.json'))
    selected += list((session / 'mask_attempts').glob('*/request.json'))
    for frame in (session / 'frames').iterdir():
        if (frame / 'registration_candidates.json').exists():
            selected += list(frame.glob('*.json')) + list(frame.glob('*.txt')) + [frame / 'mask.png', frame / 'overlay.jpg']
selected += [data / 'checkpoints/sam2/installation.json', data / 'reacquisition_inspection_20261015.json']
runtime, _ = sam2_runtime_environment(root)
versions = {}
for name, command, env in [
    ('native_foundationpose', ['/home/ni/anaconda3/envs/foundationpose/bin/python', '-c', 'import torch,torchvision;print(torch.__version__,torchvision.__version__)'], None),
    ('sam2', [str(data / 'environments/sam2/bin/python'), '-c', 'import torch,torchvision;print(torch.__version__,torchvision.__version__,torch.cuda.is_available())'], runtime),
    ('docker_foundationpose', ['docker','exec','foundationpose','/opt/conda/envs/my/bin/python','-c','import torch,torchvision;print(torch.__version__,torchvision.__version__)'], None)]:
    versions[name] = subprocess.check_output(command, text=True, env=env).strip()
versions_path = data / 'derived/reacquisition_runtime_versions_20261015.json'
if not versions_path.exists():
    versions_path.write_text(json.dumps(versions, indent=2) + '\n')
selected.append(versions_path)
files = []
for path in sorted(set(selected)):
    if not path.is_file():
        continue
    relative = path.relative_to(data)
    dest = output / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    content = dest.read_bytes()
    assert content == path.read_bytes()
    files.append(dict(path=relative.as_posix(), bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
packages = subprocess.check_output([str(data / 'environments/sam2/bin/python'), '-m', 'pip', 'freeze'], text=True)
path = output / 'sam2_requirements_observed.txt'
path.write_text(packages)
content = path.read_bytes()
files.append(dict(path=path.name, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
(output / 'manifest.json').write_text(json.dumps(dict(files=files), indent=2) + '\n')
print(json.dumps(dict(passed=True, files=len(files), output=str(output))))
