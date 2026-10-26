#!/usr/bin/env python3
"""Real GPU/HTTP tests and end-to-end 30Hz saved-image replay benchmark; no live/GT claim."""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--controls', action='store_true')
    p.add_argument('--port', type=int, default=8768)
    args = p.parse_args()
    root = args.root.resolve(strict=True); output = args.output.resolve()
    output.relative_to(root / 'foundationpose_data'); output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, source='30Hz repeated independent saved RGB-D', live_camera_fps_measured=False,
                  physical_accuracy_validated=False, checks={}, controls=args.controls)
    session = output / 'session'
    process = logstream = None
    base = 'http://127.0.0.1:' + str(args.port)

    def get(path):
        with urllib.request.urlopen(base + path, timeout=5) as stream:
            return stream.read()

    def post(path, value=None):
        req = urllib.request.Request(base + path, data=json.dumps(value or {}).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as stream:
            return json.loads(stream.read())

    def status():
        try:
            return json.loads(get('/status'))
        except (OSError, urllib.error.URLError):
            return {}

    def until(predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            if process.poll() is not None:
                raise RuntimeError('Bridge exited before expected state')
            time.sleep(.02)
        raise TimeoutError('Integration test timed out')

    try:
        for name in ('run_cup_live_fast.py', 'run_cup_live_worker.py', 'cup_aruco_reference.py', 'cup_pose_quality.py'):
            ast.parse((root / 'setup' / name).read_text(encoding='utf-8-sig'))
        subprocess.run(['bash', '-n', str(root / 'setup/run_cup_live_fast.sh')], check=True)
        scene = root / 'foundationpose_data/windows_captures/cup_photos_20261013_204739_875'
        masks = root / 'foundationpose_data/derived/cup_masks_test_204739_v2'
        proof = root / 'foundationpose_data/derived/cup_fp_new72_geometric_heldout5_v1_20261014_1958/report.json'
        command = ['bash', str(root / 'setup/run_cup_live_fast.sh'), '--root', str(root), '--output', str(session), '--port', str(args.port),
                   '--duration-seconds', '120', '--replay-scene', str(scene), '--replay-mask-dir', str(masks), '--replay-proof', str(proof),
                   '--replay-count', '180', '--aruco-marker-length-m', '0.06', '--aruco-fixed-scene']
        if args.controls:
            command.append('--replay-wait-for-roi')
        logstream = (output / 'bridge_stdout.log').open('wb')
        process = subprocess.Popen(command, cwd=root, stdout=logstream, stderr=subprocess.STDOUT)
        if args.controls:
            until(lambda: status().get('state') == 'waiting_for_roi')
            try:
                post('/initialize')
                raise AssertionError('Mask-free initialize must be rejected')
            except urllib.error.HTTPError as error:
                assert error.code == 400
            until(lambda: bool(get('/preview.jpg')))
            post('/freeze')
            yy, xx = np.nonzero(cv2.imread(str(masks / 'masks/000004.png'), 0))
            x, y = max(0, int(xx.min()) - 10), max(0, int(yy.min()) - 10)
            rect = [x, y, min(640, int(xx.max()) + 11) - x, min(480, int(yy.max()) + 11) - y]
            mask_result = post('/mask', dict(rect=rect)); post('/initialize', dict(candidate_id=mask_result['candidate_id']))
            until(lambda: status().get('completed', 0) >= 10)
            (output / 'overlay.jpg').write_bytes(get('/overlay.jpg'))
            post('/pause'); time.sleep(.3)
            count = status()['completed']; time.sleep(.3)
            assert status()['state'] == 'paused' and status()['completed'] == count
            post('/freeze'); mask_result = post('/mask', dict(rect=rect)); post('/initialize', dict(candidate_id=mask_result['candidate_id']))

            def pending_register():
                for path in sorted((session / 'processing').glob('*.json'), reverse=True):
                    item = json.loads(path.read_text())
                    if item['operation'] == 'register' and path.stem != '000000' and not (session / 'responses' / path.name).exists():
                        return path.stem
                return None
            stopped_frame = until(pending_register, 20)
            post('/stop')
            report['checks']['freeze_mask_initialize_track_pause_reinitialize_stop'] = True
            report['stopped_frame'] = stopped_frame
        exit_code = process.wait(timeout=60)
        if exit_code:
            raise RuntimeError('Bridge failed: ' + (output / 'bridge_stdout.log').read_text()[-4000:])
        host = json.loads((session / 'session.json').read_text())
        gpu = json.loads((session / 'worker_report.json').read_text())
        events = [json.loads(line) for line in (session / 'frame_events.jsonl').read_text().splitlines()]
        assert host['passed'] and gpu['passed']
        assert host['completed_frames'] == gpu['frames_completed'] == len(events) == len(list((session / 'requests').glob('*.json')))
        assert host['failed_frames'] == gpu['frames_failed'] == 0
        assert len(set(e['frame'] for e in events)) == len(events)
        original_rgb = cv2.cvtColor(cv2.imread(str(scene / 'rgb/000004.png')), cv2.COLOR_BGR2RGB)
        original_depth = cv2.imread(str(scene / 'depth/000004.png'), -1)
        sequences = []
        for event in events:
            folder = session / 'frames' / event['frame']
            request = json.loads((session / 'requests' / (event['frame'] + '.json')).read_text())
            for name, digest in request['input_sha256'].items():
                assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
            assert np.array_equal(np.load(str(folder / 'rgb.npy'), allow_pickle=False), original_rgb)
            assert np.array_equal(np.load(str(folder / 'depth.npy'), allow_pickle=False), original_depth)
            capture = json.loads((folder / 'capture.json').read_text())
            sequences.append(capture['sequence'])
            assert capture['rgb_sdk_timestamp_ms'] is None
            pose = np.loadtxt(folder / 'pose_camera_from_mesh.txt')
            assert np.allclose(pose, event['pose'])
            assert hashlib.sha256((folder / 'pose_camera_from_mesh.txt').read_bytes()).hexdigest() == event['pose_sha256']
            assert event['reference_evaluation']['relative_errors'] is None, 'Saved scene has no marker, so no error may be invented'
        assert all(b > a for a, b in zip(sequences, sequences[1:])), 'A camera frame cannot be submitted twice'
        rows = list(csv.DictReader((session / 'aruco_errors.csv').open(encoding='utf-8')))
        assert len(rows) == len(events) and all(row['relative_translation_mm'] == '' for row in rows)
        if args.controls:
            assert sum(e['operation'] == 'register' for e in events) == 2
            assert any(e.get('drained_after_stop') and e['frame'] == report['stopped_frame'] for e in events)
        else:
            assert len(events) == 180 and host['quality_rejected_frames'] == 0
        for name, digest in host['code_sha256'].items():
            assert hashlib.sha256((session / 'worker_code' / name).read_bytes()).hexdigest() == digest
        tracks = events[5:]
        report.update(passed=True, session=str(session), completed=host['completed_frames'], quality_rejected=host['quality_rejected_frames'],
                      steady_processing_fps=host['steady_processing_fps'], gpu=gpu['gpu'],
                      median_host_latency_ms=float(np.median([e['host_receive_to_result_seconds'] * 1000 for e in tracks])),
                      p95_host_latency_ms=float(np.percentile([e['host_receive_to_result_seconds'] * 1000 for e in tracks], 95)),
                      median_worker_ms=float(np.median([e['worker_seconds'] * 1000 for e in tracks])),
                      official_tracking_iterations=gpu['tracking_iterations'], weights=gpu['weights'], repo_commit=gpu['repo_commit'])
        report['checks'].update(lossless_source_pixels_and_hashes=True, all_poses_preserved=True, missing_marker_errors_null=True,
                                camera_sequence_strictly_increasing=True, source_snapshots_intact=True)
    except Exception as error:
        report.update(error=str(error), traceback=traceback.format_exc()); traceback.print_exc()
    finally:
        if process is not None and process.poll() is None:
            try:
                post('/stop'); process.wait(timeout=30)
            except Exception:
                (session / 'stop.flag').write_text('stop\n'); process.terminate()
        if logstream is not None:
            logstream.close()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k not in ('weights', 'checks', 'traceback')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
