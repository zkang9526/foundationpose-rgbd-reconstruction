#!/usr/bin/env python3
"""Snapshot explicit external capture trees and project evidence, excluding bag.

All archive paths are portable, relative project paths. Reject symlinks and
changing sources. Stream into a new E-drive ZIP; preserve failure output.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def signature(path):
    s = path.stat()
    return s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--capture', type=Path, action='append', required=True)
    p.add_argument('--derived', type=Path, action='append', default=[])
    p.add_argument('--review', type=Path, action='append', default=[])
    p.add_argument('--file', action='append', default=[])
    p.add_argument('--runs-since', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    entries, excluded = {}, []

    def add(source, name, source_root):
        source_root = source_root.resolve(strict=True)
        source = source.absolute()
        relative = source.relative_to(source_root)
        cursor = source_root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink() or cursor.resolve(strict=True) != cursor:
                raise ValueError('Linked source rejected: ' + str(source))
        if not source.is_file():
            raise ValueError('Not a regular file: ' + str(source))
        member = PurePosixPath(name)
        if member.is_absolute() or '..' in member.parts or ':' in name or '\\' in name:
            raise ValueError('Unsafe archive path')
        if name in entries:
            raise ValueError('Duplicate archive target: ' + name)
        entries[name] = (source, signature(source))

    def tree(directory, prefix, excluded_suffixes=()):
        directory = directory.resolve(strict=True)
        for source in sorted(directory.rglob('*')):
            if source.is_symlink():
                raise ValueError('Linked source rejected')
            if source.is_file():
                if source.suffix.lower() in excluded_suffixes:
                    excluded.append(dict(source=str(source), bytes=source.stat().st_size,
                                         reason='User selected static RGB-D transfer; native bag retained on E'))
                    continue
                add(source, prefix + '/' + source.relative_to(directory).as_posix(), directory)

    for directory in args.capture:
        metadata = json.loads((directory / 'metadata.json').read_text())
        if not metadata.get('passed') or not metadata.get('pipeline_stopped') or metadata.get('status') != 'complete':
            raise ValueError('Capture is not complete and stopped')
        tree(directory, 'foundationpose_data/windows_captures/' + directory.name, ('.bag',))
    for directory in args.derived:
        tree(directory, 'foundationpose_data/derived/' + directory.name)
    for directory in args.review:
        tree(directory, 'reports/e_drive_reviews/' + directory.name)
    for name in args.file:
        add(root / name, name, root)
    included_runs = []
    for path in sorted((root / 'foundationpose_data/runs').glob('*/run.json')):
        record = json.loads(path.read_text(encoding='utf-8-sig'))
        if path.parent.name < args.runs_since or not record.get('end') or record.get('exit_code') is None:
            continue
        if record.get('status') not in ('passed', 'failed', 'interrupted'):
            continue
        if not record.get('metadata', {}).get('platform', '').startswith('Windows'):
            continue
        tree(path.parent, 'foundationpose_data/runs/' + path.parent.name)
        included_runs.append(path.parent.name)
    manifest = dict(schema_version=1, purpose='explicit_external_static_rgbd_reconstruction_batch',
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        capture_sources=[str(path.resolve()) for path in args.capture], included_run_ids=included_runs,
        excluded=excluded, files=[], windows_journals_replace_server=False, planned_angles_are_poses=False)
    archive_path = output / 'capture_batch.zip'
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for index, (name, (source, before)) in enumerate(sorted(entries.items()), 1):
            if signature(source) != before:
                raise RuntimeError('Source changed before copying')
            h, size = hashlib.sha256(), 0
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info._compresslevel = 1
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            with source.open('rb') as stream, archive.open(info, 'w', force_zip64=True) as target:
                for data in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(data)
                    size += len(data)
                    target.write(data)
            if signature(source) != before or size != before[0]:
                raise RuntimeError('Source changed while copying')
            manifest['files'].append(dict(path=name, source_path=str(source), bytes=size, sha256=h.hexdigest()))
            if index % 500 == 0:
                print('Packaged %d/%d files' % (index, len(entries)), flush=True)
        raw = (json.dumps(manifest, indent=2) + '\n').encode()
        archive.writestr('manifest.json', raw)
    (output / 'manifest.json').write_bytes(raw)
    with zipfile.ZipFile(archive_path) as archive:
        for item in manifest['files']:
            h, size = hashlib.sha256(), 0
            with archive.open(item['path']) as source:
                for data in iter(lambda: source.read(1024 * 1024), b''):
                    h.update(data)
                    size += len(data)
            if size != item['bytes'] or h.hexdigest() != item['sha256']:
                raise RuntimeError('Archive verification failed')
    report = dict(passed=True, files=len(entries), included_runs=len(included_runs), archive=str(archive_path),
        bytes=archive_path.stat().st_size, sha256=digest(archive_path), excluded_bags=excluded,
        source_png_modified=False, archive_entries_verified=True)
    (output / 'package_report.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'SHA256SUMS.txt').write_text(report['sha256'] + '  capture_batch.zip\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
