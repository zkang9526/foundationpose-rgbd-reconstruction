#!/usr/bin/env python3
"""Compare saved static marker/FP variation and whole-run drift; no absolute accuracy claim."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import collections
import numpy as np
import cv2
from cup_aruco_reference import rigid_error
from summarize_cup_aruco_session import stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--static-last-frame', required=True, help='Confirmed stationary status snapshot frame, inclusive')
    p.add_argument('--plot', action='store_true')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    session = args.session.resolve(strict=True)
    events = [json.loads(line) for line in (session / 'frame_events.jsonl').read_text().splitlines()]
    summary = json.loads((session / 'evaluation_summary/report.json').read_text())
    marker_first = pose_first = corners_first = None
    marker_variation, pose_variation, static_errors, corner_changes, timestamps = [], [], [], [], []
    reasons = collections.Counter()
    for event in events:
        folder = session / 'frames' / event['frame']
        marker = json.loads((folder / 'aruco.json').read_text())
        reasons[marker.get('reason', 'unknown')] += 1
        if event['frame'] > args.static_last_frame or not event.get('pose_confirmed'):
            continue
        capture = json.loads((folder / 'capture.json').read_text())
        timestamps.append(capture['received_utc'])
        current_pose = np.array(event['pose'])
        if pose_first is None:
            pose_first = current_pose
        pose_variation.append(rigid_error(current_pose, pose_first))
        if marker.get('reference_accepted'):
            current_marker = np.array(marker['pose_camera_from_marker'])
            corners = np.array(marker['corners_px'])
            if marker_first is None:
                marker_first, corners_first = current_marker, corners
            marker_variation.append(rigid_error(current_marker, marker_first))
            corner_changes.append(float(np.sqrt(np.mean(np.sum((corners - corners_first)**2, axis=1)))))
        if event['reference_evaluation'].get('anchored_object_errors') is not None:
            static_errors.append(event['reference_evaluation']['anchored_object_errors'])
    def variation(values):
        # Exclude the first sample, zero by construction.
        return dict(translation_mm=stats([v['translation_error_mm'] for v in values[1:]]),
                    rotation_deg=stats([v['rotation_error_deg'] for v in values[1:]]))
    result = dict(passed=True, source='actual live D435i session', session=str(session),
        marker_id=6, measured_black_side_m=.030, dictionary='DICT_5X5_50',
        scope='first-frame aligned drift, plus requested stationary baseline; no absolute object GT',
        static_condition='User confirmed camera stationary before initialization and was instructed to remain still until later movement request; physical motion not independently instrumented',
        static_last_frame=args.static_last_frame, static_first_capture_utc=timestamps[0] if timestamps else None,
        static_last_capture_utc=timestamps[-1] if timestamps else None,
        static_duration_seconds=(datetime.datetime.fromisoformat(timestamps[-1])-datetime.datetime.fromisoformat(timestamps[0])).total_seconds() if len(timestamps)>1 else 0,
        static_confirmed_pose_frames=len(pose_variation), static_valid_marker_frames=len(marker_variation),
        static_marker_raw_pose_change=variation(marker_variation), static_fp_raw_pose_change=variation(pose_variation),
        static_marker_corner_change_rms_px=stats(corner_changes[1:]),
        static_anchored_object_errors=variation(static_errors),
        marker_reasons=dict(reasons),
        completed_attempts=len(events), inference_failed=summary['inference_failed'],
        tracking_rejected=summary['tracking_consistency_rejected'],
        reference_coverage=summary['reference_coverage'], paired_relative_frames=summary['paired_relative_frames'],
        steady_processing_fps=summary['steady_processing_fps'],
        whole_run_anchored_translation_mm=summary['anchored_object_translation_mm'],
        whole_run_anchored_rotation_deg=summary['anchored_object_rotation_deg'],
        absolute_physical_accuracy_validated=False, reference_uncertainty_calibrated=False,
        whole_run_includes_all_conditions=True,
        input_hash_verification_count=summary['input_files_sha256_verified'],
        evidence_sha256={name: hashlib.sha256((session / name).read_bytes()).hexdigest()
                        for name in ('session.json', 'frame_events.jsonl', 'aruco_errors.csv', 'evaluation_summary/report.json')})
    result['tracking_rejections'] = [dict(frame=e['frame'], operation=e['operation'],
        drained_after_stop=e.get('drained_after_stop'), state_revision_current=e.get('state_revision_current'),
        gpu_tracking_consistent=e.get('tracking_consistent'), depth_quality=e.get('depth_quality'),
        initialization_marker_movement_check=e.get('initialization_marker_movement_check'))
        for e in events if not e.get('accepted_for_tracking')]
    host = json.loads((session / 'session.json').read_text())
    result['recovery_attempts'] = host.get('recovery_attempts')
    last_capture = json.loads((session / 'frames' / events[-1]['frame'] / 'capture.json').read_text())
    result['last_processed_capture_utc'] = last_capture['received_utc']
    result['session_ended_utc'] = host['ended_utc']
    result['seconds_after_last_processed_capture_until_end'] = (datetime.datetime.fromisoformat(host['ended_utc']) - datetime.datetime.fromisoformat(last_capture['received_utc'])).total_seconds()
    result['reference_coverage_denominator'] = 'processed frames only; excludes camera frames during search/no pose'
    result['worst_frames'] = []
    candidates = [e for e in events if e['reference_evaluation'].get('anchored_object_errors') is not None]
    anchor_corners = np.array(json.loads((session / 'frames' / candidates[0]['frame'] / 'aruco.json').read_text())['corners_px']) if candidates else None
    changed_view = []
    for e in candidates:
        marker = json.loads((session / 'frames' / e['frame'] / 'aruco.json').read_text())
        rms = float(np.sqrt(np.mean(np.sum((np.array(marker['corners_px']) - anchor_corners)**2, axis=1))))
        if rms >= 5:
            capture = json.loads((session / 'frames' / e['frame'] / 'capture.json').read_text())
            changed_view.append(dict(frame=e['frame'], capture_utc=capture['received_utc'], corner_change_rms_px=rms,
                                     **e['reference_evaluation']['anchored_object_errors']))
    result['changed_view_scope'] = 'Heuristic: same-marker corners RMS >=5px from anchor; view change, not measured camera speed or planned motion phase'
    result['changed_view_paired_frames'] = len(changed_view)
    result['changed_view_first_capture_utc'] = changed_view[0]['capture_utc'] if changed_view else None
    result['changed_view_last_capture_utc'] = changed_view[-1]['capture_utc'] if changed_view else None
    result['changed_view_translation_mm'] = stats([v['translation_error_mm'] for v in changed_view])
    result['changed_view_rotation_deg'] = stats([v['rotation_error_deg'] for v in changed_view])
    worst = sorted(candidates, key=lambda e: e['reference_evaluation']['anchored_object_errors']['translation_error_mm'], reverse=True)[:5]
    selected = set(e['frame'] for e in worst)
    selected.update((events[0]['frame'], args.static_last_frame, events[-1]['frame']))
    for e in worst:
        selected.update(f'{max(0, int(e["frame"])+delta):06d}' for delta in (-1, 1))
    for e in events:
        if e['frame'] not in selected:
            continue
        source = session / 'frames' / e['frame']
        folder = args.output / e['frame']; folder.mkdir()
        rgb = np.load(source / 'rgb.npy', allow_pickle=False)
        cv2.imwrite(str(folder / 'rgb.png'), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        for name in ('overlay.jpg', 'aruco.json', 'capture.json', 'host_result.json'):
            (folder / name).write_bytes((source / name).read_bytes())
        marker = json.loads((source / 'aruco.json').read_text())
        details = dict(frame=e['frame'], error=e['reference_evaluation'].get('anchored_object_errors'),
            depth_quality=e.get('depth_quality'), pose=e['pose'], marker=marker)
        previous = next((v for v in events if int(v['frame']) == int(e['frame'])-1), None)
        if previous and previous.get('passed') and marker.get('reference_accepted'):
            prev_marker = json.loads((session / 'frames' / previous['frame'] / 'aruco.json').read_text())
            details['fp_pose_change_from_previous'] = rigid_error(np.array(e['pose']), np.array(previous['pose']))
            if prev_marker.get('reference_accepted'):
                details['marker_pose_change_from_previous'] = rigid_error(np.array(marker['pose_camera_from_marker']), np.array(prev_marker['pose_camera_from_marker']))
                details['marker_corner_change_from_previous_rms_px'] = float(np.sqrt(np.mean(np.sum((np.array(marker['corners_px'])-np.array(prev_marker['corners_px']))**2, axis=1))))
        result['worst_frames'].append(details)
    if args.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
        paired = [(e, e['reference_evaluation']['anchored_object_errors']) for e in candidates]
        start = datetime.datetime.fromisoformat(json.loads((session / 'frames' / paired[0][0]['frame'] / 'capture.json').read_text())['received_utc'])
        times = [(datetime.datetime.fromisoformat(json.loads((session / 'frames' / e['frame'] / 'capture.json').read_text())['received_utc']) - start).total_seconds() for e, _ in paired]
        last_t = (datetime.datetime.fromisoformat(last_capture['received_utc']) - start).total_seconds()
        end_t = (datetime.datetime.fromisoformat(host['ended_utc']) - start).total_seconds()
        for ax, key, label in ((axes[0, 0], 'translation_error_mm', 'First-frame aligned drift (mm)'),
                               (axes[0, 1], 'rotation_error_deg', 'First-frame aligned rotation difference (deg)')):
            ax.plot(times, [v[key] for _, v in paired], lw=.8)
            ax.axvspan(last_t, end_t, color='gray', alpha=.2, label='search; no confirmed pose')
            ax.set_title(label); ax.set_xlabel('seconds from anchor'); ax.grid(alpha=.3); ax.legend(fontsize=8)
        for ax, key, label in ((axes[1, 0], 'translation_error_mm', 'Static change from first sample (mm)'),
                               (axes[1, 1], 'rotation_error_deg', 'Static change from first sample (deg)')):
            ax.plot([v[key] for v in marker_variation], label='ArUco reference', lw=.8)
            ax.plot([v[key] for v in pose_variation], label='FoundationPose estimate', lw=.8)
            ax.set_title(label); ax.set_xlabel('static sample'); ax.grid(alpha=.3); ax.legend(fontsize=8)
        fig.suptitle('ID6, black side 30 mm | relative consistency only; no absolute object GT')
        fig.savefig(args.output / 'relative_drift_and_static_variation.png', dpi=160)
        plt.close(fig)
    (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    manifest = {path.relative_to(args.output).as_posix(): dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                for path in args.output.rglob('*') if path.is_file()}
    (args.output / 'SHA256SUMS.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'worst_frames'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
