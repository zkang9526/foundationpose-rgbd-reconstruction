#!/usr/bin/env python3
"""Read-only diagnostics for reference tracking; no reconstruction edits."""
import argparse
import json
from pathlib import Path
import numpy as np

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--pipeline', type=Path, required=True)
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--run-id', required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
if args.output.exists():
    raise ValueError('Use a new report')
log_path = args.root / 'foundationpose_data/runs' / args.run_id / 'console.log'
lines = log_path.read_text(errors='replace').splitlines()
keyframe_lines = [line for line in lines if 'Added frame' in line or 'keyframes#:' in line or 'not selected as keyframe' in line]
warnings = [line for line in lines if any(word in line.lower() for word in ('tracking fail', 'ransac fail', 'no enough', 'not enough', 'reset', 'segmentation fault'))]
poses = [(path.stem, np.loadtxt(path)) for path in sorted((args.pipeline / 'ob_in_cam').glob('*.txt'))]
angles = []
if poses:
    first = poses[0][1][:3, :3]
    for name, pose in poses:
        angle = float(np.degrees(np.arccos(np.clip((np.trace(first.T @ pose[:3, :3]) - 1) / 2, -1, 1))))
        angles.append(dict(frame=name, rotation_from_first_degrees=angle))
source = (args.repo / 'BundleTrack/scripts/data_reader.py').read_text().splitlines()
reader_lines = []
for i, line in enumerate(source):
    if 'YcbineoatReader' in line or 'def get_mask' in line:
        reader_lines.extend('%d: %s' % (j + 1, source[j]) for j in range(max(0, i - 2), min(len(source), i + 25)))
summary = dict(online_pose_count=len(poses), estimated_rotations_not_ground_truth=True,
    max_estimated_rotation_from_first_degrees=max((row['rotation_from_first_degrees'] for row in angles), default=None),
    pose_angles=angles, keyframe_lines=keyframe_lines, diagnostic_warnings=warnings[-30:],
    reader_source_context=reader_lines)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({k: summary[k] for k in ('online_pose_count', 'max_estimated_rotation_from_first_degrees')}))
print('\n'.join(keyframe_lines[-12:] + warnings[-8:] + reader_lines))
