"""Read-only depth-plane diagnostics for saved projector-ON board snapshots.

Uses the session's verified source snapshot for plane_metrics and geometry.
Snapshot trials may be accepted=False by design; no acceptance flag is changed.
"""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import numpy as np


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_child(parent, name):
    p = (parent / name).resolve()
    if not p.is_relative_to(parent.resolve()):
        raise ValueError('Manifest path outside source directory')
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-emitter-off', action='store_true',
                        help='Explicit independent OFF snapshot diagnostic; does not validate production ON depth')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    src = args.input / 'source'
    manifest = load(args.input / 'source_manifest.json')
    source_verified = []
    for entry in manifest['files']:
        path = checked_child(src, entry['name'])
        if not path.is_file() or digest(path) != entry['sha256']:
            raise ValueError('Captured source snapshot mismatch: ' + entry['name'])
        if 'bytes' in entry and path.stat().st_size != entry['bytes']:
            raise ValueError('Captured source byte count mismatch')
        source_verified.append(dict(name=entry['name'], sha256=digest(path)))
    names = {entry['name'] for entry in source_verified}
    if not {'analyze.py', 'common.py'} <= names:
        raise ValueError('Missing saved plane-metric source')
    sys.path.insert(0, str(src.resolve()))
    # Import the immutable session copy, not the mutable project analyze.py.
    for name in ('common', 'analyze'):
        if name in sys.modules:
            raise ValueError('Unexpected pre-imported shared geometry module')
    spec = importlib.util.spec_from_file_location('saved_active_depth_analysis', src / 'analyze.py')
    analysis_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analysis_module)
    common = sys.modules['common']
    if Path(common.__file__).resolve() != (src / 'common.py').resolve():
        raise ValueError('Wrong geometry module imported')
    output_source = args.output / 'source'
    output_source.mkdir()
    for original in [Path(__file__), src / 'analyze.py', src / 'common.py']:
        shutil.copy2(original, output_source / original.name)
    meta, session = load(args.input / 'factory.json'), load(args.input / 'session.json')
    if session.get('status') != 'finished' or not session.get('pipeline_stopped'):
        raise ValueError('Input session has not ended normally')
    if any(meta['board'][k] != session['board'][k] for k in ('rows', 'cols', 'square_mm')):
        raise ValueError('Factory/session board parameters differ')
    if not np.isfinite(meta['depth_scale_m']) or meta['depth_scale_m'] <= 0:
        raise ValueError('Invalid source depth scale')
    emitter = meta.get('depth_options', {}).get('emitter_enabled')
    session_emitter = session.get('active_emitter_enabled')
    if emitter != session_emitter or emitter not in (0, 1):
        raise ValueError('Factory/session emitter state missing, inconsistent or unsupported')
    if emitter == 0 and not args.allow_emitter_off:
        raise ValueError('OFF snapshot requires explicit --allow-emitter-off')
    source_evidence = []
    for name in ('factory.json', 'session.json', 'source_manifest.json', 'events.jsonl',
                 'sensor_settings_before.json', 'sensor_settings_after_restore.json',
                 'K_color.txt', 'K_native_depth.txt'):
        p = args.input / name
        if p.is_file():
            source_evidence.append(dict(name=name, bytes=p.stat().st_size, sha256=digest(p)))
    obj = common.board_points(meta['board'])
    report = dict(
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        input=str(args.input.resolve()), device=meta['device'], board=meta['board'],
        depth_scale_m=meta['depth_scale_m'], saved_profiles=meta['intrinsics'],
        projector_scope='projector_ON_snapshot' if emitter == 1 else 'projector_OFF_independent_snapshot',
        physical_calibration_accepted=False,
        absolute_depth_accuracy_accepted=False, production_depth_accepted=False,
        source_trials_modified=False, camera_calibration_parameters_fitted=False,
        board_pose_estimated_from_saved_corners=True,
        executed_tool_sha256=digest(__file__), captured_source_files_verified=source_verified,
        source_evidence=source_evidence,
        geometry_implementation=dict(analyze_sha256=digest(src / 'analyze.py'),
                                     common_sha256=digest(src / 'common.py')),
        capture_state=dict(session_status=session['status'], pipeline_stopped=session['pipeline_stopped'],
                           emitter_factory=emitter, emitter_session=session_emitter,
                           depth_options=meta.get('depth_options'), emitter_control=meta.get('emitter_control'),
                           frames_received=session.get('frames_received')),
        assumptions=[
            'Saved snapshot accepted=False is retained; snapshot is intentionally excluded from multiview calibration.',
            'Snapshot has no temporal stationarity validation; measured stream time difference is not proof of temporal stability.',
            'RGB board points plus factory RGB K/distortion and factory RGB-to-native-depth transform define a comparison plane.',
            'The RGB board plane uses the reported 20 mm grid and a planar-board assumption; this is not an independent depth ground truth.',
            'Raw native depth is used with its native rays and recorded scale; aligned-depth Z is not treated as RGB-camera Z.',
            'plane_metrics uses the inner-corner hull eroded by 9x9 pixels; zeros are excluded. Best-fit plane residual is iteratively trimmed, and retained fraction is reported.',
            'Any detectable IR board is supplemental; IR detection is not required with the projector ON.',
            'Single-frame depth ratios, biases and plane residuals do not establish absolute millimeter accuracy or multi-frame repeatability.',
            'Results are confined to the board ROI and recorded settings; no conclusion about the painted cup, reconstruction readiness or full-frame depth quality is made.',
            'Source checks verify saved evidence integrity, not sensor calibration accuracy.'], trials=[])
    if emitter == 0:
        report['assumptions'].append('This explicitly allowed projector-OFF snapshot is an independent geometry diagnostic; it does not establish projector-ON production depth performance.')
    frame_verified = 0
    for folder in sorted((args.input / 'trials').iterdir()):
        trial_path = folder / 'trial.json'
        if not trial_path.is_file():
            continue
        trial = load(trial_path)
        files = []
        for entry in trial['files']:
            path = checked_child(folder, entry['name'])
            if not path.is_file() or digest(path) != entry['sha256']:
                raise ValueError('Trial file SHA mismatch: ' + str(path))
            if 'bytes' in entry and path.stat().st_size != entry['bytes']:
                raise ValueError('Trial file byte count mismatch')
            files.append(dict(name=entry['name'], sha256=digest(path)))
            frame_verified += 1
        depth = np.load(folder / 'depth_native.npy', allow_pickle=False)
        rgb = np.load(folder / 'rgb.npy', allow_pickle=False)
        dm, cm = meta['intrinsics']['depth_native'], meta['intrinsics']['rgb']
        if depth.dtype != np.uint16 or depth.shape != (dm['height'], dm['width']):
            raise ValueError('Native depth shape or dtype mismatch')
        if rgb.dtype != np.uint8 or rgb.shape != (cm['height'], cm['width'], 3):
            raise ValueError('RGB shape or dtype mismatch')
        streams = trial['metadata']['streams']
        domains = [item['timestamp_domain'] for item in streams.values()]
        comparable = len(set(domains)) == 1
        stamps = [float(item['sdk_timestamp_ms']) for item in streams.values()]
        if not np.isfinite(stamps).all():
            raise ValueError('Nonfinite recorded timestamp')
        timestamp = dict(domains_match=comparable, recorded_streams=streams,
                         computed_sdk_stream_span_ms=max(stamps)-min(stamps) if comparable else None,
                         native_depth_minus_rgb_ms=(float(streams['depth_native']['sdk_timestamp_ms'])-
                                                   float(streams['rgb']['sdk_timestamp_ms'])) if comparable else None,
                         trial_recorded_timestamp_span_ms=trial.get('timestamp_span_ms'),
                         selected_frame_age_s=trial['metadata'].get('selected_frame_age_s'),
                         host_utc=trial['metadata'].get('host_utc'))
        row = dict(trial=folder.name, original_accepted=trial['accepted'], original_reasons=trial['reasons'],
                   trial_json_sha256=digest(trial_path), files_verified=files, metadata=trial['metadata'],
                   stationarity_verified=False,
                   saved_stationarity_interval_s=trial.get('stationarity_interval_s'),
                   saved_stationarity_motion_p95_px=trial.get('stationarity_motion_p95_px'),
                   timestamp=timestamp, depth_native_dtype=str(depth.dtype), depth_native_shape=list(depth.shape),
                   rgb_board_detected=trial['corners'].get('rgb') is not None,
                   depth_vs_factory_board={}, supplemental_ir={})
        for camera in ('rgb', 'ir1', 'ir2'):
            key = 'rgb' if camera == 'rgb' else camera + '_ordered'
            saved = trial['corners'].get(key)
            if saved is None and camera != 'rgb':
                saved = trial['corners'].get(camera)
            if saved is None:
                if camera != 'rgb':
                    row['supplemental_ir'][camera] = dict(detected=False)
                continue
            corners = np.asarray(saved, np.float32)
            if corners.shape != (len(obj), 2) or not np.isfinite(corners).all():
                raise ValueError('Saved board corner shape mismatch')
            K, d = common.camera_model(meta['intrinsics'][camera])
            T = common.pose(obj, corners, K, d)
            if camera + '_to_depth_native' in meta['extrinsics']:
                camera_to_depth = analysis_module.T_of(meta, camera, 'depth_native')
            else:
                camera_to_depth = (analysis_module.T_of(meta, 'rgb', 'depth_native') @
                                   analysis_module.T_of(meta, camera, 'rgb'))
            Td = camera_to_depth @ T
            metric = analysis_module.plane_metrics(depth, meta, Td, obj)
            row['depth_vs_factory_board'][camera] = dict(
                board_to_camera_T=T.tolist(),
                board_to_native_depth_T=Td.tolist(),
                factory_board_reprojection_rms_px=common.rms(common.project(obj, T, K, d), corners),
                estimated_board_center_z_m=float((obj.mean(axis=0) @ T[:3, :3].T + T[:3, 3])[2]),
                native_depth_plane_metrics=metric)
            if camera != 'rgb':
                row['supplemental_ir'][camera] = dict(detected=True, ordered_saved=trial['corners'].get(key) is not None)
        ordered1, ordered2 = trial['corners'].get('ir1_ordered'), trial['corners'].get('ir2_ordered')
        if ordered1 is not None and ordered2 is not None:
            dy = np.asarray(ordered2, dtype=float)[:, 1] - np.asarray(ordered1, dtype=float)[:, 1]
            row['ir1_to_ir2_raw_dy'] = dict(
                definition='y_IR2 - y_IR1 from saved ordered raw image corners, pixels; no PnP, plane or grid size',
                signed=common.distribution(dy), absolute=common.distribution(np.abs(dy)),
                per_corner_dy_px=dy.tolist(),
                limitation='Saved correspondence ordering uses discrete factory board-symmetry selection; corner noise and image geometry remain possible contributors.')
        else:
            row['ir1_to_ir2_raw_dy'] = dict(available=False, reason='Both saved ordered IR corner sets required; no new detection or ordering performed')
        raw1, raw2 = trial['corners'].get('ir1'), trial['corners'].get('ir2')
        if raw1 is not None and raw2 is not None:
            raw1, raw2 = np.asarray(raw1, dtype=float), np.asarray(raw2, dtype=float)
            if raw1.shape != raw2.shape:
                raise ValueError('Raw IR corner count mismatch')
            row['ir_raw_centroid_and_unresolved_order'] = dict(
                centroid_dy_px=float(raw2[:, 1].mean() - raw1[:, 1].mean()),
                centroid_definition='mean(raw y_IR2) - mean(raw y_IR1); independent of corner-list order, no PnP or board plane',
                same_list_order_dy=common.distribution(raw2[:, 1] - raw1[:, 1]),
                reversed_IR2_list_dy=common.distribution(raw2[::-1, 1] - raw1[:, 1]),
                same_list_order_abs_dy=common.distribution(np.abs(raw2[:, 1] - raw1[:, 1])),
                reversed_IR2_list_abs_dy=common.distribution(np.abs(raw2[::-1, 1] - raw1[:, 1])),
                correspondence_status='Raw list orders are not newly accepted as physical correspondence; both possible rectangular-board 180-degree orders shown without selecting one.')
        row['diagnostic_status'] = ('rgb_board_plane_available' if 'rgb' in row['depth_vs_factory_board']
                                    else 'no_saved_rgb_board_corners_primary_plane_unavailable')
        report['trials'].append(row)
    report['original_frame_files_verified'] = frame_verified
    report['trials_reviewed'] = len(report['trials'])
    if report['trials_reviewed'] != session['trials']:
        raise ValueError('Session/trial count mismatch')
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    lines = ['# Saved projector-%s board snapshot diagnostic' % ('ON' if emitter == 1 else 'OFF'), '',
             'Single-frame diagnostic only: no temporal stationarity verification or independent physical accuracy acceptance.', '',
             '|Trial|Plane reference|ROI valid|Z bias median (mm)|Trimmed depth-plane RMS (mm)|Retained fraction|RGB/depth time gap (ms)|',
             '|---|---|---:|---:|---:|---:|---:|']
    summary = []
    for row in report['trials']:
        if 'rgb' not in row['depth_vs_factory_board']:
            gap = row['timestamp']['native_depth_minus_rgb_ms']
            lines.append('|%s|RGB unavailable: no saved board corners|n/a|n/a|n/a|n/a|%s|' %
                         (row['trial'], 'n/a' if gap is None else '%.3f' % gap))
            summary.append(dict(trial=row['trial'], reference='rgb', emitter=emitter,
                                diagnostic_status=row['diagnostic_status'], valid_fraction=None,
                                z_bias_median_mm=None, trimmed_plane_rms_mm=None,
                                depth_minus_rgb_ms=gap, stationarity_verified=False))
        for camera, value in row['depth_vs_factory_board'].items():
            pm = value['native_depth_plane_metrics']
            bias = pm.get('z_measured_minus_predicted_mm', {}).get('median')
            residual = pm.get('depth_best_fit_plane_residual_mm', {}).get('rms')
            retained = pm.get('depth_best_fit_retained_fraction')
            gap = row['timestamp']['native_depth_minus_rgb_ms']
            lines.append('|%s|%s|%.2f%%|%s|%s|%s|%s|' % (
                row['trial'], camera, pm['valid_fraction']*100,
                'n/a' if bias is None else '%.3f' % bias,
                'n/a' if residual is None else '%.3f' % residual,
                'n/a' if retained is None else '%.3f' % retained,
                'n/a' if gap is None else '%.3f' % gap))
            summary.append(dict(trial=row['trial'], reference=camera, emitter=emitter,
                                valid_fraction=pm['valid_fraction'], z_bias_median_mm=bias,
                                trimmed_plane_rms_mm=residual, retained_fraction=retained,
                                depth_minus_rgb_ms=gap, stationarity_verified=False))
    for row in report['trials']:
        dy = row['ir1_to_ir2_raw_dy']
        if 'signed' in dy:
            lines += ['', 'Trial %s saved ordered IR2-IR1 raw dy mean %.4f px; median %.4f px; absolute P95 %.4f px.' %
                      (row['trial'], dy['signed']['mean'], dy['signed']['median'], dy['absolute']['p95'])]
        raw = row.get('ir_raw_centroid_and_unresolved_order')
        if raw is not None:
            lines += ['', 'Trial %s raw IR2-IR1 y-centroid difference %.4f px (independent of list ordering; not a physical accuracy acceptance).' %
                      (row['trial'], raw['centroid_dy_px'])]
    lines += ['', '## Limits', ''] + ['- '+line for line in report['assumptions']]
    (args.output / 'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    outputs = [dict(name=str(path.relative_to(args.output)), sha256=digest(path))
               for path in sorted(args.output.rglob('*')) if path.is_file()]
    (args.output / 'manifest.json').write_text(json.dumps(dict(files=outputs), indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(args.output.resolve()), snapshot_source_files_verified=len(source_verified),
                         original_frame_files_verified=frame_verified, summary=summary,
                         ir_raw_dy=[dict(trial=r['trial'], value=r['ir1_to_ir2_raw_dy'],
                                         raw_centroid_and_unresolved_orders=r.get('ir_raw_centroid_and_unresolved_order'))
                                    for r in report['trials']]), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
