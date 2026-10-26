"""Separate factory checks, held-out candidate calibration, depth and alignment.

Candidate intrinsics/extrinsics are files only, never written to the device.
"""
import argparse
import csv
import json
from pathlib import Path
import traceback

import cv2
import numpy as np

from common import (board_points, camera_model, distribution, now, pose, project,
                    rms, sha, snapshot_sources, write_json)


def T_of(meta, src, dst):
    return np.array(meta['extrinsics'][src + '_to_' + dst]['T_destination_from_source'])


def plane_metrics(depth, meta, T_depth_from_board, obj):
    K, d = camera_model(meta['intrinsics']['depth_native'])
    outline = project(obj[[0, meta['board']['cols']-1, -1, -meta['board']['cols']]], T_depth_from_board, K, d)
    mask = np.zeros(depth.shape, np.uint8)
    cv2.fillConvexPoly(mask, np.round(outline).astype(np.int32), 1)
    mask = cv2.erode(mask, np.ones((9, 9), np.uint8)) > 0
    ys, xs = np.nonzero(mask & (depth > 0))
    result = dict(interior_pixels=int(mask.sum()), valid_depth_pixels=len(xs),
                  valid_fraction=float(len(xs)/max(1, mask.sum())))
    if len(xs) < 200:
        result['insufficient_valid_depth'] = True
        return result
    step = max(1, len(xs)//5000)
    xs, ys = xs[::step], ys[::step]
    normalized = cv2.undistortPoints(np.column_stack([xs, ys]).astype(float).reshape(-1, 1, 2), K, d).reshape(-1, 2)
    rays = np.column_stack([normalized, np.ones(len(xs))])
    measured_z = depth[ys, xs] * meta['depth_scale_m']
    n, t = T_depth_from_board[:3, 2], T_depth_from_board[:3, 3]
    den = rays @ n
    use = np.abs(den) > .1
    rays, measured_z, den = rays[use], measured_z[use], den[use]
    predicted_z = np.dot(n, t) / den
    result['z_measured_minus_predicted_mm'] = distribution((measured_z-predicted_z)*1000)
    result['signed_distance_to_board_plane_mm'] = distribution((measured_z*den - np.dot(n, t))*1000)
    result['z_ratio_measured_over_predicted'] = distribution(measured_z/predicted_z)
    points = rays * measured_z[:, None]
    keep = np.ones(len(points), bool)
    for _ in range(3):
        center = points[keep].mean(axis=0)
        normal = np.linalg.svd(points[keep]-center, full_matrices=False)[2][-1]
        distance = np.abs((points-center) @ normal)
        keep = distance <= max(.001, float(np.percentile(distance, 90)))
    result['depth_best_fit_plane_residual_mm'] = distribution(((points[keep]-center) @ normal)*1000)
    result['depth_best_fit_retained_fraction'] = float(keep.mean())
    result['depth_plane_normal_difference_deg'] = float(np.degrees(np.arccos(np.clip(abs(np.dot(normal, n)), 0, 1))))
    return result


def calibration(obj, observations, train, val, image_size, factory):
    objlist = [obj.copy() for _ in train]
    imglist = [observations[i].astype(np.float32).reshape(-1, 1, 2) for i in train]
    error, K, d, _, _, std_intr, _, per_view = cv2.calibrateCameraExtended(objlist, imglist, image_size, None, None)
    candidate = dict(K=K.tolist(), distortion_coefficients=d.ravel().tolist(), model='OpenCV Brown-Conrady 5 parameters',
                     training_rms_px=float(error), training_per_view_rms_px=per_view.ravel().tolist(),
                     estimated_intrinsic_stddev=std_intr.ravel().tolist(), written_to_device=False)
    rows = []
    Kf, df = camera_model(factory)
    for i in val:
        obs = observations[i]
        Tc, Tf = pose(obj, obs, K, d), pose(obj, obs, Kf, df)
        rows.append(dict(view=i, factory_rms_px=rms(project(obj, Tf, Kf, df), obs),
                         candidate_rms_px=rms(project(obj, Tc, K, d), obs)))
    candidate['holdout'] = rows
    candidate['holdout_factory_rms_px'] = distribution([r['factory_rms_px'] for r in rows])
    candidate['holdout_candidate_rms_px'] = distribution([r['candidate_rms_px'] for r in rows])
    candidate['factory_K'] = Kf.tolist()
    candidate['relative_focal_change_percent'] = [float((K[j, j]/Kf[j, j]-1)*100) for j in (0, 1)]
    return candidate


def stereo_check(obj, left, right, train, val, size, ml, mr, factory_T):
    Kl, dl = camera_model(ml)
    Kr, dr = camera_model(mr)
    fit = cv2.stereoCalibrate([obj.copy() for _ in train], [left[i].reshape(-1, 1, 2) for i in train],
                              [right[i].reshape(-1, 1, 2) for i in train], Kl.copy(), dl.copy(), Kr.copy(), dr.copy(),
                              size, flags=cv2.CALIB_FIX_INTRINSIC,
                              criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 150, 1e-8))
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = fit[5], fit[6].ravel()
    rows = []
    for i in val:
        Tl = pose(obj, left[i], Kl, dl)
        rows.append(dict(view=i, factory_rms_px=rms(project(obj, factory_T @ Tl, Kr, dr), right[i]),
                         candidate_rms_px=rms(project(obj, T @ Tl, Kr, dr), right[i])))
    angle = np.degrees(np.arccos(np.clip((np.trace(T[:3, :3] @ factory_T[:3, :3].T)-1)/2, -1, 1)))
    return dict(training_joint_rms_px=float(fit[0]), fitted_T_destination_from_source=T.tolist(),
                factory_T_destination_from_source=factory_T.tolist(), unit='meter',
                rotation_difference_deg=float(angle), translation_difference_mm=float(np.linalg.norm(T[:3, 3]-factory_T[:3, 3])*1000),
                holdout=rows, holdout_factory_rms_px=distribution([r['factory_rms_px'] for r in rows]),
                holdout_candidate_rms_px=distribution([r['candidate_rms_px'] for r in rows]),
                fitted_intrinsics='fixed factory intrinsics; intrinsic bias can appear in fitted extrinsics',
                written_to_device=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    result = dict(created_utc=now(), input=str(a.input.resolve()), physical_calibration_accepted=False,
                  robot_world_extrinsics_validated=False, notes=[], per_view=[], candidate_intrinsics={}, candidate_extrinsics={})
    result['executed_source'] = snapshot_sources(a.output)
    code = 0
    try:
        meta = json.loads((a.input / 'factory.json').read_text(encoding='utf-8'))
        board, obj = meta['board'], board_points(meta['board'])
        result['device'], result['board'] = meta['device'], board
        result['capture_sensor_settings'] = dict(depth_options=meta.get('depth_options', {}),
                                                  emitter_control=meta.get('emitter_control', {}))
        result['production_active_depth_accepted'] = False
        if meta.get('depth_options', {}).get('emitter_enabled') == 0:
            result['notes'].append('Projector was OFF for checkerboard geometry capture. Depth statistics here do not validate production projector-ON depth; acquire a separate active-depth check.')
        result['data_origin'] = meta.get('data_origin', 'not_recorded')
        result['software_alignment'] = {k: meta.get(k) for k in ('align', 'aligned_shape_matches_rgb', 'aligned_intrinsics_match_rgb')}
        result['software_alignment']['physical_boundary_alignment_verified'] = False
        result['source_factory_sha256'] = sha(a.input / 'factory.json')
        observations = {k: [] for k in ('rgb', 'ir1', 'ir2')}
        paths, Ts = [], []
        for folder in sorted((a.input / 'trials').iterdir()):
            trial_path = folder / 'trial.json'
            if not trial_path.is_file():
                continue
            trial = json.loads(trial_path.read_text(encoding='utf-8'))
            result.setdefault('trial_index', []).append(dict(name=folder.name, accepted=trial['accepted'],
                                                            sha256=sha(trial_path), reasons=trial['reasons']))
            if not trial['accepted']:
                continue
            # Verify immutable source evidence before using it for calibration.
            for item in trial['files']:
                if sha(folder / item['name']) != item['sha256']:
                    raise ValueError('Source SHA mismatch: ' + str(folder / item['name']))
            obs = {k: (None if trial['corners'].get(k if k == 'rgb' else k + '_ordered') is None else
                       np.array(trial['corners'][k if k == 'rgb' else k + '_ordered'], np.float32)) for k in observations}
            if obs['rgb'] is None or obs['ir1'] is None:
                raise ValueError('Accepted trial lacks corresponding RGB and IR1 points')
            index = len(paths)
            paths.append(folder.name)
            for k in observations:
                observations[k].append(obs[k])
            poses = {k: pose(obj, obs[k], *camera_model(meta['intrinsics'][k])) for k in ('rgb', 'ir1')}
            Ts.append(poses['rgb'])
            rgb_K, rgb_d = camera_model(meta['intrinsics']['rgb'])
            factory_cross = project(obj, T_of(meta, 'ir1', 'rgb') @ poses['ir1'], rgb_K, rgb_d)
            row = dict(index=index, trial=folder.name,
                       factory_rgb_pose_reprojection_rms_px=rms(project(obj, poses['rgb'], rgb_K, rgb_d), obs['rgb']),
                       factory_ir1_to_rgb_reprojection_rms_px=rms(factory_cross, obs['rgb']))
            depth = np.load(str(folder / 'depth_native.npy'), allow_pickle=False)
            row['depth_vs_ir1_board'] = plane_metrics(depth, meta, T_of(meta, 'ir1', 'depth_native') @ poses['ir1'], obj)
            row['depth_vs_rgb_board'] = plane_metrics(depth, meta, T_of(meta, 'rgb', 'depth_native') @ poses['rgb'], obj)
            result['per_view'].append(row)
        n = len(paths)
        result['accepted_views'], result['view_names'] = n, paths
        result['factory_cross_sensor_reprojection_rms_px'] = distribution([r['factory_ir1_to_rgb_reprojection_rms_px'] for r in result['per_view']])
        if n:
            centers = np.array([x.mean(axis=0) for x in observations['rgb']])
            areas = np.array([cv2.contourArea(cv2.convexHull(x)) for x in observations['rgb']])
            normals = np.array([t[:3, 2] * (1 if t[2, 2] >= 0 else -1) for t in Ts])
            angles = np.degrees(np.arctan2(normals[:, :2], normals[:, 2, None]))
            spans = np.ptp(centers, axis=0)
            tilt = np.ptp(angles, axis=0)
            scale_ratio = float(np.sqrt(areas.max()/max(1., areas.min())))
            quality = dict(center_span_px=spans.tolist(), normal_angle_span_deg=tilt.tolist(),
                           apparent_linear_scale_ratio=scale_ratio,
                           criteria='Diagnostic sampling gates, not manufacturer accuracy tolerances',
                           sufficient=bool(n >= 20 and spans[0] >= 160 and spans[1] >= 120 and
                                           tilt[0] >= 15 and tilt[1] >= 15 and scale_ratio >= 1.4))
            result['view_diversity'] = quality
        if n >= 20 and result['view_diversity']['sufficient']:
            val = list(range(4, n, 5))
            train = [i for i in range(n) if i not in val]
            result['split'] = dict(train=train, holdout=val, rule='every fifth accepted view held out; no refitting on validation views')
            size = (meta['intrinsics']['rgb']['width'], meta['intrinsics']['rgb']['height'])
            for k in ('rgb', 'ir1', 'ir2'):
                available_train = [i for i in train if observations[k][i] is not None]
                available_val = [i for i in val if observations[k][i] is not None]
                if len(available_train) >= 12 and len(available_val) >= 3:
                    result['candidate_intrinsics'][k] = calibration(obj, observations[k], available_train, available_val, size, meta['intrinsics'][k])
            for src, dst in (('ir1', 'rgb'), ('ir1', 'ir2')):
                tr = [i for i in train if observations[src][i] is not None and observations[dst][i] is not None]
                va = [i for i in val if observations[src][i] is not None and observations[dst][i] is not None]
                if len(tr) >= 12 and len(va) >= 3:
                    result['candidate_extrinsics'][src + '_to_' + dst] = stereo_check(obj, observations[src], observations[dst], tr, va,
                                                                                   size, meta['intrinsics'][src], meta['intrinsics'][dst], T_of(meta, src, dst))
            if 'ir1_to_rgb' in result['candidate_extrinsics']:
                T = np.array(result['candidate_extrinsics']['ir1_to_rgb']['fitted_T_destination_from_source'])
                result['candidate_T_rgb_from_native_depth'] = (T @ np.linalg.inv(T_of(meta, 'ir1', 'depth_native'))).tolist()
                result['notes'].append('Candidate depth-to-color transform derives from fitted IR1-to-RGB plus factory depth-to-IR1; not an independent depth-system calibration.')
        else:
            result['notes'].append('Need at least 20 accepted stationary views with adequate center/tilt/scale diversity; no calibration fitted until sampling checks pass.')
        result['notes'] += [
            'No automatic physical pass/fail: assess held-out residuals, sampling coverage, board flatness and measurement uncertainty together.',
            'Reprojection residuals depend on corner detection, timing, board shape and PnP as well as calibration.',
            'Aligned depth retains native depth units/Z semantics; depth-plane metrics use original depth rays and rigid transforms, not a guessed color-Z convention.',
            'Black/white texture edges are not depth steps. Inspect physical board perimeter against a separated background; occlusion/zero depth is not automatically misalignment.',
            'All fitted parameters are diagnostic candidates only. Device calibration and historical capture K are unchanged.',
            'Camera-to-world/robot/hand-eye extrinsics need independent world or robot reference observations.']
        result['boundary_checks'] = []
        for path in sorted((a.input / 'boundary_checks').glob('*/boundary.json')):
            result['boundary_checks'].append(dict(path=str(path), sha256=sha(path),
                                                  result=json.loads(path.read_text(encoding='utf-8'))))
        result['software_alignment']['physical_boundary_observations'] = len(result['boundary_checks'])
        result['analysis_completed'] = True
    except Exception as e:
        result['error'] = dict(message=str(e), traceback=traceback.format_exc())
        result['analysis_completed'] = False
        code = 1
        traceback.print_exc()
    write_json(a.output / 'report.json', result)
    if result['per_view']:
        with (a.output / 'per_view.csv').open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['trial', 'factory_rgb_pose_reprojection_rms_px', 'factory_ir1_to_rgb_reprojection_rms_px',
                                              'native_depth_vs_ir_plane_z_bias_mm', 'native_depth_vs_rgb_plane_z_bias_mm'])
            w.writeheader()
            for r in result['per_view']:
                csv_row = {k: r.get(k) for k in w.fieldnames[:3]}
                csv_row.update({
                    'native_depth_vs_ir_plane_z_bias_mm': (r['depth_vs_ir1_board'].get('z_measured_minus_predicted_mm') or {}).get('median'),
                    'native_depth_vs_rgb_plane_z_bias_mm': (r['depth_vs_rgb_board'].get('z_measured_minus_predicted_mm') or {}).get('median')})
                w.writerow(csv_row)
    text = ['# D435i 棋盘格验证报告', '', '物理精度验收：未通过独立验收（不能由软件执行成功替代）。', '',
            '有效静态视角：%s；建议至少25–35张且覆盖画面边缘、距离及双轴倾角。' % result.get('accepted_views', 0), '',
            '## 软件对齐', '', '```json', json.dumps(result.get('software_alignment'), ensure_ascii=False, indent=2), '```', '',
            '## 结果与限制', '']
    emitter = result.get('capture_sensor_settings', {}).get('depth_options', {}).get('emitter_enabled')
    if emitter is not None:
        text += ['采集时投射器：' + ('关闭。这里的深度统计仅对应棋盘几何采集；生产开启投射器的深度和实体边缘另验。' if emitter == 0 else
                                      '开启/其他模式（SDK值%s）；完整设置见report.json。' % emitter), '']
    if result.get('factory_cross_sensor_reprojection_rms_px'):
        metric = result['factory_cross_sensor_reprojection_rms_px']
        text += ['原厂 IR1→RGB 跨传感器重投影：均值 %.3f px；95%% 分位 %.3f px（每帧角点RMS）。' % (metric['mean'], metric['p95']), '']
    if result.get('candidate_intrinsics'):
        text += ['|流|原厂验证集 RMS 均值(px)|候选验证集 RMS 均值(px)|fx变化(%)|fy变化(%)|', '|---|---:|---:|---:|---:|']
        for k, v in result['candidate_intrinsics'].items():
            text.append('|%s|%.3f|%.3f|%.3f|%.3f|' % (k, v['holdout_factory_rms_px']['mean'],
                        v['holdout_candidate_rms_px']['mean'], *v['relative_focal_change_percent']))
        text += ['', '候选仅在训练视角拟合，在独立验证视角上评估；未写入相机。', '']
    if result.get('candidate_extrinsics'):
        text += ['|传感器变换|原厂验证 RMS 均值(px)|候选验证 RMS 均值(px)|旋转差(度)|平移差(mm)|', '|---|---:|---:|---:|---:|']
        for k, v in result['candidate_extrinsics'].items():
            text.append('|%s|%.3f|%.3f|%.3f|%.3f|' % (k, v['holdout_factory_rms_px']['mean'],
                        v['holdout_candidate_rms_px']['mean'], v['rotation_difference_deg'], v['translation_difference_mm']))
        text += ['', '固定原厂内参的外参拟合也会吸收内参误差，不能把变化全部归因于外参。', '']
    if result.get('view_diversity'):
        text += ['采样覆盖条件：' + ('达到本工具的采样检查条件。' if result['view_diversity']['sufficient'] else
                                    '未满足数量/画面位置/双轴倾角/远近变化条件，需补拍。'), '']
    if result.get('boundary_checks'):
        text += ['已保存 %d 组人工实体板边界检查；各边偏移、匹配率和缺失样本见 report.json 及会话 boundary_checks/。' % len(result['boundary_checks']), '']
    text += ['- ' + s for s in result['notes']]
    text += ['', '完整参数、逐视角误差和候选内外参见 report.json；摘要见 per_view.csv。', '']
    (a.output / 'REPORT.md').write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps(dict(analysis_completed=result.get('analysis_completed'), accepted_views=result.get('accepted_views'),
                          physical_calibration_accepted=False, report=str(a.output / 'report.json')), ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
