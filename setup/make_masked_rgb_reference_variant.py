#!/usr/bin/env python3
"""Create a traceable RGB-background-masked variant of a prepared reference.

Only derived RGB pixels outside accepted masks become zero. Raw RGB/depth,
intrinsics, masks and prior preparation remain unchanged.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import cv2

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--input', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
original = json.loads((args.input / 'report.json').read_text())
if not original['passed'] or len(original['sequences']) != 1:
    raise ValueError('Expected one complete reference ring')
args.output.mkdir(parents=True, exist_ok=False)
record = copy.deepcopy(original['sequences'][0])
source = args.input / Path(record['output_scene']).name
dest = args.output / source.name
for folder in ('rgb', 'depth', 'masks'):
    (dest / folder).mkdir(parents=True)
for item in record['frames']:
    name = item['frame']
    image = cv2.imread(str(source / 'rgb' / name))
    mask = cv2.imread(str(source / 'masks' / name), 0)
    for folder, key in (('rgb', 'rgb_sha256'), ('depth', 'filtered_depth_sha256'), ('masks', 'mask_sha256')):
        if sha(source / folder / name) != item[key]:
            raise ValueError('Prepared source changed')
    image[mask == 0] = 0
    if not cv2.imwrite(str(dest / 'rgb' / name), image):
        raise ValueError('RGB write failed')
    item['unmasked_rgb_sha256'] = item['rgb_sha256']
    item['rgb_sha256'] = sha(dest / 'rgb' / name)
    for folder in ('depth', 'masks'):
        shutil.copy2(source / folder / name, dest / folder / name)
for name in ('K.txt', 'cam_K.txt', 'depth_scale.txt', 'timestamps.csv', 'timestamps.json', 'source_capture_metadata.json'):
    shutil.copy2(source / name, dest / name)
record['output_scene'] = str(dest)
record['role'] = 'higher_view_reference_masked_rgb_control'
report = dict(original, sequences=[record], source_preparation_sha256=sha(args.input / 'report.json'),
              controlled_change='Set only derived RGB pixels outside reviewed target masks to zero',
              raw_sources_modified=False, depth_interpolated=False, estimated_or_planned_poses_injected=False)
(args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(passed=True, frames=len(record['frames']), video_dir=str(dest))), flush=True)
