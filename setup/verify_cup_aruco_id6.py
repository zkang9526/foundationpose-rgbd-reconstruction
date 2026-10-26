#!/usr/bin/env python3
"""Check ID6/5x5 detection, meter scale and null invalid errors; synthetic, no physical GT."""
import argparse
import ast
import json
from pathlib import Path
import cv2
import numpy as np
from cup_aruco_reference import ArucoReference


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for name in ('cup_aruco_reference.py', 'cup_live_dashboard.py', 'run_cup_live_fast.py',
                 'inspect_cup_aruco_scene.py', 'cup_live_control.py', 'configure_cup_aruco_id6.py'):
        ast.parse((Path(__file__).parent / name).read_text(encoding='utf-8-sig'))
    K = np.array([[608., 0, 328.], [0, 608., 243.], [0, 0, 1.]])
    reference = ArucoReference(.03, 6, 'DICT_5X5_50', fixed_scene=True)
    T = np.eye(4)
    T[:3, :3] = cv2.Rodrigues(np.array([.4, .25, .03]))[0] @ np.diag([1., -1., -1.])
    T[:3, 3] = [.01, -.02, .28]
    projected = cv2.projectPoints(reference.object_points, cv2.Rodrigues(T[:3, :3])[0], T[:3, 3], K, np.zeros(5))[0].reshape(4, 2)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_50)
    marker = cv2.aruco.generateImageMarker(dictionary, 6, 600)
    H = cv2.getPerspectiveTransform(np.float32([[-.5, -.5], [599.5, -.5], [599.5, 599.5], [-.5, 599.5]]), projected.astype(np.float32))
    image = cv2.warpPerspective(marker, H, (640, 480), flags=cv2.INTER_LINEAR, borderValue=255)
    rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    detected = reference.detect(rgb, K)
    assert detected['reference_accepted'], detected
    wrong_dictionary = ArucoReference(.03, 6, 'DICT_4X4_50').detect(rgb, K)
    assert not wrong_dictionary['reference_accepted']
    doubled = ArucoReference(.06, 6, 'DICT_5X5_50').detect(rgb, K)
    assert doubled['reference_accepted']
    pose = np.array(detected['pose_camera_from_marker'])
    assert np.allclose(np.array(doubled['pose_camera_from_marker'])[:3, 3], pose[:3, 3] * 2, atol=1e-8)
    before_confirmation = reference.evaluate(T, detected, 'unconfirmed', False)
    assert before_confirmation['anchored_object_errors'] is None and reference.anchor_frame is None
    reference.evaluate(T, detected, 'anchor', True)
    shifted = T.copy(); shifted[0, 3] += .01
    error = reference.evaluate(shifted, detected, 'shifted', True)
    assert abs(error['anchored_object_errors']['translation_error_mm'] - 10) < 1e-8
    absent = reference.detect(np.full_like(rgb, 255), K)
    assert reference.evaluate(shifted, absent, 'absent', True)['anchored_object_errors'] is None
    report = dict(passed=True, synthetic_only=True, physical_accuracy_validated=False,
                  dictionary='DICT_5X5_50', marker_id=6, measured_black_side_m=.03,
                  checks=dict(source_syntax=True, target_detected=True, wrong_dictionary_rejected=True,
                              marker_length_scales_translation=True, unconfirmed_pose_cannot_anchor=True,
                              injected_10mm_drift_measured=True, absent_reference_errors_null=True),
                  synthetic_detection=detected)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
