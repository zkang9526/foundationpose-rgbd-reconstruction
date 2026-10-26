#!/usr/bin/env python3
"""Verify a new static-capture ZIP and add it to Ubuntu without journal overwrite."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import zipfile


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def safe(root, name):
    if '\\' in name or ':' in name or name.startswith('/') or '..' in PurePosixPath(name).parts:
        raise ValueError('Unsafe portable path')
    path = root / name
    cursor = root
    for part in PurePosixPath(name).parts:
        cursor /= part
        if cursor.is_symlink() or cursor.resolve(strict=False) != cursor:
            raise ValueError('Linked destination rejected')
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/data/ZJC/foundationPos'))
    p.add_argument('--zip', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--batch-id', required=True)
    args = p.parse_args()
    root = args.root.resolve(strict=True)
    if args.batch_id != Path(args.batch_id).name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.batch_id):
        raise ValueError('Invalid batch id')
    if sha(args.zip) != args.sha256:
        raise ValueError('Uploaded ZIP SHA256 differs')
    stage = safe(root, 'foundationpose_data/incoming/' + args.batch_id + '/verified_payload')
    stage.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, zip_sha256=args.sha256, files=[], server_journals_replaced=False,
                  run_ids_appended_by_existing_importer=True)
    report_path = stage.parent / 'static_capture_import_report.json'
    try:
        with zipfile.ZipFile(args.zip) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            expected = {item['path']: item for item in manifest['files']}
            if len(expected) != len(manifest['files']) or set(archive.namelist()) != set(expected) | {'manifest.json'}:
                raise ValueError('Archive member list differs')
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError('Duplicate ZIP member')
            plans = []
            for name, item in sorted(expected.items()):
                if not (name.startswith(('foundationpose_data/windows_captures/', 'foundationpose_data/derived/',
                                         'foundationpose_data/runs/', 'reports/', 'setup/'))):
                    raise ValueError('Unexpected destination scope: ' + name)
                if item['bytes'] > 256 * 1024 * 1024 or not stat.S_ISREG(archive.getinfo(name).external_attr >> 16):
                    raise ValueError('Unexpected type or file size')
                path = safe(stage, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                h, size = hashlib.sha256(), 0
                with archive.open(name) as source, path.open('xb') as target:
                    for data in iter(lambda: source.read(1024 * 1024), b''):
                        size += len(data)
                        h.update(data)
                        target.write(data)
                if size != item['bytes'] or h.hexdigest() != item['sha256']:
                    raise ValueError('Staged SHA256 differs')
                destination = safe(root, name)
                existing = sha(destination) if destination.is_file() else None
                if destination.exists() and not destination.is_file():
                    raise ValueError('Destination is not a regular file')
                if existing is not None and existing != item['sha256'] and not name.startswith('setup/'):
                    raise ValueError('Existing data/evidence differs; preserved: ' + name)
                plans.append((name, item, path, destination, existing))
        for name, item, source, destination, existing in plans:
            action = 'identical_skip'
            if existing != item['sha256']:
                if existing is not None:
                    backup = safe(root, 'foundationpose_data/import_backups/' + args.batch_id + '/' + name)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    if backup.exists():
                        raise ValueError('Backup already exists')
                    shutil.copy2(destination, backup)
                    if sha(backup) != existing:
                        raise ValueError('Backup hash differs')
                destination.parent.mkdir(parents=True, exist_ok=True)
                if existing is None:
                    # Hard link provides atomic no-overwrite publication on /data.
                    os.link(source, destination)
                else:
                    temporary = destination.with_name('.' + destination.name + '.' + args.batch_id + '.tmp')
                    with source.open('rb') as f, temporary.open('xb') as target:
                        shutil.copyfileobj(f, target, 1024 * 1024)
                    os.replace(temporary, destination)
                action = 'new_file' if existing is None else 'setup_updated_with_backup'
            if sha(destination) != item['sha256']:
                raise ValueError('Imported SHA256 differs')
            report['files'].append(dict(path=name, sha256=item['sha256'], action=action))
        subprocess.run([sys.executable, str(root / 'setup/import_windows_run_records.py')], cwd=root, check=True)
        report.update(passed=True, imported_files=len(plans), batch_id=args.batch_id,
                      source_manifest=manifest, all_file_hashes_verified=True)
    finally:
        report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, files=len(plans), report=str(report_path))), flush=True)


if __name__ == '__main__':
    main()
