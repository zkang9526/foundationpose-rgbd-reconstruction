#!/usr/bin/env python3
"""Summarize all attempts, reference coverage, same-frame relative errors and latency."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def stats(values):
    values = np.asarray(values, float)
    return dict(count=len(values), mean=float(np.mean(values)), rmse=float(np.sqrt(np.mean(values ** 2))),
                median=float(np.median(values)), p95=float(np.percentile(values, 95)), max=float(np.max(values))) if len(values) else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--plot', action='store_true', help='Optional matplotlib export; no environment is installed by this script')
    args = p.parse_args()
    session = args.session.resolve(strict=True); args.output.mkdir(parents=True, exist_ok=False)
    host = json.loads((session / 'session.json').read_text())
    events = [json.loads(line) for line in (session / 'frame_events.jsonl').read_text().splitlines()]
    reference_valid = 0
    inputs_verified = 0
    relative, anchored, absolute, reference_jitter = [], [], [], []
    first_marker = None
    from cup_aruco_reference import rigid_error
    for event in events:
        folder = session / 'frames' / event['frame']
        request = json.loads((session / 'requests' / (event['frame'] + '.json')).read_text())
        for name, digest in request['input_sha256'].items():
            if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Input evidence changed: ' + str(folder / name))
            inputs_verified += 1
        if event['passed']:
            if hashlib.sha256((folder / 'pose_camera_from_mesh.txt').read_bytes()).hexdigest() != event['pose_sha256']:
                raise ValueError('Pose evidence changed: ' + event['frame'])
        marker = json.loads((folder / 'aruco.json').read_text())
        if marker.get('reference_accepted'):
            reference_valid += 1
            current = np.array(marker['pose_camera_from_marker'])
            if first_marker is None:
                first_marker = current
            reference_jitter.append(dict(frame=event['frame'], **rigid_error(current, first_marker)))
        evaluation = event['reference_evaluation']
        for kind, target in (('relative', relative), ('anchored_object', anchored), ('absolute', absolute)):
            if evaluation.get(kind + '_errors') is not None:
                target.append(dict(frame=event['frame'], anchor_frame=evaluation.get('anchor_frame'), **evaluation[kind + '_errors']))
    # Anchor relative error is zero by construction; exclude it from stats.
    relative_nonanchor = [row for row in relative if row['frame'] != row['anchor_frame']]
    report = dict(passed=True, session=str(session), source=host['source'], attempts=len(events),
                  inference_failed=sum(not e['passed'] for e in events),
                  tracking_consistency_rejected=sum(e['passed'] and not e['accepted_for_tracking'] for e in events),
                  valid_reference_frames=reference_valid, reference_coverage=reference_valid / max(1, len(events)),
                  paired_relative_frames=len(relative), paired_absolute_frames=len(absolute),
                  paired_relative_coverage=len(relative) / max(1, len(events)),
                  relative_scope='camera motion consistency for rigidly fixed cup and marker; constant object-frame bias cancels',
                  anchored_object_scope='object-origin drift relative to FIRST estimated pose; removes initial bias, not absolute object accuracy',
                  reference_uncertainty_measured=False, absolute_physical_accuracy_validated=False,
                  reference_raw_change_scope='Only interpret as ArUco jitter when camera AND cup AND marker are static; during motion this is actual camera change',
                  reference_raw_changes=reference_jitter,
                  relative_translation_mm=stats([v['translation_error_mm'] for v in relative_nonanchor]),
                  relative_rotation_deg=stats([v['rotation_error_deg'] for v in relative_nonanchor]),
                  anchored_object_translation_mm=stats([v['translation_error_mm'] for v in anchored if v['frame'] != v['anchor_frame']]),
                  anchored_object_rotation_deg=stats([v['rotation_error_deg'] for v in anchored if v['frame'] != v['anchor_frame']]),
                  absolute_translation_mm=stats([v['translation_error_mm'] for v in absolute]),
                  absolute_rotation_deg=stats([v['rotation_error_deg'] for v in absolute]),
                  steady_processing_fps=host.get('steady_processing_fps'),
                  latency_all_ms=stats([e['host_receive_to_result_seconds'] * 1000 for e in events]),
                  latency_tracking_ms=stats([e['host_receive_to_result_seconds'] * 1000 for e in events if e['operation'] == 'track']),
                  input_files_sha256_verified=inputs_verified, settings=host['aruco'],
                  relative_errors=relative, anchored_object_errors=anchored, absolute_errors=absolute)
    report['evidence_sha256'] = {name: hashlib.sha256((session / name).read_bytes()).hexdigest()
                               for name in ('session.json', 'frame_events.jsonl', 'aruco_errors.csv', 'worker_report.json', 'K.txt')}
    if args.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(3, 1, figsize=(9, 8), constrained_layout=True)
        for ax, key, unit in zip(axes[:2], ('translation_error_mm', 'rotation_error_deg'), ('mm', 'degrees')):
            ax.plot([int(e['frame']) for e in anchored], [e[key] for e in anchored], '.-', label='object drift from first-frame alignment')
            if not anchored:
                ax.text(.5, .5, 'No valid same-frame marker/pose pairs', ha='center', transform=ax.transAxes)
            ax.set_ylabel(unit); ax.grid(True, alpha=.3)
        axes[0].set_title('First-frame aligned object drift; not absolute object accuracy')
        axes[2].plot([int(e['frame']) for e in events], [e['host_receive_to_result_seconds'] * 1000 for e in events], '.-')
        axes[2].set_ylabel('input-to-result ms'); axes[2].set_xlabel('processed frame'); axes[2].grid(True, alpha=.3)
        fig.savefig(args.output / 'errors_and_latency.png', dpi=180); plt.close(fig)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('reference_raw_changes', 'relative_errors', 'anchored_object_errors', 'absolute_errors', 'evidence_sha256')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
