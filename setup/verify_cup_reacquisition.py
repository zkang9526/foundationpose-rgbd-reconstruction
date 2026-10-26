"""GPU integration: initial pose -> missing target -> autonomous search -> return."""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import cv2
import numpy as np
from cup_reacquisition import target_signature, choose_target, fresh_frame_check


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--pure-only', action='store_true')
    p.add_argument('--real-return', action='store_true')
    args = p.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    output.relative_to(root / 'foundationpose_data')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, physical_accuracy_validated=False, source='saved real cup image with explicitly synthetic 6s absence')
    for name in ['cup_reacquisition.py', 'cup_sam2_mask.py', 'cup_sam2_worker.py', 'run_cup_live_fast.py', 'run_cup_live_worker.py']:
        ast.parse((root / 'setup' / name).read_text())
    scene = root / 'foundationpose_data/windows_captures/cup_photos_20261013_204739_875'
    masks = root / 'foundationpose_data/derived/cup_masks_test_204739_v2'
    proof = root / 'foundationpose_data/derived/cup_fp_new72_geometric_heldout5_v1_20261014_1958/report.json'
    rgb = cv2.cvtColor(cv2.imread(str(scene / 'rgb/000004.png')), cv2.COLOR_BGR2RGB)
    depth = cv2.imread(str(scene / 'depth/000004.png'), -1)
    mask = cv2.imread(str(masks / 'masks/000004.png'), 0)
    K = np.loadtxt(scene / 'cam_K.txt').reshape(3, 3)
    sig = target_signature(rgb, mask, depth, K)
    # Deterministic fresh-frame movement rejection and ambiguous duplicate check.
    shifted = cv2.warpAffine(rgb, np.float32([[1, 0, 30], [0, 1, 0]]), (640, 480))
    assert not fresh_frame_check(rgb, shifted, mask)['consistent']
    assert fresh_frame_check(rgb, rgb.copy(), mask)['consistent']
    # Duplicate synthetic candidates use the same target footprint on two disjoint masks.
    left = cv2.warpAffine(mask, np.float32([[1, 0, -100], [0, 1, 0]]), (640, 480)) > 0
    right = cv2.warpAffine(mask, np.float32([[1, 0, 100], [0, 1, 0]]), (640, 480)) > 0
    synthetic = np.full_like(rgb, 90)
    for shift, shifted_mask in [(-100, left), (100, right)]:
        moved_rgb = cv2.warpAffine(rgb, np.float32([[1, 0, shift], [0, 1, 0]]), (640, 480))
        synthetic[shifted_mask] = moved_rgb[shifted_mask]
    ambiguous_index, ambiguity = choose_target(sig, synthetic, np.full_like(depth, round(sig['median_depth_m'] * 1000)), K,
        [left, right], [dict(predicted_iou=.99), dict(predicted_iou=.99)])
    assert ambiguous_index is None and ambiguity['ambiguous']
    # Appearance rejection is tested directly with the observed target descriptor.
    index, _ = choose_target(sig, np.full_like(rgb, 90), depth, K, [mask > 0], [dict(predicted_iou=.99)])
    assert index is None
    report['pure_checks'] = dict(motion_rejected=True, identical_frame_accepted=True, wrong_color_rejected=True, ambiguous_duplicates_rejected=True)
    if args.pure_only:
        report['passed'] = True
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
        return
    session = output / 'session'
    command = ['bash', str(root / 'setup/run_cup_live_fast.sh'), '--output', str(session), '--port', '8772',
        '--duration-seconds', '150', '--max-frames', '75', '--replay-count', '75', '--replay-loss-test',
        '--replay-scene', str(scene), '--replay-mask-dir', str(masks), '--replay-proof', str(proof)]
    real_folder = root / 'foundationpose_data/live_sessions/cup_fast_20261015_105319_214e4f54/frames/000678'
    if args.real_return:
        command += ['--replay-return-frame-dir', str(real_folder)]
    else:
        command += ['--replay-return-shift-x', '-100']
    states = []
    with (output / 'bridge.log').open('w') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, cwd=root)
        deadline = time.monotonic() + 180
        while process.poll() is None and time.monotonic() < deadline:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8772/status', timeout=2) as response:
                    value = json.loads(response.read())
                if not states or states[-1]['state'] != value['state']:
                    states.append(dict(state=value['state'], seconds=time.monotonic(), pose_visible=value.get('pose') is not None))
                if value['state'] in ['needs_reinitialization', 'searching_target']:
                    assert value['pose'] is None
            except OSError:
                pass
            time.sleep(.04)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=120)
        report['exit_code'] = process.returncode
    host = json.loads((session / 'session.json').read_text())
    events = [json.loads(line) for line in (session / 'frame_events.jsonl').read_text().splitlines()]
    registrations = [e for e in events if e['operation'] == 'register']
    searches = list((session / 'mask_attempts').glob('*/target_selection.json'))
    absence = [e for e in events if json.loads((session / 'frames' / e['frame'] / 'capture.json').read_text())['source'] == 'synthetic_uniform_background_target_absence']
    assert process.returncode == 0 and host['passed'], 'See bridge.log'
    assert len(registrations) >= 2 and host['recovery_attempts'] >= 1
    assert all(not e['accepted_for_tracking'] and not e['pose_confirmed'] for e in absence)
    assert any(json.loads(v.read_text())['check']['selected'] is None for v in searches)
    final = events[-1]
    assert final['pose_confirmed'] and final['accepted_for_tracking']
    recovered_folder = session / 'frames' / registrations[-1]['frame']
    capture = json.loads((recovered_folder / 'capture.json').read_text())
    assert capture['initialization']['method'].startswith('automatic full-frame SAM2')
    assert (recovered_folder / 'official_top1_pose.txt').exists()
    assert (recovered_folder / 'registration_candidates.json').exists()
    selected_mask = cv2.imread(str(recovered_folder / 'mask.png'), 0)
    observed_shift = float(np.nonzero(selected_mask)[1].mean() - np.nonzero(mask)[1].mean())
    if args.real_return:
        actual = json.loads((real_folder / 'capture.json').read_text())['initialization']['roi']
        yy, xx = np.nonzero(selected_mask)
        assert actual[0] <= xx.mean() <= actual[0]+actual[2] and actual[1] <= yy.mean() <= actual[1]+actual[3]
    else:
        assert abs(observed_shift + 100) < 25, 'Must find target at new location without old ROI'
    cv2.imwrite(str(output / 'recovered_mask.png'), selected_mask)
    final_folder = session / 'frames' / events[-1]['frame']
    import shutil
    shutil.copy2(final_folder / 'overlay.jpg', output / 'recovered_overlay.jpg')
    assert any(v['state'] == 'searching_target' for v in states)
    report.update(passed=True, states=states, registrations=[e['frame'] for e in registrations],
        recovery_attempts=host['recovery_attempts'], absent_processed_frames=len(absence),
        completed=host['completed_frames'], quality_rejected=host['quality_rejected_frames'],
        continuous_replay_fps=host['steady_processing_fps'], manual_reinitialization_calls=0,
        actual_saved_return_view=args.real_return, known_synthetic_return_shift_px=None if args.real_return else -100,
        recovered_mask_centroid_shift_px=observed_shift,
        recovered_registration_selection=registrations[-1]['registration_selection'])
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
