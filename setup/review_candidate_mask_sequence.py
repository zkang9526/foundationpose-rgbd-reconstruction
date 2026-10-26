#!/usr/bin/env python3
"""Read-only mask/depth statistics and crop contact sheets; manual QA required."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import cv2
import numpy as np
from PIL import Image, ImageDraw

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--scene', type=Path, required=True)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--crop', type=int, nargs=4, required=True)
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
generation = json.loads((args.candidate / 'report.json').read_text())
if not generation.get('passed') or generation.get('status') != 'complete':
    raise ValueError('Candidate generation is incomplete')
entries, rows = [], []
for item in generation['frames']:
    filename = item['frame']
    mask_path = args.candidate / 'masks' / filename
    if hashlib.sha256(mask_path.read_bytes()).hexdigest() != item['mask_sha256']:
        raise ValueError('Candidate mask changed')
    mask = np.asarray(Image.open(mask_path)) > 0
    depth = np.asarray(Image.open(args.scene / 'depth' / filename))
    values = depth[mask]
    ratios = dict(nonzero_raw_depth_ratio=float(np.count_nonzero(values) / values.size),
                  raw_depth_300_800_ratio=float(np.count_nonzero((values >= 300) & (values <= 800)) / values.size))
    rows.append(dict(frame=filename, mask_pixels=int(mask.sum()), mask_sha256=item['mask_sha256'], **ratios,
                     median_positive_depth_mm=float(np.median(values[values > 0])) if np.any(values) else None,
                     generation_flags=item['flags']))
    picture = Image.open(args.candidate / 'overlays' / filename).convert('RGB').crop(args.crop).resize((320, 240))
    entries.append((Path(filename).stem, picture))
for start in range(0, len(entries), 8):
    page = entries[start:start + 8]
    sheet = Image.new('RGB', (1280, ((len(page) + 3) // 4) * 264), (25, 25, 25))
    draw = ImageDraw.Draw(sheet)
    for i, (label, picture) in enumerate(page):
        x, y = i % 4 * 320, i // 4 * 264
        draw.text((x + 8, y + 5), label, fill='white')
        sheet.paste(picture, (x, y + 24))
    sheet.save(args.output / ('overlays_%02d.png' % (start // 8)))
report = dict(scope='Candidate mask RGB overlays and unfiltered depth consistency; not automatic acceptance or metric accuracy',
              scene=str(args.scene), candidate=str(args.candidate), frames=rows, masks_accepted=False,
              mean_mask_nonzero_raw_depth_ratio=statistics.mean(r['nonzero_raw_depth_ratio'] for r in rows),
              min_mask_nonzero_raw_depth_ratio=min(r['nonzero_raw_depth_ratio'] for r in rows),
              mean_mask_raw_300_800_ratio=statistics.mean(r['raw_depth_300_800_ratio'] for r in rows),
              generation_report_sha256=hashlib.sha256((args.candidate / 'report.json').read_bytes()).hexdigest())
(args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ('mean_mask_nonzero_raw_depth_ratio', 'min_mask_nonzero_raw_depth_ratio', 'mean_mask_raw_300_800_ratio')}))
