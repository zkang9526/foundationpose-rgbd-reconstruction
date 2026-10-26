#!/usr/bin/env python3
"""Download a primary-source LoFTR outdoor checkpoint, preserve retries and hashes."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path('/data/ZJC/foundationPos')
CODE = ROOT / 'BundleSDF-cf0610e'
stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
ATTEMPT = ROOT / 'foundationpose_data/bundlesdf_setup_20261013' / ('loftr_download_' + stamp)
ATTEMPT.mkdir(parents=True, exist_ok=False)
target = CODE / 'BundleTrack/LoFTR/weights/outdoor_ds.ckpt'
if target.exists():
    raise FileExistsError('Preserve prior checkpoint: ' + str(target))

# The official LoFTR authors explicitly recommend Kornia; Kornia0.7.1's source
# specifies this outdoor dual-softmax checkpoint. Exact BundleSDF state loading
# is checked separately, and this origin is recorded rather than called GDrive.
url = 'https://cmp.felk.cvut.cz/~mishkdmy/models/loftr_outdoor.ckpt'
temporary = ATTEMPT / 'loftr_outdoor.ckpt.part'
argv = ['curl', '--fail', '--location', '--show-error', '--connect-timeout', '15',
        '--max-time', '180', '--output', str(temporary), url]
command = [sys.executable, '-u', str(ROOT / 'setup/run_logged.py'), '--root', str(ROOT),
           '--label', 'bundlesdf_loftr_primary_download', '--note',
           'Pretrained outdoor DS checkpoint URL documented in official Kornia0.7.1 source; no new training.', '--'] + argv
result = subprocess.run(command)
manifest = {'source_url': url,
            'primary_origin': 'https://kornia.readthedocs.io/en/v0.7.1/_modules/kornia/feature/loftr/loftr.html',
            'bundle_official_requested_name': 'outdoor_ds.ckpt', 'attempt_file': str(temporary),
            'exit_code': result.returncode, 'cpu_state_dict_validation_pending': True}
if temporary.is_file():
    manifest.update({'size': temporary.stat().st_size, 'sha256': hashlib.sha256(temporary.read_bytes()).hexdigest()})
if result.returncode == 0 and temporary.stat().st_size > 10000000:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(temporary, target)
    manifest['installed_copy'] = str(target)
elif result.returncode == 0:
    manifest['error'] = 'Unexpectedly small checkpoint; did not install'
    result = type('Result', (), {'returncode': 1})()
(ATTEMPT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest))
raise SystemExit(result.returncode)
