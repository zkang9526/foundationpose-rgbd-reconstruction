#!/usr/bin/env python3
"""Download only outdoor_ds from the BundleSDF official public weight folder."""
import datetime
import hashlib
import json
from pathlib import Path
import signal
import shutil
import gdown

root = Path('/data')
stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
attempt = root / 'bundlesdf_setup_20261013' / ('loftr_gdrive_' + stamp)
attempt.mkdir(parents=True, exist_ok=False)
target = Path('/workspace/BundleSDF/BundleTrack/LoFTR/weights/outdoor_ds.ckpt')
if target.exists():
    raise FileExistsError('Prior weight preserved: ' + str(target))
manifest = {'official_folder': 'https://drive.google.com/drive/folders/1xu2Pq6mZT5hmFgiYMBT9Zt8h1yO-3SIp', 'passed': False}
try:
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('GDrive folder/download exceeded limit')))
    signal.alarm(180)
    files = gdown.download_folder(id='1xu2Pq6mZT5hmFgiYMBT9Zt8h1yO-3SIp', skip_download=True, use_cookies=False)
    manifest['folder_files'] = [item._asdict() for item in files]
    choices = [item for item in files if Path(item.path).name == 'outdoor_ds.ckpt']
    if len(choices) != 1:
        raise RuntimeError('Expected exactly one official outdoor_ds.ckpt: ' + str(choices))
    chosen = choices[0]
    temporary = attempt / 'outdoor_ds.ckpt'
    result = gdown.download(id=chosen.id, output=str(temporary), use_cookies=False)
    signal.alarm(0)
    if not result or temporary.stat().st_size < 10000000:
        raise RuntimeError('No complete checkpoint')
    manifest.update({'download_id': chosen.id, 'size': temporary.stat().st_size,
                     'sha256': hashlib.sha256(temporary.read_bytes()).hexdigest(), 'source_copy': str(temporary)})
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(temporary, target)
    manifest['installed_copy'] = str(target)
    manifest['passed'] = True
except Exception as error:
    manifest['error'] = str(error)
finally:
    signal.alarm(0)
    (attempt / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
raise SystemExit(0 if manifest['passed'] else 1)
