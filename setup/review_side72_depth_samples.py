#!/usr/bin/env python3
"""Review manually inspected sample rectangles in the 2026-10-14 side72 scene.

Coordinates are scene-specific. Raw depth is read, never filtered or modified.
This is not full-object segmentation or a metric-accuracy/mesh verdict.
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = json.loads((args.scene / 'metadata.json').read_text(encoding='utf-8'))
    if len(metadata['frames']) != 72:
        raise ValueError('These manually inspected rectangles require the reviewed 72-photo scene')
    selection = dict(selection_method='Manual RGB review of all 72 crops. Body/band samples avoid the front handle where possible; bottom-center samples are small fixed rectangles, not whole surfaces. Four handle samples were checked in full-resolution RGB.', frames={})
    handle_samples = {'000000': [201, 338, 206, 348], '000017': [290, 335, 300, 350],
                      '000031': [380, 345, 384, 352], '000071': [201, 339, 206, 351]}
    for index in range(72):
        name = '%06d' % index
        core, band = [267, 315, 324, 355], [268, 387, 324, 400]
        if 9 <= index <= 18:
            core, band = [311, 315, 326, 355], [311, 387, 326, 400]
        elif 19 <= index <= 24:
            core, band = [265, 315, 281, 355], [265, 387, 281, 400]
        regions = dict(body_core=core, dark_band_core=band, visible_bottom_core=[275, 275, 313, 285])
        if name in handle_samples:
            regions['visible_handle_stem_sample'] = handle_samples[name]
        selection['frames'][name] = dict(observations='Complete inverted cup, fixed observation height; sampled visible surfaces, not all cup pixels.', regions=regions)
    selection_path = output / 'regions_selection.json'
    selection_path.write_text(json.dumps(selection, indent=2) + '\n')
    result_path = output / 'raw_depth_samples.json'
    subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('assess_cup_sequence_regions.py')),
                    '--scene', str(args.scene), '--regions', str(selection_path), '--output', str(result_path)],
                   check=True, stdout=subprocess.DEVNULL)
    result = json.loads(result_path.read_text(encoding='utf-8'))
    summary = dict(scope=result['scope'], scene=str(args.scene.resolve()), measured_frames=72,
                   full_target_masks_assessed=False, raw_depth_modified=False, regions={}, limitations=result['limitations'])
    for region in ('body_core', 'dark_band_core', 'visible_bottom_core', 'visible_handle_stem_sample'):
        rows = [(name, frame['regions'][region]) for name, frame in result['frames'].items() if region in frame['regions']]
        values = [row['nonzero_depth_ratio'] for _, row in rows]
        summary['regions'][region] = dict(sampled_frames=len(rows), min=min(values), mean=statistics.mean(values),
            median=statistics.median(values), max=max(values),
            below_90_percent_frames=[name for name, row in rows if row['nonzero_depth_ratio'] < .9],
            below_50_percent_frames=[name for name, row in rows if row['nonzero_depth_ratio'] < .5],
            zero_percent_frames=[name for name, row in rows if row['nonzero_depth_ratio'] == 0],
            median_depth_meters_range=[min(row['nonzero_depth_meters_percentiles_5_50_95'][1] for _, row in rows if row['nonzero_depth_pixels']),
                                      max(row['nonzero_depth_meters_percentiles_5_50_95'][1] for _, row in rows if row['nonzero_depth_pixels'])])
    (output / 'raw_depth_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
