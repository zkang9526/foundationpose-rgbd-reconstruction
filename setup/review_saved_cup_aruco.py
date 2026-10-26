#!/usr/bin/env python3
"""Review one ended live run: time bins, marker failures, motion consistency and source images."""
import argparse
import collections
import csv
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import cv2
import numpy as np
from cup_aruco_reference import rigid_error
from summarize_cup_aruco_session import stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--plot', action='store_true')
    p.add_argument('--condition-note', default='Human movement/occlusion conditions require user confirmation; no static phase is inferred')
    args = p.parse_args()
    session = args.session.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    host = json.loads((session / 'session.json').read_text())
    summary = json.loads((session / 'evaluation_summary/report.json').read_text())
    for name, digest in summary['evidence_sha256'].items():
        if hashlib.sha256((session / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Session evidence differs from completed summary: ' + name)
    events = [json.loads(line) for line in (session / 'frame_events.jsonl').read_text().splitlines()]
    if not events:
        raise ValueError('No recorded inference frames')
    mesh_to_obb = np.loadtxt(session / 'mesh_metric_to_obb.txt')
    center_in_mesh = np.linalg.inv(mesh_to_obb)[:, 3]
    reasons = collections.Counter()
    rows = []
    anchor_pose = anchor_marker = anchor_corners = None
    start = None
    for e in events:
        folder = session / 'frames' / e['frame']
        cap = json.loads((folder / 'capture.json').read_text())
        marker = json.loads((folder / 'aruco.json').read_text())
        stamp = datetime.datetime.fromisoformat(cap['received_utc'])
        error = e['reference_evaluation'].get('anchored_object_errors')
        if error is not None and anchor_pose is None:
            anchor_pose = np.array(e['pose'])
            anchor_marker = np.array(marker['pose_camera_from_marker'])
            anchor_corners = np.array(marker['corners_px'])
            start = stamp
        reasons[marker.get('reason', 'unknown')] += 1
        row = dict(frame=e['frame'], capture_utc=cap['received_utc'], timestamp=stamp.timestamp(),
                   operation=e['operation'], confirmed=e.get('pose_confirmed', False),
                   accepted=e.get('accepted_for_tracking', False), marker_found=marker.get('found', False),
                   marker_accepted=marker.get('reference_accepted', False),
                   marker_reason=marker.get('reason'), marker_min_edge_px=marker.get('min_edge_pixels'),
                   marker_reprojection_rms_px=marker.get('reprojection_rms_px'),
                   error=error, worker_seconds=e.get('worker_seconds'),
                   depth_valid_fraction=e.get('depth_quality', {}).get('valid_measured_fraction'),
                   depth_median_residual_m=e.get('depth_quality', {}).get('median_abs_depth_residual_m'),
                   pose=e.get('pose'), marker_pose=marker.get('pose_camera_from_marker'),
                   corners=marker.get('corners_px'))
        if anchor_pose is not None and e.get('passed'):
            row['fp_rotation_change_from_anchor_deg'] = rigid_error(np.array(e['pose']), anchor_pose)['rotation_error_deg']
            if row['marker_accepted']:
                row['marker_rotation_change_from_anchor_deg'] = rigid_error(np.array(marker['pose_camera_from_marker']), anchor_marker)['rotation_error_deg']
                row['corner_rms_from_anchor_px'] = float(np.sqrt(np.mean(np.sum((np.array(marker['corners_px'])-anchor_corners)**2, axis=1))))
        if error is not None:
            marker_from_mesh = np.linalg.inv(np.array(marker['pose_camera_from_marker'])) @ np.array(e['pose'])
            anchor_marker_from_mesh = np.linalg.inv(anchor_marker) @ anchor_pose
            direct_error = rigid_error(marker_from_mesh, anchor_marker_from_mesh)
            row['marker_from_mesh'] = marker_from_mesh.tolist()
            row['direct_relative_error'] = direct_error
            if abs(direct_error['translation_error_mm']-error['translation_error_mm']) > 1e-5 or abs(direct_error['rotation_error_deg']-error['rotation_error_deg']) > 1e-3:
                raise ValueError('Direct marker/object relative transform differs from anchored metric: ' + e['frame'])
            estimated_center = np.array(e['pose']) @ center_in_mesh
            reference_center = np.array(e['reference_evaluation']['anchored_reference_pose_camera_from_mesh']) @ center_in_mesh
            row['obb_center_translation_difference_mm'] = float(np.linalg.norm(estimated_center[:3]-reference_center[:3])*1000)
        rows.append(row)
    if start is None:
        start = datetime.datetime.fromisoformat(rows[0]['capture_utc'])
    for row in rows:
        row['seconds_from_anchor'] = row['timestamp'] - start.timestamp()
    paired = [r for r in rows if r['error'] is not None and r['frame'] != events[0]['reference_evaluation'].get('anchor_frame')]
    # The anchor may not be the first inference frame; exclude its constructed zero.
    anchor_frames = {e['reference_evaluation'].get('anchor_frame') for e in events}
    paired = [r for r in paired if r['frame'] not in anchor_frames]
    changed = [r for r in paired if r.get('corner_rms_from_anchor_px', 0) >= 5]
    relative_rows = [r for r in rows if r.get('marker_from_mesh') is not None]
    with (args.output / 'marker_cup_relative.csv').open('w', newline='', encoding='utf-8') as stream:
        fields = ('frame', 'capture_utc', 'seconds_from_anchor', 'marker_accepted', 'pose_confirmed',
                  'x_marker_mm', 'y_marker_mm', 'z_marker_mm', 'translation_change_mm', 'rotation_change_deg')
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for row in rows:
            value = dict(frame=row['frame'], capture_utc=row['capture_utc'], seconds_from_anchor=row['seconds_from_anchor'],
                         marker_accepted=row['marker_accepted'], pose_confirmed=row['confirmed'])
            if row.get('marker_from_mesh') is not None:
                value.update(zip(('x_marker_mm', 'y_marker_mm', 'z_marker_mm'), np.array(row['marker_from_mesh'])[:3,3]*1000))
                value.update(translation_change_mm=row['direct_relative_error']['translation_error_mm'], rotation_change_deg=row['direct_relative_error']['rotation_error_deg'])
            writer.writerow(value)
    if relative_rows:
        np.savez_compressed(args.output / 'marker_from_mesh_poses.npz', frames=np.array([r['frame'] for r in relative_rows]),
                            transforms=np.array([r['marker_from_mesh'] for r in relative_rows]))
    def errors(values):
        return dict(frames=len(values), translation_mm=stats([r['error']['translation_error_mm'] for r in values]),
                    rotation_deg=stats([r['error']['rotation_error_deg'] for r in values]),
                    obb_center_translation_mm=stats([r['obb_center_translation_difference_mm'] for r in values]))
    bins = []
    for begin in range(0, max(1, int(max(r['seconds_from_anchor'] for r in rows)) + 1), 30):
        attempted = [r for r in rows if begin <= r['seconds_from_anchor'] < begin + 30]
        valid = [r for r in paired if begin <= r['seconds_from_anchor'] < begin + 30]
        bins.append(dict(begin_seconds=begin, end_seconds=begin+30, attempted=len(attempted),
                         marker_accepted=sum(r['marker_accepted'] for r in attempted), **errors(valid)))
    blind = []; current = []
    for r in rows:
        if r['confirmed'] and not r['marker_accepted']:
            current.append(r)
        else:
            if current:
                blind.append(current)
                current = []
    if current:
        blind.append(current)
    blind_report = [dict(first_frame=v[0]['frame'], last_frame=v[-1]['frame'], count=len(v),
                         first_capture_utc=v[0]['capture_utc'], last_capture_utc=v[-1]['capture_utc'],
                         first_to_last_seconds=v[-1]['timestamp']-v[0]['timestamp']) for v in blind]
    selected = {rows[0]['frame'], rows[-1]['frame']}
    if paired:
        selected.add(paired[0]['frame'])
        for key in ('translation_error_mm', 'rotation_error_deg'):
            selected.add(max(paired, key=lambda r: r['error'][key])['frame'])
        for boundary in (10, 30, 60, 90, 120, 150, 180):
            selected.add(min(rows, key=lambda r: abs(r['seconds_from_anchor']-boundary))['frame'])
        for condition in (lambda r:r['error']['translation_error_mm']>50,
                          lambda r:r['error']['rotation_error_deg']>30):
            first = next((r for r in paired if condition(r)), None)
            if first:
                selected.add(first['frame'])
    for span in sorted(blind_report, key=lambda r:r['first_to_last_seconds'], reverse=True)[:2]:
        selected.add(span['first_frame']); selected.add(span['last_frame'])
    tail_start=max(r['seconds_from_anchor'] for r in rows)-30
    tail_low=[r for r in paired if r['seconds_from_anchor']>=tail_start and r.get('marker_rotation_change_from_anchor_deg', 180)<=10]
    tail_high=[r for r in paired if r['seconds_from_anchor']>=tail_start and r.get('marker_rotation_change_from_anchor_deg', 0)>20]
    if tail_low:
        selected.add(tail_low[len(tail_low)//2]['frame'])
    samples = []; tiles = []
    sample_dir = args.output / 'samples'; sample_dir.mkdir()
    for index, row in enumerate(rows):
        if row['frame'] not in selected:
            continue
        source = session / 'frames' / row['frame']; dest = sample_dir / row['frame']; dest.mkdir()
        rgb = np.load(source / 'rgb.npy', allow_pickle=False)
        cv2.imwrite(str(dest / 'rgb.png'), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        for name in ('overlay.jpg', 'aruco.json', 'capture.json', 'host_result.json', 'mask.png'):
            if (source / name).exists():
                shutil.copy2(source / name, dest / name)
        details = dict(row)
        if index:
            previous = rows[index-1]
            details['fp_change_from_previous'] = rigid_error(np.array(row['pose']), np.array(previous['pose']))
            if row['marker_accepted'] and previous['marker_accepted']:
                details['marker_change_from_previous'] = rigid_error(np.array(row['marker_pose']), np.array(previous['marker_pose']))
        samples.append(details)
        tile = np.full((275, 320, 3), 245, np.uint8)
        tile[35:] = cv2.resize(cv2.imread(str(dest / 'overlay.jpg')), (320, 240))
        text = f"{row['frame']} t={row['seconds_from_anchor']:.1f}s"
        if row['error']:
            text += f" {row['error']['translation_error_mm']:.0f}mm {row['error']['rotation_error_deg']:.0f}deg"
        else:
            text += ' no reference'
        cv2.putText(tile, text, (5, 22), cv2.FONT_HERSHEY_SIMPLEX, .39, (0,0,0), 1)
        tiles.append(tile)
    sheet = np.full(((len(tiles)+3)//4*275, 1280, 3), 235, np.uint8)
    for index, tile in enumerate(tiles):
        sheet[index//4*275:(index//4+1)*275, index%4*320:(index%4+1)*320] = tile
    cv2.imwrite(str(args.output / 'overlay_contact_sheet.jpg'), sheet)
    report = dict(passed=True, session=str(session), source=host['source'], settings=host['aruco'],
        first_anchor_capture_utc=start.isoformat(), last_capture_utc=rows[-1]['capture_utc'],
        tracking_capture_duration_seconds=rows[-1]['timestamp']-start.timestamp(),
        attempts=len(events), steady_processing_fps=host.get('steady_processing_fps'),
        operator_stop=host.get('stop_reason'), inference_failures=summary['inference_failed'],
        host_quality_rejected=host.get('quality_rejected_frames'), recovery_attempts=host.get('recovery_attempts'),
        rejections=[dict(frame=e['frame'], operation=e['operation'], drained=e.get('drained_after_stop'),
                         current_revision=e.get('state_revision_current'), gpu_consistent=e.get('tracking_consistent'))
                    for e in events if not e.get('accepted_for_tracking')],
        marker_reasons=dict(reasons), valid_reference_frames=summary['valid_reference_frames'],
        paired_relative_frames=summary['paired_relative_frames'], reference_coverage=summary['reference_coverage'],
        coverage_denominator='processed frames, not full wall time',
        whole_run=errors(paired), changed_view=errors(changed),
        changed_view_scope='same-marker corners RMS >=5px from anchor; image view change, not measured speed or GT',
        original_mesh_origin_to_obb_center_m=float(np.linalg.norm(center_in_mesh[:3])),
        obb_center_point_in_original_mesh_m=center_in_mesh[:3].tolist(),
        tail_reference_modes=dict(scope='Last 30 seconds split only by ArUco camera rotation from anchor; diagnostic subsets, not GT or replacement for full-run metrics',
                                  at_most_10deg=errors(tail_low), above_20deg=errors(tail_high)),
        thirty_second_bins=bins, reference_blind_spans=sorted(blind_report, key=lambda r:r['first_to_last_seconds'], reverse=True),
        marker_edge_pixels=stats([r['marker_min_edge_px'] for r in rows if r['marker_min_edge_px'] is not None]),
        depth_median_residual_mm=stats([r['depth_median_residual_m']*1000 for r in rows if r['depth_median_residual_m'] is not None]),
        thresholds={f'translation_above_{value}mm':sum(r['error']['translation_error_mm']>value for r in paired)/max(1,len(paired)) for value in (10,20,50,100)},
        relative_transform_definition='T_marker_from_original_mesh = inverse(T_camera_from_marker) @ T_camera_from_original_mesh; should be constant for fixed marker/object',
        direct_relative_transform_crosscheck_passed=True,
        maximum_translation_metric_difference_mm=max((abs(r['direct_relative_error']['translation_error_mm']-r['error']['translation_error_mm']) for r in relative_rows), default=0),
        maximum_rotation_metric_difference_deg=max((abs(r['direct_relative_error']['rotation_error_deg']-r['error']['rotation_error_deg']) for r in relative_rows), default=0),
        relative_transform_anchor=anchor_marker_from_mesh.tolist() if relative_rows else None,
        relative_translation_components_mm={axis:dict(mean=float(np.mean([r['marker_from_mesh'][i][3]*1000 for r in paired])),
            std=float(np.std([r['marker_from_mesh'][i][3]*1000 for r in paired])),
            min=float(np.min([r['marker_from_mesh'][i][3]*1000 for r in paired])),
            max=float(np.max([r['marker_from_mesh'][i][3]*1000 for r in paired]))) for i,axis in enumerate(('x','y','z'))} if paired else None,
        absolute_physical_accuracy_validated=False, reference_uncertainty_calibrated=False,
        user_conditions=args.condition_note,
        original_inputs_hash_verified=summary['input_files_sha256_verified'],
        summary_source_hashes_verified=len(summary['evidence_sha256']),
        source_summary_sha256=hashlib.sha256((session / 'evaluation_summary/report.json').read_bytes()).hexdigest(),
        source_evidence_sha256=summary['evidence_sha256'], selected_samples=samples)
    if args.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(3, 1, figsize=(10, 9), constrained_layout=True)
        for ax, key, title in ((axes[0], 'translation_error_mm', 'First-frame aligned translation difference (mm)'),
                                (axes[1], 'rotation_error_deg', 'First-frame aligned rotation difference (degrees)')):
            ax.plot([r['seconds_from_anchor'] for r in paired], [r['error'][key] for r in paired], '.', ms=2)
            ax.set_title(title); ax.grid(alpha=.3)
            for span in blind_report:
                left=datetime.datetime.fromisoformat(span['first_capture_utc']).timestamp()-start.timestamp()
                right=datetime.datetime.fromisoformat(span['last_capture_utc']).timestamp()-start.timestamp()
                ax.axvspan(left, right, color='gray', alpha=.15)
        confirmed = [r for r in rows if r['confirmed']]
        axes[2].plot([r['seconds_from_anchor'] for r in confirmed], [r.get('fp_rotation_change_from_anchor_deg', np.nan) for r in confirmed], label='FoundationPose camera rotation from anchor', lw=.8)
        referenced = [r for r in rows if r.get('marker_rotation_change_from_anchor_deg') is not None]
        axes[2].plot([r['seconds_from_anchor'] for r in referenced], [r['marker_rotation_change_from_anchor_deg'] for r in referenced], '.', ms=1, label='ArUco camera rotation from anchor')
        axes[2].set_ylabel('degrees'); axes[2].set_xlabel('seconds from anchor'); axes[2].grid(alpha=.3); axes[2].legend(fontsize=8)
        fig.suptitle('Actual live run | relative consistency, no absolute object GT\nGray spans: tracking has no accepted ArUco reference')
        fig.savefig(args.output / 'run_errors_and_rotation.png', dpi=160); plt.close(fig)
        if relative_rows:
            fig, axes = plt.subplots(2, 1, figsize=(10, 6), constrained_layout=True)
            relative_t = [r['seconds_from_anchor'] for r in relative_rows]
            translations = np.array([r['marker_from_mesh'] for r in relative_rows])[:,:3,3]*1000
            for i,axis in enumerate(('x','y','z')):
                axes[0].plot(relative_t, translations[:,i]-translations[0,i], '.', ms=2, label=axis+' in marker frame')
            axes[0].set_ylabel('position change from anchor (mm)'); axes[0].legend(fontsize=8)
            axes[1].plot(relative_t, [r['direct_relative_error']['rotation_error_deg'] for r in relative_rows], '.', ms=2)
            axes[1].set_ylabel('relative orientation change (degrees)'); axes[1].set_xlabel('seconds from anchor')
            for ax in axes:
                ax.grid(alpha=.3)
            fig.suptitle('Fixed marker + cup: inverse(T_camera_marker) @ T_camera_mesh should be constant\nMeasured relative stability; not absolute object ground truth')
            fig.savefig(args.output / 'marker_cup_relative_stability.png', dpi=160); plt.close(fig)
    source_dir = args.output / 'analysis_source'; source_dir.mkdir()
    for name in (Path(__file__).name, 'cup_aruco_reference.py', 'summarize_cup_aruco_session.py'):
        shutil.copy2(Path(__file__).parent / name, source_dir / name)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    manifest={path.relative_to(args.output).as_posix():dict(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in args.output.rglob('*') if path.is_file()}
    (args.output / 'SHA256SUMS.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('selected_samples','reference_blind_spans')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
