"""Generate/check a per-file SHA256 manifest for cross-machine evidence copies."""
import argparse
import json
from pathlib import Path

from common import sha, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--create', action='store_true')
    a = p.parse_args()
    manifest = a.input / 'transfer_manifest.json'
    if a.create:
        if manifest.exists():
            raise ValueError('Manifest already exists; preserve it and use verification mode')
        files = [dict(path=p.relative_to(a.input).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
                 for p in sorted(a.input.rglob('*')) if p.is_file() and p != manifest]
        write_json(manifest, dict(files=files))
    files = json.loads(manifest.read_text(encoding='utf-8'))['files']
    failures = []
    root = a.input.resolve(strict=True)
    for item in files:
        path = (root / item['path']).resolve()
        if root not in path.parents or not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            failures.append(item['path'])
    print(json.dumps(dict(passed=not failures, files=len(files), failures=failures)))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
