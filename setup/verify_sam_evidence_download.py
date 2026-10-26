"""Verify a downloaded evidence bundle against its Ubuntu SHA manifest."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--input', required=True, type=Path)
args = p.parse_args()
manifest = json.loads((args.input / 'manifest.json').read_text())
for item in manifest['files']:
    path = args.input / item['path']
    data = path.read_bytes()
    assert len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
print(json.dumps(dict(passed=True, sha256_verified_files=len(manifest['files']))))
