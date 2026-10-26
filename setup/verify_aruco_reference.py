#!/usr/bin/env python3
"""Print template and independent synthetic image/reference checks, never physical GT."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from cup_aruco_reference import ArucoReference, rigid_error


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    small = cv2.aruco.generateImageMarker(dictionary, 0, 6)
    cells = ''.join('<rect x="%d" y="%d" width="1" height="1"/>' % (x + 1, y + 1)
                    for y in range(6) for x in range(6) if small[y, x] == 0)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="80mm" viewBox="0 0 8 8">'
           '<rect width="8" height="8" fill="white"/><g fill="black">' + cells + '</g></svg>')
    (args.output / 'aruco_DICT_4X4_50_id0_black60mm.svg').write_text(svg, encoding='utf-8')
    preview = np.full((800, 800), 255, np.uint8)
    preview[100:700, 100:700] = cv2.resize(small, (600, 600), interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(args.output / 'aruco_preview.png'), preview)
    ref = ArucoReference(.06, fixed_scene=True)
    K = np.array([[608., 0, 328.], [0, 608., 243.], [0, 0, 1]])
    front = np.diag([1., -1., -1.])
    results = []
    detected = []
    marker_image = cv2.aruco.generateImageMarker(dictionary, 0, 600)
    for i, (rotation, translation) in enumerate((([.35, .22, .05], [-.04, -.015, .42]),
                                                ([.45, -.17, .08], [.02, .02, .46]))):
        T = np.eye(4); T[:3, :3] = cv2.Rodrigues(np.array(rotation))[0] @ front; T[:3, 3] = translation
        rvec = cv2.Rodrigues(T[:3, :3])[0]
        projected = cv2.projectPoints(ref.object_points, rvec, T[:3, 3], K, np.zeros(5))[0].reshape(4, 2)
        H = cv2.getPerspectiveTransform(np.float32([[-.5, -.5], [599.5, -.5], [599.5, 599.5], [-.5, 599.5]]), projected.astype(np.float32))
        image = cv2.warpPerspective(marker_image, H, (640, 480), flags=cv2.INTER_LINEAR, borderValue=255)
        cv2.imwrite(str(args.output / ('synthetic_camera_%d.png' % i)), image)
        info = ref.detect(cv2.cvtColor(image, cv2.COLOR_GRAY2RGB), K)
        if not info['reference_accepted']:
            raise AssertionError('Synthetic tilted marker reference rejected: ' + json.dumps(info))
        error = rigid_error(np.array(info['pose_camera_from_marker']), T)
        # ~90-pixel synthetic marker edges are rasterized. This validates the
        # coordinate convention, not a millimeter-level physical reference.
        assert error['translation_error_mm'] < 10 and error['rotation_error_deg'] < 4, error
        results.append(dict(known_camera_from_marker=T.tolist(), detected=info, error=error))
        detected.append(T)
    # An unknown constant marker->object transform must cancel from relative motion.
    A = np.eye(4); A[:3, :3] = cv2.Rodrigues(np.array([.4, -.6, .2]))[0]; A[:3, 3] = [.1, -.05, .02]
    first = ref.evaluate(detected[0] @ A, dict(reference_accepted=True, pose_camera_from_marker=detected[0].tolist()), '0', True)
    second = ref.evaluate(detected[1] @ A, dict(reference_accepted=True, pose_camera_from_marker=detected[1].tolist()), '1', True)
    assert second['relative_errors']['translation_error_mm'] < 1e-8
    assert second['relative_errors']['rotation_error_deg'] < 1e-5
    assert second['anchored_object_errors']['translation_error_mm'] < 1e-8
    shifted = detected[1] @ A
    shifted[:3, 3] += [.01, 0, 0]
    injected = ref.evaluate(shifted, dict(reference_accepted=True, pose_camera_from_marker=detected[1].tolist()), '2', True)
    assert abs(injected['relative_errors']['translation_error_mm'] - 10) < 1e-6
    assert abs(injected['anchored_object_errors']['translation_error_mm'] - 10) < 1e-6
    absent = ref.detect(np.full((480, 640, 3), 255, np.uint8), K)
    assert not absent['reference_accepted']
    assert ref.evaluate(shifted, absent, '3', True)['relative_errors'] is None
    invalid = ref.evaluate(shifted, dict(reference_accepted=True, pose_camera_from_marker=detected[1].tolist()), '4', False)
    assert invalid['relative_errors'] is None
    report = dict(passed=True, opencv=cv2.__version__, synthetic_only=True, physical_accuracy_validated=False,
                  template=dict(dictionary='DICT_4X4_50', id=0, nominal_black_side_mm=60,
                                nominal_paper_square_mm=80, require_measured_black_side=True),
                  synthetic_pose_checks=results, unknown_constant_transform_cancellation=second,
                  injected_translation_error=injected, missing_marker_returns_null=True,
                  rejected_tracking_returns_null=True,
                  checks='image detection + independent known camera poses; relative SE3 cancellation and injected errors')
    report['artifact_sha256'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in args.output.iterdir() if f.is_file()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, output=str(args.output), physical_accuracy_validated=False)), flush=True)


if __name__ == '__main__':
    main()
