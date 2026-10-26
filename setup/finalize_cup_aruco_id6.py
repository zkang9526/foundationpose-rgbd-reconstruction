#!/usr/bin/env python3
"""Verify E-drive review evidence and publish a small tracked measurement summary."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
args = p.parse_args()
root = args.root.resolve(strict=True)
review = root / 'reviews/aruco_id6_20261015'
package = review / 'aruco_id6_analysis_20261015_final'
manifest = json.loads((package / 'SHA256SUMS.json').read_text())
for name, expected in manifest.items():
    path = (package / name).resolve(strict=True)
    path.relative_to(package)
    if path.stat().st_size != expected['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
        raise ValueError('Transfer evidence mismatch: ' + name)
report = json.loads((package / 'report.json').read_text())
for local, expected in (('session.json', 'session.json'), ('aruco_errors.csv', 'aruco_errors.csv')):
    if hashlib.sha256((review / local).read_bytes()).hexdigest() != report['evidence_sha256'][expected]:
        raise ValueError('Session evidence mismatch: ' + local)
depth = np.load(review / 'loss1938/depth.npy', allow_pickle=False)
report['loss_frame_depth_statistics'] = dict(shape=list(depth.shape),
    whole_image_valid_fraction=float(np.count_nonzero(depth) / depth.size),
    whole_image_nonzero_pixels=int(np.count_nonzero(depth)), unit='millimeters')
report['transfer_files_sha256_verified'] = len(manifest) + 2
report['peak_neighbor_changes'] = [{k: row.get(k) for k in ('frame', 'error', 'fp_pose_change_from_previous',
    'marker_pose_change_from_previous', 'marker_corner_change_from_previous_rms_px')}
    for row in report.pop('worst_frames') if row.get('error') is not None]
recovery = [json.loads(line) for line in (review / 'recovery_events.jsonl').read_text().splitlines()]
report['recovery_searches'] = [dict(time_utc=e['time_utc'], matched=e['matched'], error=e.get('error'))
    for e in recovery if e['event'] == 'search_result']
report['recovery_freshness_checks'] = [dict(time_utc=e['time_utc'], queued=e.get('queued_for_registration'), motion=e.get('motion'))
    for e in recovery if e['event'] == 'search_consumed']
source = root / 'reports/report.json'
if source.exists():
    preflight = json.loads(source.read_text())
    if preflight.get('marker_id') != 6 or 'aruco_id6_preflight_20261015_v2' not in preflight.get('output', ''):
        raise ValueError('Generic report is unrelated; preserved')
    target = review / 'preflight_v2.json'
    if target.exists():
        raise ValueError('Preflight archive already exists; preserved')
    shutil.move(str(source), str(target))
source_image = root / 'reports/preview_000045.png'
if source_image.exists() and not (review / 'preflight_v2.png').exists():
    shutil.move(str(source_image), str(review / 'preflight_v2.png'))
target = root / 'reports/CUP_ARUCO_ID6_MEASUREMENTS_20261015.json'
if target.exists():
    raise ValueError('Curated report already exists; preserve prior result')
target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(passed=True, files_sha256_verified=report['transfer_files_sha256_verified'],
                     loss_frame_depth_statistics=report['loss_frame_depth_statistics'], report=str(target),
                     peak_neighbor_changes=report['peak_neighbor_changes']), ensure_ascii=False))
