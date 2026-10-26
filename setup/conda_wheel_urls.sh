#!/usr/bin/env bash
# Record exact official wheel URLs and hashes for a fast transfer machine.
set -euo pipefail
/home/ni/anaconda3/envs/foundationpose/bin/python - <<'PY'
import json
from pathlib import Path
from urllib.request import urlopen
packages = [('pandas', '3.0.6'), ('dash', '4.4.1'), ('fonttools', '4.66.1'),
            ('PyOpenGL-accelerate', '3.1.10'), ('pydantic-core', '2.50.0'),
            ('rpds-py', '2026.9.1')]
rows = []
for name, version in packages:
    with urlopen('https://pypi.org/pypi/{}/{}/json'.format(name, version), timeout=30) as response:
        metadata = json.load(response)
    candidates = [x for x in metadata['urls'] if x['filename'].endswith('.whl') and (
        ('cp311-' in x['filename'] and 'x86_64' in x['filename'] and 'linux' in x['filename'])
        or 'py3-none-any.whl' in x['filename'])]
    if not candidates:
        raise RuntimeError('No compatible wheel for ' + name)
    info = candidates[0]
    rows.append({'name': name, 'version': version, 'filename': info['filename'], 'url': info['url'],
                 'sha256': info['digests']['sha256'], 'size': info['size']})
output = Path('/home/ni/foundationpose_data/conda_setup/remaining_wheels.json')
output.write_text(json.dumps(rows, indent=2))
print(json.dumps(rows, indent=2))
PY
