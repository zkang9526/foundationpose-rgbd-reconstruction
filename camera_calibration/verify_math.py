"""Synthetic numeric verification only. This is not a camera accuracy test."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np
import pyrealsense2 as rs

from analyze import calibration, plane_metrics, stereo_check
from boundary import check_boundary
from common import board_points, camera_model, detect, extrinsic, orient_corners, project, rms, sha, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    board = json.loads(Path(__file__).with_name('board.json').read_text(encoding='utf-8-sig'))
    obj = board_points(board)
    model = dict(width=640, height=480, fx=600., fy=605., cx=320., cy=240.,
                 model='distortion.brown_conrady', coeffs=[.01, -.005, .0002, -.0001, 0.])
    K, d = camera_model(model)
    zero = dict(model, model='distortion.inverse_brown_conrady', coeffs=[0.]*5)
    assert np.all(camera_model(zero)[1] == 0)
    try:
        camera_model(dict(model, model='distortion.modified_brown_conrady'))
        raise AssertionError('Unsupported nonzero distortion was silently accepted')
    except ValueError:
        pass
    Tpair = np.eye(4)
    Tpair[:3, :3] = cv2.Rodrigues(np.array([.005, -.009, .002]))[0]
    Tpair[:3, 3] = [.014, -.0002, .0005]
    rng = np.random.default_rng(42)
    left, right, transforms = [], [], []
    for _ in range(25):
        T = np.eye(4)
        T[:3, :3] = cv2.Rodrigues(rng.uniform(-.5, .5, 3))[0]
        T[:3, 3] = [rng.uniform(-.17, .04), rng.uniform(-.11, .02), rng.uniform(.45, .85)]
        left.append(project(obj, T, K, d).astype(np.float32))
        right.append(project(obj, Tpair @ T, K, d).astype(np.float32))
        transforms.append(T)
    reversed_pts = right[0][::-1]
    reordered, order = orient_corners(reversed_pts, right[0], board)
    assert rms(reordered, right[0]) < 1e-5 and order['choice'] == 1
    train, val = [i for i in range(25) if i % 5 != 4], list(range(4, 25, 5))
    intr = calibration(obj, left, train, val, (640, 480), model)
    assert intr['holdout_candidate_rms_px']['rms'] < .001
    assert max(abs(x) for x in intr['relative_focal_change_percent']) < .01
    stereo = stereo_check(obj, left, right, train, val, (640, 480), model, model, Tpair)
    assert stereo['holdout_candidate_rms_px']['rms'] < .001
    assert stereo['translation_difference_mm'] < .02
    assert stereo['rotation_difference_deg'] < .01
    T = np.eye(4)
    T[:3, 3] = [-.1, -.05, .6]
    depth = np.full((480, 640), 600, np.uint16)
    plane = plane_metrics(depth, dict(intrinsics={'depth_native': zero}, board=board, depth_scale_m=.001), T, obj)
    assert plane['valid_fraction'] == 1
    assert abs(plane['z_measured_minus_predicted_mm']['median']) < 1e-6
    assert plane['depth_best_fit_plane_residual_mm']['rms'] < 1e-6
    class Profile:
        def get_extrinsics_to(self, _):
            e = rs.extrinsics()
            e.rotation = Tpair[:3, :3].flatten(order='F').tolist()
            e.translation = Tpair[:3, 3].tolist()
            return e
    serialized = extrinsic(Profile(), Profile(), rs)
    assert np.allclose(serialized['T_destination_from_source'], Tpair, atol=1e-7)
    # Exercise real image corner detection rather than only synthetic points.
    checker = np.full(((board['rows']+1)*40+40, (board['cols']+1)*40+40), 255, np.uint8)
    for y in range(board['rows']+1):
        for x in range(board['cols']+1):
            checker[20+y*40:20+(y+1)*40, 20+x*40:20+(x+1)*40] = 0 if (x+y) % 2 == 0 else 255
    assert detect(checker, board).shape == (board['rows']*board['cols'], 2)
    # A known +4-pixel depth-silhouette shift should be recovered to pixel precision.
    border_trial = a.output / 'boundary_source'
    border_trial.mkdir()
    cv2.imwrite(str(border_trial / 'rgb.png'), np.zeros((480, 640, 3), np.uint8))
    rectangle = np.full((480, 640), 900, np.uint16)
    rectangle[100:350, 104:504] = 600
    np.save(str(border_trial / 'depth_aligned.npy'), rectangle)
    b = check_boundary(border_trial, [[100, 100], [500, 100], [500, 350], [100, 350]], .001, a.output / 'boundary_test')
    assert b['edges'][1]['matched'] > 60 and b['edges'][3]['matched'] > 60
    assert abs(b['edges'][3]['signed_offset_px']['median']-3.5) < 1.1
    assert abs(b['edges'][1]['signed_offset_px']['median']+3.5) < 1.1
    dataset = a.output / 'synthetic_session'
    (dataset / 'trials').mkdir(parents=True)
    def ex(T):
        return dict(T_destination_from_source=T.tolist())
    ir2_from_ir1 = np.eye(4)
    ir2_from_ir1[0, 3] = -.05
    meta = dict(board=board, device={'name': 'SYNTHETIC: NOT A PHYSICAL CAMERA'}, data_origin='synthetic_verification',
                depth_scale_m=.001, intrinsics={k: model for k in ('rgb', 'ir1', 'ir2', 'depth_native')},
                extrinsics=dict(ir1_to_rgb=ex(Tpair), ir1_to_ir2=ex(ir2_from_ir1),
                                ir1_to_depth_native=ex(np.eye(4)), rgb_to_depth_native=ex(np.linalg.inv(Tpair))),
                align='synthetic test only', aligned_shape_matches_rgb=True, aligned_intrinsics_match_rgb=True)
    write_json(dataset / 'factory.json', meta)
    yy, xx = np.mgrid[:480, :640]
    normalized = cv2.undistortPoints(np.stack([xx, yy], axis=-1).astype(float).reshape(-1, 1, 2), K, d).reshape(480, 640, 2)
    rays = np.concatenate([normalized, np.ones((480, 640, 1))], axis=2)
    for i, T in enumerate(transforms):
        trial_dir = dataset / 'trials' / ('%04d' % (i+1))
        trial_dir.mkdir()
        n, t = T[:3, 2], T[:3, 3]
        z = np.dot(n, t)/(rays @ n)
        values = np.round(np.clip(z*1000, 0, 65535)).astype(np.uint16)
        np.save(str(trial_dir / 'depth_native.npy'), values)
        write_json(trial_dir / 'trial.json', dict(accepted=True, reasons=[],
            corners=dict(rgb=right[i].tolist(), ir1_ordered=left[i].tolist(),
                         ir2_ordered=project(obj, ir2_from_ir1 @ T, K, d).tolist()),
            files=[dict(name='depth_native.npy', sha256=sha(trial_dir / 'depth_native.npy'))]))
    completed = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('analyze.py')),
                               '--input', str(dataset), '--output', str(a.output / 'end_to_end')], check=False)
    assert completed.returncode == 0
    full = json.loads((a.output / 'end_to_end' / 'report.json').read_text(encoding='utf-8'))
    assert full['accepted_views'] == 25 and full['analysis_completed']
    assert full['physical_calibration_accepted'] is False and full['data_origin'] == 'synthetic_verification'
    assert full['candidate_extrinsics']['ir1_to_rgb']['holdout_candidate_rms_px']['rms'] < .001
    result = dict(passed=True, physical_camera_test=False, tests=['column-major SDK extrinsic transform',
        'discrete chessboard correspondence', 'held-out intrinsic recovery', 'held-out stereo recovery',
        'native depth ray/plane and metric units', 'unsupported distortion rejection',
        'image chessboard detection', 'manual-boundary known depth shift',
        '25-view analysis with train/holdout reports and synthetic-data labeling'],
        intrinsic_holdout_rms_px=intr['holdout_candidate_rms_px']['rms'],
        stereo_holdout_rms_px=stereo['holdout_candidate_rms_px']['rms'])
    write_json(a.output / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
