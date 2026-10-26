"""Check numerical validity of a recorded factory snapshot, not physical accuracy."""
import argparse
import json
from pathlib import Path

import numpy as np

from common import camera_model, sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.session / 'factory.json'
    meta = json.loads(source.read_text(encoding='utf-8'))
    report = dict(device=meta['device'], factory_sha256=sha(source),
                  depth_scale_m=meta['depth_scale_m'], intrinsics=meta['intrinsics'],
                  depth_options=meta['depth_options'], extrinsics={}, checks={},
                  physical_calibration_accepted=False,
                  scope='Numerical structure and SDK metadata only; requires physical board observations')
    for name, model in meta['intrinsics'].items():
        K, d = camera_model(model)
        report['checks'][name + '_finite_positive_focal_and_principal_in_frame'] = bool(
            np.isfinite(K).all() and np.isfinite(d).all() and model['fx'] > 0 and model['fy'] > 0
            and 0 <= model['cx'] < model['width'] and 0 <= model['cy'] < model['height'])
    for name, item in meta['extrinsics'].items():
        T = np.array(item['T_destination_from_source'])
        R = T[:3, :3]
        orthogonal = float(np.linalg.norm(R.T @ R - np.eye(3)))
        det = float(np.linalg.det(R))
        valid = bool(np.isfinite(T).all() and np.allclose(T[3], [0, 0, 0, 1])
                     and orthogonal < 1e-5 and abs(det-1) < 1e-5
                     and item['sdk_basis_vector_check_passed'])
        report['checks'][name + '_rigid_transform_and_sdk_direction'] = valid
        report['extrinsics'][name] = dict(translation_mm=(T[:3, 3]*1000).tolist(),
            translation_norm_mm=float(np.linalg.norm(T[:3, 3])*1000),
            rotation_orthogonality_error=orthogonal, rotation_determinant=det,
            T_destination_from_source=T.tolist())
    report['checks']['finite_positive_depth_scale'] = bool(np.isfinite(meta['depth_scale_m']) and meta['depth_scale_m'] > 0)
    report['checks']['aligned_shape_matches_rgb'] = bool(meta['aligned_shape_matches_rgb'])
    report['checks']['aligned_intrinsics_match_rgb'] = bool(meta['aligned_intrinsics_match_rgb'])
    report['checks']['device_calibration_not_written'] = meta['device_calibration_written'] is False
    report['numerical_checks_passed'] = all(report['checks'].values())
    write_json(args.output / 'report.json', report)
    print(json.dumps(dict(numerical_checks_passed=report['numerical_checks_passed'],
        physical_calibration_accepted=False, checks=len(report['checks']),
        depth_to_rgb_translation_mm=report['extrinsics']['depth_native_to_rgb']['translation_mm'],
        ir_stereo_baseline_mm=report['extrinsics']['ir1_to_ir2']['translation_norm_mm'],
        depth_options=report['depth_options'], report=str(args.output / 'report.json')), ensure_ascii=False))
    return 0 if report['numerical_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
