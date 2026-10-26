#!/usr/bin/env python3
"""Real GPU/HTTP integration smoke on repeated saved RGB-D, never live-camera QA."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--port', type=int, default=8767)
    args = p.parse_args()
    root, output = args.root.resolve(strict=True), args.output.resolve()
    output.relative_to(root / 'foundationpose_data')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, live_camera_validated=False, real_time_fps_validated=False,
                  pose_accuracy_validated=False, source='repeated independent saved frame 000004', checks={})
    process = logstream = None
    base = 'http://127.0.0.1:' + str(args.port)
    session = output / 'session'

    def get(path):
        with urllib.request.urlopen(base + path, timeout=5) as r:
            return r.read()

    def post(path, value=None):
        data = json.dumps(value or {}).encode()
        request = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=10) as r:
            return json.loads(r.read())

    def until(predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            if process is not None and process.poll() is not None:
                raise RuntimeError('Replay bridge exited before expected control state')
            time.sleep(0.03)
        raise TimeoutError('Timed out during integration smoke')

    def status():
        try:
            return json.loads(get('/status'))
        except (OSError, urllib.error.URLError):
            return {}

    try:
        import cv2
        import numpy as np
        import pyrealsense2 as rs
        from PIL import Image
        report['packages'] = {name: importlib.metadata.version(name)
                              for name in ('numpy', 'pyrealsense2', 'pillow', 'opencv-python-headless')}
        assert report['packages']['numpy'] == '1.26.4'
        assert report['packages']['opencv-python-headless'] == '4.11.0.86'
        report['sdk_device_count'] = len(list(rs.context().query_devices()))
        subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
        for name in ('run_cup_live.py', 'run_cup_live_worker.py', 'cup_live_dashboard.py'):
            ast.parse((root / 'setup' / name).read_text(encoding='utf-8-sig'))
        subprocess.run(['bash', '-n', str(root / 'setup/run_cup_live.sh')], check=True)
        report['checks']['dependency_and_source_preflight'] = True
        command = ['bash', str(root / 'setup/run_cup_live.sh'), '--root', str(root),
                   '--output', str(session), '--port', str(args.port), '--duration-seconds', '180',
                   '--replay-scene', str(root / 'foundationpose_data/windows_captures/cup_photos_20261013_204739_875'),
                   '--replay-mask-dir', str(root / 'foundationpose_data/derived/cup_masks_test_204739_v2'),
                   '--replay-proof', str(root / 'foundationpose_data/derived/cup_fp_new72_geometric_heldout5_v1_20261014_1958/report.json'),
                   '--replay-frame', '000004', '--replay-count', '100', '--replay-wait-for-roi']
        logstream = (output / 'bridge_stdout.log').open('wb')
        process = subprocess.Popen(command, cwd=root, stdout=logstream, stderr=subprocess.STDOUT)
        until(lambda: status().get('state') == 'waiting_for_roi')
        html = get('/').decode('utf-8')
        assert '冻结画面' in html and '确认 Mask 并初始化' in html
        script = re.search(r'<script>([\s\S]*?)</script>', html).group(1)
        (output / 'dashboard_client.js').write_text(script, encoding='utf-8')
        (output / 'dashboard.html').write_text(html, encoding='utf-8')
        try:
            post('/initialize')
            raise AssertionError('Initialization without same-frame mask must fail')
        except urllib.error.HTTPError as error:
            assert error.code == 400
        report['checks']['initialization_without_mask_rejected'] = True
        deadline = time.monotonic() + 5
        while True:
            try:
                post('/freeze')
                break
            except urllib.error.HTTPError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        target = cv2.imread(str(root / 'foundationpose_data/derived/cup_masks_test_204739_v2/masks/000004.png'), 0) > 0
        yy, xx = np.nonzero(target)
        x, y = max(0, int(xx.min()) - 10), max(0, int(yy.min()) - 10)
        right, bottom = min(640, int(xx.max()) + 11), min(480, int(yy.max()) + 11)
        rect = [x, y, right - x, bottom - y]
        post('/mask', dict(rect=rect))
        (output / 'mask_preview.jpg').write_bytes(get('/preview.jpg'))
        assert Image.open(output / 'mask_preview.jpg').size == (640, 480)
        post('/initialize')
        until(lambda: status().get('completed', 0) >= 3)
        (output / 'pose_overlay.jpg').write_bytes(get('/overlay.jpg'))
        post('/pause')
        time.sleep(1)
        paused = status()
        count = paused['completed']
        time.sleep(0.4)
        assert status()['state'] == 'paused' and status()['completed'] == count
        report['checks']['freeze_grabcut_initialize_track_pause'] = True
        post('/freeze')
        post('/mask', dict(rect=rect))
        post('/initialize')

        def in_flight_registration():
            for marker in sorted((session / 'processing').glob('*.json'), reverse=True):
                item = json.loads(marker.read_text())
                if (item['operation'] == 'register' and marker.stem != '000000'
                        and not (session / 'responses' / marker.name).exists()):
                    return marker.stem
            return None

        stopped_frame = until(in_flight_registration, timeout=20)
        post('/stop')
        exit_code = process.wait(timeout=35)
        assert exit_code == 0
        host = json.loads((session / 'session.json').read_text())
        gpu = json.loads((session / 'worker_report.json').read_text())
        events = [json.loads(line) for line in (session / 'frame_events.jsonl').read_text().splitlines()]
        responses = sorted((session / 'responses').glob('*.json'))
        requests = sorted((session / 'requests').glob('*.json'))
        assert host['passed'] and gpu['passed'] and host['source'] == 'offline_replay'
        assert host['completed_frames'] == gpu['frames_completed'] == len(events) == len(responses) == len(requests)
        assert host['failed_frames'] == gpu['frames_failed'] == 0
        assert len({event['frame'] for event in events}) == len(events)
        assert sum(event['operation'] == 'register' for event in events) == 2
        assert any(event['operation'] == 'track' for event in events)
        assert any(event.get('drained_after_stop') and event['frame'] == stopped_frame for event in events)
        for event in events:
            folder = session / 'frames' / event['frame']
            pose = np.loadtxt(folder / 'pose_camera_from_mesh.txt')
            assert pose.shape == (4, 4) and np.allclose(pose, event['pose'])
            assert hashlib.sha256((folder / 'pose_camera_from_mesh.txt').read_bytes()).hexdigest() == event['pose_sha256']
            assert cv2.imread(str(folder / 'depth.png'), -1).dtype == np.uint16
        # Verify localhost port is closed after normal operator stop.
        try:
            get('/status')
            raise AssertionError('Preview server still listening after stop')
        except (urllib.error.URLError, OSError):
            pass
        report['checks']['stop_during_inference_retained_and_indexed'] = True
        report['checks']['web_server_closed_on_stop'] = True
        report.update(passed=True, completed_frames=host['completed_frames'], stopped_frame=stopped_frame,
                      roi=rect, gpu=gpu['gpu'], session=str(session), worker_exit_code=host['worker_exit_code'])
    except Exception as error:
        report.update(error=str(error), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        if process is not None and process.poll() is None:
            try:
                post('/stop')
                process.wait(timeout=30)
            except Exception:
                if session.exists():
                    (session / 'stop.flag').write_text('stop\n')
                process.terminate()
        if logstream is not None:
            logstream.close()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
