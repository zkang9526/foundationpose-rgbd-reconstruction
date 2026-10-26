#!/usr/bin/env python3
"""Prepare a fresh, hashed local payload of explicit updates and ended runs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-manifest', type=Path, action='append', default=[])
    parser.add_argument('--include-ended-runs', action='store_true')
    parser.add_argument('--ended-runs-since', help='Include only run IDs at or after YYYYMMDD_HHMMSS; avoids long Windows argv lists')
    parser.add_argument('--include-new-reports', action='store_true')
    parser.add_argument('--files', nargs='*', default=[])
    args = parser.parse_args()
    if args.ended_runs_since and not re.fullmatch(r'[0-9]{8}_[0-9]{6}', args.ended_runs_since):
        parser.error('--ended-runs-since must have format YYYYMMDD_HHMMSS')
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    if root / 'foundationpose_data/exports' not in output.parents or output.exists():
        parser.error('Output must be a new directory inside project exports')
    selected = set(args.files)
    known = set()
    known_files = set()
    for manifest_path in args.previous_manifest:
        previous = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        for item in previous['files']:
            name = item['path']
            known_files.add(name)
            if name.startswith('foundationpose_data/runs/'):
                known.add(name.split('/')[2])
    if args.include_new_reports:
        selected.update(path.relative_to(root).as_posix()
                        for path in (root / 'reports').rglob('*')
                        if path.is_file() and path.relative_to(root).as_posix() not in known_files)
    if args.include_ended_runs:
        for run_file in sorted((root / 'foundationpose_data/runs').glob('*/run.json')):
            if args.ended_runs_since and run_file.parent.name < args.ended_runs_since:
                continue
            run = json.loads(run_file.read_text(encoding='utf-8-sig'))
            if (run_file.parent.name in known or not run.get('end')
                    or run.get('exit_code') is None
                    or run.get('status') not in ('passed', 'failed', 'interrupted')
                    or not run.get('metadata', {}).get('platform', '').startswith('Windows')):
                continue
            selected.update(path.relative_to(root).as_posix()
                            for path in run_file.parent.rglob('*') if path.is_file())
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for name in sorted(selected):
        source = root / name
        if (source.resolve(strict=True) != source.absolute() or root not in source.parents
                or '..' in Path(name).parts or Path(name).is_absolute()):
            raise ValueError('Unsafe source path: ' + name)
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = output / 'payload' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as handle:
            handle.write(data)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Staging checksum mismatch: ' + name)
        if source.read_bytes() != data:
            raise ValueError('Source changed while staging: ' + name)
        records.append({'path': name, 'sha256': digest, 'bytes': len(data)})
    manifest = {'schema_version': 1, 'files': records}
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    shutil.copyfile(root / 'setup/deploy_cup_stage_updates.py', output / 'deploy_cup_stage_updates.py')
    print(json.dumps({'passed': True, 'files': len(records), 'output': str(output)}))


if __name__ == '__main__':
    main()
