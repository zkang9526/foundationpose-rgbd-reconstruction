"""Audit a real capture without changing acceptance, fitting K, or writing calibration."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

import cv2
import numpy as np

from analyze import plane_metrics, T_of
from common import (board_points, camera_model, distribution, now, pose, project,
                    rms, sha, snapshot_sources, write_json)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    snapshot_sources(a.output)
    meta = json.loads((a.input / 'factory.json').read_text(encoding='utf-8'))
    session = json.loads((a.input / 'session.json').read_text(encoding='utf-8'))
    obj = board_points(meta['board'])
    counts, rows, panels, failures = Counter(), [], [], []
    verified = 0
    for folder in sorted((a.input / 'trials').iterdir()):
        trial = json.loads((folder / 'trial.json').read_text(encoding='utf-8'))
        counts.update(trial['reasons'])
        for entry in trial['files']:
            path = folder / entry['name']
            if not path.is_file() or sha(path) != entry['sha256']:
                failures.append(str(path))
            verified += 1
        row = dict(trial=folder.name, accepted=trial['accepted'], reasons=trial['reasons'],
                   trial_json_sha256=sha(folder / 'trial.json'),
                   motion_p95_px=trial.get('stationarity_motion_p95_px'),
                   motion_interval_s=trial.get('stationarity_interval_s'),
                   timestamp_span_ms=trial.get('timestamp_span_ms'),
                   rgb_detected=trial['corners']['rgb'] is not None,
                   ir1_detected=trial['corners']['ir1'] is not None,
                   ir2_detected=trial['corners']['ir2'] is not None)
        if row['rgb_detected']:
            K, d = camera_model(meta['intrinsics']['rgb'])
            points = np.array(trial['corners']['rgb'], np.float32)
            T = pose(obj, points, K, d)
            row['rgb_factory_reprojection_rms_px'] = rms(project(obj, T, K, d), points)
            row['rgb_board_center_px'] = points.mean(axis=0).tolist()
            normal = T[:3, 2] * (1 if T[2, 2] >= 0 else -1)
            row['rgb_board_normal_angles_deg'] = np.degrees(np.arctan2(normal[:2], normal[2])).tolist()
            row['rgb_board_hull_area_px2'] = float(cv2.contourArea(cv2.convexHull(points)))
            row['rgb_board_center_z_m'] = float((obj.mean(axis=0) @ T[:3, :3].T + T[:3, 3])[2])
            if trial['corners'].get('ir1_ordered') is not None:
                Ki, di = camera_model(meta['intrinsics']['ir1'])
                pi = np.array(trial['corners']['ir1_ordered'], np.float32)
                Ti = pose(obj, pi, Ki, di)
                projected = project(obj, T_of(meta, 'ir1', 'rgb') @ Ti, K, d)
                residual = projected-points
                row['factory_ir1_to_rgb_rms_px'] = rms(projected, points)
                row['cross_projection_mean_dx_dy_px'] = residual.mean(axis=0).tolist()
                depth = np.load(str(folder / 'depth_native.npy'), allow_pickle=False)
                for reference, Td in [('ir1', T_of(meta, 'ir1', 'depth_native') @ Ti),
                                      ('rgb', T_of(meta, 'rgb', 'depth_native') @ T)]:
                    pm = plane_metrics(depth, meta, Td, obj)
                    row['depth_vs_' + reference] = pm
                if trial['accepted']:
                    overlay = cv2.imread(str(folder / 'rgb.png'))
                    for detected, predicted in zip(points, projected):
                        q, r = tuple(np.round(detected).astype(int)), tuple(np.round(predicted).astype(int))
                        cv2.circle(overlay, q, 3, (0, 255, 0), 1)
                        cv2.drawMarker(overlay, r, (255, 0, 255), cv2.MARKER_CROSS, 5, 1)
                    cv2.putText(overlay, 'Green: RGB; magenta: IR1 pose + factory extrinsic', (7, 20),
                                cv2.FONT_HERSHEY_SIMPLEX, .43, (0, 255, 255), 1)
                    cv2.imwrite(str(a.output / ('cross_projection_' + folder.name + '.png')), overlay)
        rows.append(row)
        image = cv2.imread(str(folder / 'rgb.png'))
        image = cv2.resize(image, (320, 240))
        image = cv2.copyMakeBorder(image, 32, 0, 0, 0, cv2.BORDER_CONSTANT, value=(20, 20, 20))
        motion = row['motion_p95_px']
        label = folder.name + (' ACCEPTED' if row['accepted'] else ' REJECTED')
        label += (' motion=%.2fpx' % motion) if motion is not None else ' incomplete corners'
        cv2.putText(image, label, (5, 21), cv2.FONT_HERSHEY_SIMPLEX, .42,
                    (0, 255, 0) if row['accepted'] else (70, 180, 255), 1)
        panels.append(image)
    grid = []
    for start in range(0, len(panels), 4):
        group = panels[start:start+4]
        group += [np.zeros_like(panels[0])] * (4-len(group))
        grid.append(np.hstack(group))
    if grid:
        cv2.imwrite(str(a.output / 'all_trials_contact_sheet.jpg'), np.vstack(grid))
    accepted = [r for r in rows if r['accepted']]
    complete = [r for r in rows if 'factory_ir1_to_rgb_rms_px' in r]
    rgb = [r for r in rows if 'rgb_board_center_px' in r]
    def summarize(subset):
        summary = dict(n=len(subset))
        for key in ('rgb_factory_reprojection_rms_px', 'factory_ir1_to_rgb_rms_px', 'rgb_board_center_z_m', 'motion_p95_px'):
            summary[key] = distribution([r[key] for r in subset if r.get(key) is not None])
        for reference in ('ir1', 'rgb'):
            values = [r['depth_vs_' + reference] for r in subset if 'depth_vs_' + reference in r]
            summary['depth_vs_' + reference] = dict(
                valid_fraction=distribution([v['valid_fraction'] for v in values]),
                per_frame_z_bias_mm=distribution([(v.get('z_measured_minus_predicted_mm') or {}).get('median', np.nan) for v in values]),
                per_frame_depth_plane_rms_mm=distribution([(v.get('depth_best_fit_plane_residual_mm') or {}).get('rms', np.nan) for v in values]))
        return summary
    result = dict(created_utc=now(), input=str(a.input.resolve()), session=session,
                  verified_files=verified, sha_failures=failures, all_trial_count=len(rows), accepted_count=len(accepted),
                  reason_counts=dict(counts), accepted_summary=summarize(accepted),
                  rejected_and_accepted_diagnostic_only=summarize(complete), rows=rows,
                  source_factory_sha256=sha(a.input / 'factory.json'),
                  acceptance_changed=False, calibration_fitted=False, physical_accuracy_accepted=False,
                  boundary_annotation_count=len(list((a.input / 'boundary_checks').glob('*/boundary.json'))))
    if rgb:
        centers = np.array([r['rgb_board_center_px'] for r in rgb])
        tilts = np.array([r['rgb_board_normal_angles_deg'] for r in rgb])
        areas = np.array([r['rgb_board_hull_area_px2'] for r in rgb])
        result['all_rgb_diagnostic_coverage'] = dict(n=len(rgb), center_span_px=np.ptp(centers, axis=0).tolist(),
            normal_angle_span_deg=np.ptp(tilts, axis=0).tolist(), apparent_linear_scale_ratio=float(np.sqrt(areas.max()/areas.min())),
            scope='Includes rejected moving frames; does not qualify these frames as accepted calibration data')
    write_json(a.output / 'review.json', result)
    fields = ['trial', 'accepted', 'motion_p95_px', 'motion_interval_s', 'timestamp_span_ms', 'rgb_detected',
              'ir1_detected', 'ir2_detected', 'rgb_factory_reprojection_rms_px', 'factory_ir1_to_rgb_rms_px']
    with (a.output / 'trials.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: r.get(k) for k in fields} for r in rows)
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'session')}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
