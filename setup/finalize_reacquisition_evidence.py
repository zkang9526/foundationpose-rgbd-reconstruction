"""Verify downloaded evidence and publish small immutable Git-tracked summaries."""
import hashlib
import json
from pathlib import Path
import statistics

root = Path(__file__).resolve().parent.parent
source = root / 'reviews/reacquisition_verified_evidence_20261015'
manifest = json.loads((source / 'manifest.json').read_text())
for item in manifest['files']:
    data = (source / item['path']).read_bytes()
    if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('Downloaded evidence mismatch: ' + item['path'])
proofs = {
    'reacquisition_shift_test_20261015_v1': 'AUTO_RECOVERY_SHIFT_VERIFICATION_20261015.json',
    'reacquisition_real_return_20261015_v1': 'AUTO_RECOVERY_REAL_VIEW_VERIFICATION_20261015.json',
    'reacquisition_final_real_return_20261015_v2': 'AUTO_RECOVERY_FINAL_VERIFICATION_20261015.json',
    'sam2_first_frame_verification_20261015_v1': 'SAM2_FIRST_FRAME_VERIFICATION_20261015.json',
    'reacquisition_tracking_regression_20261015_v1': 'AUTO_RECOVERY_TRACKING_REGRESSION_20261015.json',
}
for name, target_name in proofs.items():
    data = (source / 'derived' / name / 'report.json').read_bytes()
    assert json.loads(data)['passed']
    target = root / 'reports' / target_name
    if target.exists() and target.read_bytes() != data:
        raise RuntimeError('Existing evidence differs; retain and use a new report version')
    if not target.exists():
        target.write_bytes(data)
comparison = json.loads((root / 'reviews/cup_sam_sam2_comparison_20261015_v1/report.json').read_text())
summary = dict(frames=len(comparison['frames']), source='same images, same box, zero clicks; single sequential run per model/image',
    sam_host_seconds_median=statistics.median(v['sam']['host_seconds'] for v in comparison['frames']),
    sam2_host_seconds_median=statistics.median(v['sam2']['host_seconds'] for v in comparison['frames']),
    sam_inference_ms_median=statistics.median(v['sam']['inference_seconds'] * 1000 for v in comparison['frames']),
    sam2_inference_ms_median=statistics.median(v['sam2']['inference_seconds'] * 1000 for v in comparison['frames']),
    sam_peak_allocated_mb_median=statistics.median(v['sam']['cuda_peak_allocated_mb'] for v in comparison['frames']),
    sam2_peak_allocated_mb_median=statistics.median(v['sam2']['cuda_peak_allocated_mb'] for v in comparison['frames']),
    mask_agreement_iou_min=min(v['cross_model_mask_iou'] for v in comparison['frames']),
    mask_agreement_iou_max=max(v['cross_model_mask_iou'] for v in comparison['frames']),
    agreement_is_accuracy=False, physical_accuracy_validated=False,
    default_first_frame_backend='sam', optional_first_frame_backend='sam2', reacquisition_backend='sam2 automatic mask proposals',
    compared=[dict(name=v['name'], agreement=v['cross_model_mask_iou'], sam_attempt=v['sam']['attempt'], sam2_attempt=v['sam2']['attempt']) for v in comparison['frames']])
(root / 'reports/SAM_SAM2_COMPARISON_SUMMARY_20261015.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(dict(passed=True, sha256_verified_files=len(manifest['files']), comparison=summary), indent=2))
