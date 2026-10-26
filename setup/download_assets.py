#!/usr/bin/env python3
"""Download only the two official inference models and mustard demo."""
import hashlib
import json
from pathlib import Path
import zipfile

import gdown

repo = Path.home() / 'FoundationPose'
data = Path.home() / 'foundationpose_data'
files = [
    ('1477-st1s1TxXN6oqfM5ZnsQwd8BCzVg1', repo / 'weights/2023-10-28-18-33-37/config.yml'),
    ('1E9FPB5WFIBMLrOJqZLpoVOK4Mjzrrxhv', repo / 'weights/2023-10-28-18-33-37/model_best.pth'),
    ('1kQkQG-q_VvLRozv30hyeLB7P_jiEEqiE', repo / 'weights/2024-01-11-20-02-45/config.yml'),
    ('1Zdjnkn4EHOI5_k08apofwRgTjWpai4E4', repo / 'weights/2024-01-11-20-02-45/model_best.pth'),
    ('1AwV9sESDKMgXGUu2n1o0Pc4x2JGYdVB3', data / 'downloads/mustard0.zip'),
]
manifest = []
for file_id, path in files:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        print('Downloading ' + str(path), flush=True)
        temporary = path.with_name(path.name + '.download')
        result = gdown.download(id=file_id, output=str(temporary), quiet=True)
        if result is None:
            raise RuntimeError('Official download failed: ' + file_id)
        temporary.replace(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    record = dict(id=file_id, path=str(path), size_bytes=path.stat().st_size, sha256=digest.hexdigest())
    manifest.append(record)
    print('Ready: {} ({} bytes)'.format(path.name, record['size_bytes']), flush=True)

destination = repo / 'demo_data'
destination.mkdir(exist_ok=True)
with zipfile.ZipFile(files[-1][1]) as archive:
    for member in archive.infolist():
        resolved = (destination / member.filename).resolve()
        if destination.resolve() not in resolved.parents and resolved != destination.resolve():
            raise ValueError('Archive path escapes demo_data: ' + member.filename)
    archive.extractall(destination)
(data / 'official_assets_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Official weights and mustard demo prepared.', flush=True)
