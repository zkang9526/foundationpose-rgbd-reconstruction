"""Real SAM/GPU/HTTP initialization check on saved RGB-D; no physical GT claims."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import cv2
import numpy as np
from cup_sam_mask import generate_sam_mask, validate_prompts


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--backend', choices=['sam', 'sam2'], default='sam')
    args = p.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    output.relative_to(root / 'foundationpose_data')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, actual_camera_fps_measured=False, physical_accuracy_validated=False, checks={})
    report['segmentation_backend_tested'] = args.backend
    process = stream = None
    base = 'http://127.0.0.1:8771'

    def get():
        try:
            with urllib.request.urlopen(base + '/status', timeout=3) as r:
                return json.loads(r.read())
        except OSError:
            return {}

    def post(path, value=None):
        req = urllib.request.Request(base + path, data=json.dumps(value or {}).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=115) as r:
            return json.loads(r.read())

    try:
        for bad in [([0, 0, 11, 20], [], []), ([10, 10, 30, 30], [[640, 0]], [1]), ([10, 10, 30, 30], [[20, 20]], [])]:
            try:
                validate_prompts(*bad)
                raise AssertionError('Bad prompts accepted')
            except ValueError:
                pass
        report['checks']['invalid_prompts_rejected'] = True
        scene = root / 'foundationpose_data/windows_captures/cup_photos_20261013_204739_875'
        masks = root / 'foundationpose_data/derived/cup_masks_test_204739_v2'
        proof = root / 'foundationpose_data/derived/cup_fp_new72_geometric_heldout5_v1_20261014_1958/report.json'
        previous = cv2.imread(str(masks / 'masks/000004.png'), 0)
        yy, xx = np.nonzero(previous)
        x, y = max(0, int(xx.min()) - 12), max(0, int(yy.min()) - 12)
        rect = [x, y, min(640, int(xx.max()) + 13) - x, min(480, int(yy.max()) + 13) - y]
        session = output / 'session'
        command = ['bash', str(root / 'setup/run_cup_live_fast.sh'), '--output', str(session), '--port', '8771',
                   '--mask-backend', args.backend,
                   '--duration-seconds', '240', '--max-frames', '60', '--replay-count', '60', '--replay-wait-for-roi',
                   '--replay-scene', str(scene), '--replay-mask-dir', str(masks), '--replay-proof', str(proof)]
        stream = (output / 'bridge.log').open('w')
        process = subprocess.Popen(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 150
        while get().get('state') != 'waiting_for_roi':
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Bridge not ready')
            time.sleep(.2)
        assert get()['segmentation_backend'] == ('SAM ViT-B' if args.backend == 'sam' else 'SAM2.1 Hiera Tiny')
        post('/freeze')
        first = post('/mask', dict(rect=rect))
        # Foreground and background hints are derived from a prior reviewed candidate,
        # solely to test the prompt path; they are not labels or ground truth.
        _, _, _, fg = cv2.minMaxLoc(cv2.distanceTransform((previous > 0).astype(np.uint8), cv2.DIST_L2, 5))
        bg = [x + 1, y + 1]
        second = post('/mask', dict(rect=rect, points=[list(fg), bg], labels=[1, 0]))
        assert second['candidate_id'] != first['candidate_id']
        try:
            post('/initialize', dict(candidate_id=first['candidate_id']))
            raise AssertionError('Stale mask accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 400
        report['checks']['stale_mask_rejected'] = True
        post('/initialize', dict(candidate_id=second['candidate_id']))
        process.wait(timeout=100)
        if process.returncode:
            raise RuntimeError('Bridge failed; inspect bridge.log')
        host = json.loads((session / 'session.json').read_text())
        assert host['passed'] and host['completed_frames'] == 60 and host['quality_rejected_frames'] == 0
        attempts = sorted((session / 'mask_attempts').iterdir())
        assert len(attempts) == 2
        results = [json.loads((a / 'result.json').read_text()) for a in attempts]
        assert all(v['passed'] for v in results) and all(results[-1]['prompt_agreement'])
        registered = session / 'frames/000000'
        capture = json.loads((registered / 'capture.json').read_text())
        assert capture['initialization']['segmentation']['attempt'] == str(attempts[-1].relative_to(session))
        assert (registered / 'mask.png').read_bytes() == (attempts[-1] / 'mask.png').read_bytes()
        rgb = np.load(registered / 'rgb.npy', allow_pickle=False)
        assert np.array_equal(rgb, np.load(attempts[-1] / 'rgb.npy', allow_pickle=False))
        report['checks'].update(real_sam_box_and_point_inference=True, prompt_agreement=True,
                                same_frozen_rgb_and_accepted_mask_used_by_foundationpose=True, sixty_gpu_pose_frames=True)
        report.update(passed=True, session=str(session), mask_results=results,
                      replay_tracking_fps=host['steady_processing_fps'], source='repeated saved RGB-D, no live FPS/GT claim')
        # Also compare actual recent user's initial frame with its original GrabCut mask.
        real = root / 'foundationpose_data/live_sessions/cup_fast_20261015_105319_214e4f54/frames/000000'
        if real.exists():
            comparison = output / 'recent_real_initialization'
            (comparison / 'worker_code').mkdir(parents=True)
            shutil.copy2(root / 'setup/cup_sam_worker.py', comparison / 'worker_code/cup_sam_worker.py')
            real_rgb = np.load(real / 'rgb.npy', allow_pickle=False)
            original = cv2.imread(str(real / 'mask.png'), 0)
            cap = json.loads((real / 'capture.json').read_text())
            real_rect = cap['initialization']['roi']
            sam, metadata = generate_sam_mask(root, comparison, real_rgb, real_rect, [], [], cap)
            panels = []
            for name, binary in [('GrabCut', original), ('SAM', sam)]:
                vis = cv2.cvtColor(real_rgb, cv2.COLOR_RGB2BGR)
                selected = binary > 0
                vis[selected] = (.6 * vis[selected] + .4 * np.array([0, 220, 255])).astype(np.uint8)
                cv2.putText(vis, name, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                panels.append(vis)
            cv2.imwrite(str(output / 'recent_real_mask_comparison.jpg'), np.concatenate(panels, axis=1))
            cv2.imwrite(str(output / 'recent_real_rgb.png'), cv2.cvtColor(real_rgb, cv2.COLOR_RGB2BGR))
            report['recent_real_comparison'] = dict(source=str(real), metadata=metadata,
                                                   grabcut_pixels=int((original > 0).sum()), sam_pixels=int((sam > 0).sum()),
                                                   human_review_required=True)
    except Exception as error:
        report.update(passed=False, error=str(error), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        if process is not None and process.poll() is None:
            try:
                post('/stop')
                process.wait(timeout=30)
            except Exception:
                process.terminate()
        if stream is not None:
            stream.close()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
