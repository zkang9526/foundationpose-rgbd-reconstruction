#!/usr/bin/env python3
"""Stage the small new-mesh pose session notes, preview and ended Windows records."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def fingerprint(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected regular source file: ' + str(path))
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--review', type=Path, required=True)
    p.add_argument('--first-run', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root, output = args.root.resolve(strict=True), args.output.resolve()
    if output.exists():
        p.error('Stage output must be new')
    fixed = ['REPRODUCTION_GUIDE.md', 'POSE_AND_TRAINING_GUIDE.md',
             'setup/summarize_cup_pose_pilot.py', 'setup/stage_cup_pose_session.py',
             'reports/CUP_NEW72_FOUNDATIONPOSE_PILOT_20261014.md',
             'reports/CUP_NEW72_FOUNDATIONPOSE_ISSUES_20261014.md']
    sources = [(root / name, name) for name in fixed]
    runs = []
    for folder in sorted((root / 'foundationpose_data/runs').iterdir()):
        if not folder.is_dir() or folder.name < args.first_run:
            continue
        path = folder / 'run.json'
        if not path.is_file():
            continue
        run = json.loads(path.read_text(encoding='utf-8-sig'))
        if not run.get('end') or type(run.get('exit_code')) is not int:
            continue
        if not run.get('metadata', {}).get('platform', '').startswith('Windows'):
            continue
        runs.append(folder.name)
        sources.extend((file, file.relative_to(root).as_posix()) for file in folder.rglob('*') if file.is_file())
    review = args.review.resolve(strict=True)
    for name in fixed[-2:]:
        target = review / Path(name).name
        if target.exists():
            if fingerprint(target) != fingerprint(root / name):
                raise ValueError('Existing E-drive note differs; preserve it')
        else:
            shutil.copy2(root / name, target)
    sources.extend((file, 'reports/cup_fp_new72_heldout5_review_20261014/' + file.relative_to(review).as_posix())
                   for file in sorted(review.rglob('*')) if file.is_file())
    payload = output / 'payload'
    payload.mkdir(parents=True, exist_ok=False)
    files = []
    for source, name in sources:
        original = fingerprint(source)
        target = payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        if fingerprint(target) != original or fingerprint(source) != original:
            raise ValueError('Source changed while staging: ' + name)
        files.append(dict(path=name, bytes=original[0], sha256=original[1]))
    manifest = dict(schema_version=1, files=files)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    report = dict(passed=True, files=len(files), bytes=sum(row['bytes'] for row in files),
                  ended_windows_run_count=len(runs), ended_windows_run_ids=runs,
                  server_journals_included=False, source_raw_images_modified=False,
                  output=str(output))
    (output / 'stage_report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
