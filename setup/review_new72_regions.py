#!/usr/bin/env python3
"""Scene-specific manually inspected sample regions for the new higher view."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scene', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
selection = dict(selection_method='Manual review of all 72 RGB crops; scene-specific cup body, black-band and upward-facing bottom samples. Rectangles are not full masks or measured geometry.', frames={})
for index in range(72):
    body, band = [419, 87, 481, 118], [417, 146, 478, 158]
    if 14 <= index <= 23:
        body, band = [469, 89, 487, 119], [468, 149, 482, 157]
    elif 24 <= index <= 29:
        body, band = [409, 91, 428, 119], [409, 147, 428, 157]
    selection['frames']['%06d' % index] = dict(observations='Inverted cup, higher observation angle; top ellipse visibly larger than the previous side sequence.',
        regions=dict(body_core=body, dark_band_core=band, visible_bottom_core=[430, 31, 470, 45]))
selection_path = args.output / 'regions_selection.json'
selection_path.write_text(json.dumps(selection, indent=2) + '\n')
result_path = args.output / 'raw_depth_samples.json'
subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('assess_cup_sequence_regions.py')),
    '--scene', str(args.scene), '--regions', str(selection_path), '--output', str(result_path)], check=True, stdout=subprocess.DEVNULL)
result = json.loads(result_path.read_text())
summary = dict(scope=result['scope'], scene=str(args.scene.resolve()), full_masks_assessed=False, regions={})
for region in ('body_core', 'dark_band_core', 'visible_bottom_core'):
    rows = [(name, row['regions'][region]) for name, row in result['frames'].items()]
    values = [row['nonzero_depth_ratio'] for _, row in rows]
    summary['regions'][region] = dict(count=len(rows), min=min(values), mean=statistics.mean(values), max=max(values),
        below_50_percent_frames=[name for name, row in rows if row['nonzero_depth_ratio'] < .5])
(args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary), flush=True)
