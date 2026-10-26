#!/usr/bin/env python3
"""Primary Google Drive retry: exact file ID discovered from official folder."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from deploy_bundlesdf_isolated_20261013 import ROOT, CODE, AUDIT, logged

stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
attempt = AUDIT / ('loftr_google_curl_' + stamp)
attempt.mkdir(parents=True, exist_ok=False)
target = CODE / 'BundleTrack/LoFTR/weights/outdoor_ds.ckpt'
if target.exists():
    raise FileExistsError(str(target))
file_id = '1M-VD35-qdB5Iw-AtbDBCKC7hPolFW9UY'
urls = ['https://drive.usercontent.google.com/download?id='+file_id+'&export=download&confirm=t',
        'https://drive.google.com/uc?export=download&id='+file_id+'&confirm=t',
        'http://cmp.felk.cvut.cz/~mishkdmy/models/loftr_outdoor.ckpt']
manifest = {'official_folder': 'https://drive.google.com/drive/folders/1xu2Pq6mZT5hmFgiYMBT9Zt8h1yO-3SIp',
            'exact_file_id': file_id, 'attempts': [], 'passed': False}
for index, url in enumerate(urls):
    temporary = attempt / ('attempt_' + str(index) + '.ckpt.part')
    item = {'url': url, 'file': str(temporary)}
    try:
        logged('bundlesdf_loftr_primary_retry_'+str(index), ['curl', '--fail', '--location', '--silent', '--show-error',
               '--connect-timeout', '10', '--max-time', '80', '--output', str(temporary), url])
        item['exit_code'] = 0
    except subprocess.CalledProcessError as error:
        item['exit_code'] = error.returncode
    if temporary.exists():
        item['size'] = temporary.stat().st_size
        item['sha256'] = hashlib.sha256(temporary.read_bytes()).hexdigest()
    manifest['attempts'].append(item)
    if item['exit_code'] == 0 and item.get('size', 0) > 10000000:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temporary, target)
        manifest['installed'] = dict(item, target=str(target), strict_cpu_load_pending=True)
        manifest['passed'] = True
        break
(attempt/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
raise SystemExit(0 if manifest['passed'] else 1)
