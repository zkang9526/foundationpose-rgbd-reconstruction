#!/usr/bin/env python3
"""Ubuntu: verify imported raw data and manually reviewed masks; prepare one ring."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import cv2
import numpy as np

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--scene', type=Path, required=True)
p.add_argument('--masks', type=Path, required=True)
p.add_argument('--qa', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
if args.output.exists():
    raise ValueError('Use a new output directory')
qa = json.loads(args.qa.read_text())
generation = json.loads((args.masks / 'report.json').read_text())
if not qa.get('accepted_for_initial_reconstruction') or sha(args.masks / 'report.json') != qa['generation_report_sha256']:
    raise ValueError('Reviewed mask QA does not match')
metadata = json.loads((args.scene / 'metadata.json').read_text())
if metadata['saved_frames'] != 72 or not metadata['passed'] or not metadata['pipeline_stopped']:
    raise ValueError('Expected stopped, complete 72-frame input')
args.output.mkdir(parents=True, exist_ok=False)
dest = args.output / args.scene.name
for name in ('rgb', 'depth', 'masks'):
    (dest / name).mkdir(parents=True)
record = dict(role='higher_view_reference', source_scene=str(args.scene), source_masks=str(args.masks),
              output_scene=str(dest), frames=[])
for index, gf in enumerate(generation['frames']):
    name = '%06d.png' % index
    if gf['frame'] != name:
        raise ValueError('Unordered mask list')
    rgbpath, depthpath, maskpath = args.scene / 'rgb' / name, args.scene / 'depth' / name, args.masks / 'masks' / name
    for path, key in ((rgbpath, 'source_rgb_sha256'), (depthpath, 'source_depth_sha256'), (maskpath, 'mask_sha256')):
        if sha(path) != gf[key]:
            raise ValueError('Imported input changed: ' + str(path))
    depth, mask = cv2.imread(str(depthpath), -1), cv2.imread(str(maskpath), 0)
    keep = (mask > 0) & (depth >= 300) & (depth <= 800)
    filtered = np.where(keep, depth, 0).astype(np.uint16)
    if not np.any(keep):
        raise ValueError('No usable target depth')
    shutil.copy2(rgbpath, dest / 'rgb' / name)
    shutil.copy2(maskpath, dest / 'masks' / name)
    if not cv2.imwrite(str(dest / 'depth' / name), filtered):
        raise ValueError('Depth PNG write failed')
    record['frames'].append(dict(frame=name, rgb_sha256=sha(rgbpath), mask_sha256=sha(maskpath),
        raw_depth_sha256=sha(depthpath), filtered_depth_sha256=sha(dest / 'depth' / name),
        retained_target_percent=float(keep.sum() * 100 / np.count_nonzero(mask))))
for name in ('K.txt', 'cam_K.txt', 'depth_scale.txt', 'timestamps.csv', 'timestamps.json'):
    shutil.copy2(args.scene / name, dest / name)
shutil.copy2(args.scene / 'metadata.json', dest / 'source_capture_metadata.json')
report = dict(passed=True, status='complete', sequences=[record], depth_range_mm_inclusive=[300, 800],
              raw_sources_modified=False, interpolated_depth=False, planned_angles_used_as_poses=False,
              mask_qa_sha256=sha(args.qa), geometry_validated=False)
(args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(passed=True, frames=72, video_dir=str(dest))), flush=True)
