#!/usr/bin/env bash
# Download ordinary dependencies while the PyTorch wheel is transferred.
set -euo pipefail
LOG=/home/ni/foundationpose_data/conda_setup
source /home/ni/anaconda3/etc/profile.d/conda.sh
conda activate /home/ni/anaconda3/envs/foundationpose
export PIP_CONFIG_FILE=/dev/null
export PIP_FIND_LINKS="$LOG/cached_wheels"
cat > "$LOG/constraints.txt" <<'EOF'
torch==2.4.1
torchvision==0.19.1
torchaudio==2.4.1
warp-lang==1.6.2
kornia==0.7.3
numpy==2.1.3
pybind11==2.13.6
setuptools<81
opencv-python==4.11.0.86
EOF
python - <<'PY'
import json
from pathlib import Path
from urllib.request import urlopen
rows = []
for name, version in [('open3d', '0.19.0'), ('warp-lang', '1.6.2')]:
    with urlopen('https://pypi.org/pypi/{}/{}/json'.format(name, version), timeout=30) as response:
        metadata = json.load(response)
    for info in metadata['urls']:
        filename = info['filename']
        if 'x86_64' in filename and ('cp311-' in filename or 'py3-' in filename) and 'linux' in filename:
            rows.append({'name': name, 'filename': filename, 'url': info['url'],
                         'sha256': info['digests']['sha256'], 'size': info['size']})
Path('/home/ni/foundationpose_data/conda_setup/large_wheels.json').write_text(json.dumps(rows, indent=2))
print(json.dumps(rows, indent=2), flush=True)
PY
python - <<'PY'
import re
from pathlib import Path
root = Path('/home/ni/foundationpose_data/conda_setup')
direct = {}
for package, version in [('numpy', '2.1.3'), ('scipy', '1.17.1'), ('pillow', '12.3.0'),
                         ('opencv_python', '4.11.0.86'), ('open3d', '0.19.0'),
                         ('warp_lang', '1.6.2')]:
    files = list((root / 'cached_wheels').glob('{}-{}-*.whl'.format(package, version)))
    if files:
        path = max(files, key=lambda p: p.name.count('.'))
        direct[package.replace('_', '-')] = '{} @ {}'.format(package, path.as_uri())
with (root / 'core_requirements.txt').open('w') as target:
    for line in Path('/home/ni/FoundationPose-conda/requirements.txt').read_text().splitlines():
        match = re.match(r'^([a-zA-Z0-9_-]+)', line)
        name = match.group(1).lower().replace('_', '-') if match else None
        if name == 'kornia':
            continue
        target.write(direct.get(name, line) + '\n')
PY
python -m pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --timeout 60 --retries 5 -c "$LOG/constraints.txt" -r "$LOG/core_requirements.txt" fvcore iopath > "$LOG/04_core_requirements.log" 2>&1
