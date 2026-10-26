#!/usr/bin/env python3
"""Controlled diagnostic: fresh same-frame mask/register on an existing live segment."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('prepare-mask', 'replay'), required=True)
    p.add_argument('--root', type=Path, default=Path('/data/ZJC/foundationPos'))
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--frames', type=int, default=120)
    p.add_argument('--roi', type=int, nargs=4)
    p.add_argument('--hard-background', type=int, nargs=4, action='append', default=[],
                   help='RGB-inspected background rectangles xyxy for diagnostic GrabCut only')
    p.add_argument('--hard-foreground', type=int, nargs=4, action='append', default=[])
    p.add_argument('--mask-directory', type=Path)
    args = p.parse_args()
    if args.output.exists() or args.start < 0 or args.frames < 1:
        p.error('Use new output and positive segment indices/count')
    import cv2
    import numpy as np
    source = args.source.resolve(strict=True)
    initial = source / 'frames' / ('%06d' % args.start)
    request = json.loads((source / 'requests' / ('%06d.json' % args.start)).read_text())
    for name in ('rgb.png', 'depth.png'):
        if sha(initial / name) != request['input_sha256'][name]:
            raise ValueError('Original input SHA mismatch')
    if args.mode == 'prepare-mask':
        if args.roi is None:
            p.error('Mask preparation requires RGB-inspected --roi')
        rgb = cv2.imread(str(initial / 'rgb.png'))
        raw = cv2.imread(str(initial / 'depth.png'), -1)
        mask = np.zeros(raw.shape, np.uint8)
        bgmodel, fgmodel = np.zeros((1, 65)), np.zeros((1, 65))
        cv2.grabCut(rgb, mask, tuple(args.roi), bgmodel, fgmodel, 5, cv2.GC_INIT_WITH_RECT)
        for x0, y0, x1, y1 in args.hard_background:
            mask[y0:y1, x0:x1] = cv2.GC_BGD
        for x0, y0, x1, y1 in args.hard_foreground:
            mask[y0:y1, x0:x1] = cv2.GC_FGD
        if args.hard_background or args.hard_foreground:
            cv2.grabCut(rgb, mask, None, bgmodel, fgmodel, 5, cv2.GC_INIT_WITH_MASK)
        mask = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8) * 255
        args.output.mkdir(parents=True, exist_ok=False)
        cv2.imwrite(str(args.output / 'mask.png'), mask)
        vis = rgb.copy()
        contours = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
        cv2.drawContours(vis, contours, -1, (0, 255, 255), 1)
        cv2.imwrite(str(args.output / 'preview.png'), vis)
        report = dict(passed=True, scope='diagnostic candidate mask; requires RGB review; not GT',
                      source_frame='%06d' % args.start, roi=args.roi,
                      hard_background_rectangles=args.hard_background,
                      hard_foreground_rectangles=args.hard_foreground,
                      source_rgb_sha256=sha(initial / 'rgb.png'), source_depth_sha256=sha(initial / 'depth.png'),
                      mask_sha256=sha(args.output / 'mask.png'), nonzero_depth_ratio=float(np.mean(raw[mask > 0] > 0)))
        write(args.output / 'report.json', report)
        print(json.dumps(report))
        return 0
    root = args.root.resolve(strict=True)
    dataroot = (root / 'foundationpose_data').resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(dataroot)
    if args.mask_directory is None:
        p.error('Replay needs inspected same-frame mask directory')
    maskproof = json.loads((args.mask_directory / 'report.json').read_text())
    if (maskproof['source_frame'] != '%06d' % args.start
            or maskproof['source_rgb_sha256'] != sha(initial / 'rgb.png')
            or maskproof['source_depth_sha256'] != sha(initial / 'depth.png')
            or maskproof['mask_sha256'] != sha(args.mask_directory / 'mask.png')):
        raise ValueError('Diagnostic mask does not belong to this actual RGB-D frame')
    original = json.loads((source / 'session.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    for name in ('frames', 'requests', 'responses', 'processing', 'worker_code'):
        (output / name).mkdir()
    report = dict(passed=False, source='offline_existing_live_segment', new_initialization_frame='%06d' % args.start,
                  source_session=str(source), source_session_sha256=sha(source / 'session.json'),
                  source_model_sha256=original['mesh_sha256'], pose_accuracy_validated=False,
                  diagnostic_mask_proof=maskproof, initialization_is_custom_diagnostic=True,
                  original_live_outputs_modified=False, runtime_fps_not_measured=True, frame_ids=[])
    process = log = None
    try:
        for name, digest in original['code_sha256'].items():
            old = source / 'worker_code' / name
            if sha(old) != digest:
                raise ValueError('Original worker snapshot changed')
            shutil.copy2(old, output / 'worker_code' / name)
        for index in range(args.start, args.start + args.frames):
            stem = '%06d' % index
            src, dst = source / 'frames' / stem, output / 'frames' / stem
            original_request = json.loads((source / 'requests' / (stem + '.json')).read_text())
            dst.mkdir()
            names = ['rgb.png', 'depth.png', 'capture.json']
            for name in names:
                if sha(src / name) != original_request['input_sha256'][name]:
                    raise ValueError('Original segment input changed')
                shutil.copy2(src / name, dst / name)
            if index == args.start:
                shutil.copy2(args.mask_directory / 'mask.png', dst / 'mask.png')
                names.append('mask.png')
            write(output / 'requests' / (stem + '.json'),
                  dict(frame=stem, operation='register' if index == args.start else 'track',
                       K=original['K'], source='offline_fresh_initialization_diagnostic',
                       saved_depth_unit='millimeter', input_sha256={name: sha(dst / name) for name in names}))
            report['frame_ids'].append(stem)
        mapped = '/data/' + output.relative_to(dataroot).as_posix()
        mesh = original['worker_command'][original['worker_command'].index('--mesh') + 1]
        command = ['/usr/bin/python3', str(root / 'setup/run_logged.py'), '--root', str(root),
                   '--label', 'cup_live_fresh_segment_gpu_worker', '--note', 'Offline recorded live segment; new first-frame mask/registration; not GT',
                   '--', 'docker', 'exec', '-w', '/workspace/FoundationPose', 'foundationpose',
                   '/opt/conda/envs/my/bin/python', '-B', '-u', mapped + '/worker_code/run_cup_live_worker.py',
                   '--session', mapped, '--repo', '/workspace/FoundationPose', '--mesh', mesh,
                   '--mesh-sha256', original['mesh_sha256']]
        log = (output / 'worker_stdout.log').open('wb')
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 180
        last = 0
        while len(list((output / 'responses').glob('*.json'))) < args.frames:
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Diagnostic worker stopped before completing segment')
            completed = len(list((output / 'responses').glob('*.json')))
            if completed // 20 > last // 20:
                print(json.dumps(dict(completed=completed, total=args.frames)), flush=True)
                last = completed
            time.sleep(0.1)
        (output / 'stop.flag').write_text('stop\n')
        report['worker_exit_code'] = process.wait(timeout=25)
        results = [json.loads((output / 'responses' / (stem + '.json')).read_text()) for stem in report['frame_ids']]
        report.update(completed=sum(r['passed'] for r in results),
                      failed_frames=[r['frame'] for r in results if not r['passed']],
                      passed=report['worker_exit_code'] == 0 and all(r['passed'] for r in results))
    except Exception as error:
        report.update(error=str(error), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        (output / 'stop.flag').write_text('stop\n')
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                process.terminate()
        if log is not None:
            log.close()
        write(output / 'diagnostic_report.json', report)
        print(json.dumps(dict(passed=report['passed'], completed=report.get('completed'), output=str(output), pose_accuracy_validated=False)))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
