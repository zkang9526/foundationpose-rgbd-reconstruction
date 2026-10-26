"""Collect a small hashed SAM validation evidence bundle, retain raw sessions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, type=Path)
p.add_argument('--source', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
selected = [args.source / n for n in ['report.json', 'bridge.log', 'recent_real_mask_comparison.jpg', 'recent_real_rgb.png']]
session = args.source / 'session'
selected += [session / n for n in ['session.json', 'worker_report.json', 'initialization_checks.jsonl', 'controls.jsonl', 'evaluation_summary/report.json']]
selected += list((session / 'mask_attempts').rglob('*'))
selected += list((session / 'worker_code').rglob('*'))
selected += list((args.source / 'recent_real_initialization').rglob('*'))
selected += list((session / 'frames/000000').glob('*'))
selected += [session / 'frames/000059/overlay.jpg']
records = []
for path in selected:
    if not path.is_file():
        continue
    name = path.relative_to(args.source)
    dest = args.output / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    data = dest.read_bytes()
    assert data == path.read_bytes()
    records.append(dict(path=name.as_posix(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
install = args.root / 'foundationpose_data/checkpoints/sam/installation.json'
dest = args.output / 'sam_installation.json'
shutil.copy2(install, dest)
data = dest.read_bytes()
records.append(dict(path=dest.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
(args.output / 'manifest.json').write_text(json.dumps(dict(files=records), indent=2) + '\n')
print(json.dumps(dict(passed=True, files=len(records), output=str(args.output))))
