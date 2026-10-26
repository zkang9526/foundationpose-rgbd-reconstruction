#!/usr/bin/env python3
"""Verify a transferred review package and publish only its small statistics JSON."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--review', type=Path, required=True)
p.add_argument('--local-session', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
review = args.review.resolve(strict=True)
manifest = json.loads((review / 'SHA256SUMS.json').read_text())
for name, expected in manifest.items():
    path = (review / name).resolve(strict=True)
    path.relative_to(review)
    if path.stat().st_size != expected['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
        raise ValueError('Transferred review mismatch: ' + name)
report = json.loads((review / 'report.json').read_text())
verified = len(manifest)
source_hashes = report.get('source_evidence_sha256', report.get('evidence_sha256'))
if not isinstance(source_hashes, dict) or not source_hashes:
    raise ValueError('Review needs source evidence hashes')
for name, digest in source_hashes.items():
    path = args.local_session / name
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Downloaded session mismatch: ' + name)
        verified += 1
report['transferred_files_sha256_verified'] = verified
report['review_package_sha256'] = hashlib.sha256((review / 'SHA256SUMS.json').read_bytes()).hexdigest()
if 'selected_samples' in report:
    report['sample_summary'] = [{key: row.get(key) for key in ('frame', 'capture_utc', 'seconds_from_anchor', 'error',
        'marker_reason', 'corner_rms_from_anchor_px', 'fp_rotation_change_from_anchor_deg',
        'marker_rotation_change_from_anchor_deg', 'depth_median_residual_m')} for row in report.pop('selected_samples')]
args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open('x', encoding='utf-8') as stream:
    stream.write(json.dumps(report, indent=2)+'\n')
print(json.dumps(dict(passed=True, verified_files=verified, output=str(args.output))))
