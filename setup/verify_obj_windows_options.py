#!/usr/bin/env python3
"""Bounded one-photo SDK check of preset, raw/filtered PNGs and bag playback.

Automatically trigger one stationary environment-check photo; no multi-view
production capture or object reconstruction is performed.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--depth-preset', choices=('high-accuracy', 'high-density'), default='high-accuracy')
    parser.add_argument('--depth-auto-exposure', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, scope='one_automatically_triggered_environment_check_photo',
                  real_multiview_capture=False, packages={})
    process = None
    playback_pipeline = None
    try:
        import cv2
        import numpy as np
        import pyrealsense2 as rs
        for name in ('pyrealsense2', 'numpy', 'Pillow', 'opencv-python'):
            report['packages'][name] = importlib.metadata.version(name)
        pip = subprocess.run([sys.executable, '-m', 'pip', 'check'],
                             capture_output=True, text=True, timeout=45)
        report['pip_check'] = dict(exit_code=pip.returncode, output=pip.stdout + pip.stderr)
        if pip.returncode:
            raise RuntimeError('Windows capture dependencies conflict')
        frozen = subprocess.run([sys.executable, '-m', 'pip', 'freeze'],
                                capture_output=True, text=True, check=True, timeout=45)
        (output / 'requirements.lock.txt').write_text(frozen.stdout, encoding='utf-8')
        argv = [sys.executable, '-B', '-u', str(Path(__file__).with_name('capture_d435i_photos.py')),
                '--output', str(output / 'single_photo'), '--views', '1', '--warmup', '30',
                '--depth-preset', args.depth_preset, '--save-filtered-depth', '--record-bag']
        if args.depth_auto_exposure:
            argv.append('--depth-auto-exposure')
        report['capture_argv'] = argv
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        triggered = False
        for line in process.stdout:
            print(line, end='', flush=True)
            if 'press Enter to save one RGB-D pair' in line and not triggered:
                process.stdin.write('\n')
                process.stdin.flush()
                triggered = True
        code = process.wait(timeout=10)
        report['capture_exit_code'] = code
        if code or not triggered:
            raise RuntimeError('Bounded photo/preset/filter/bag capture failed')
        captured = json.loads((output / 'single_photo/metadata.json').read_text(encoding='utf-8'))
        report['capture'] = {key: captured[key] for key in
                             ('device', 'saved_frames', 'depth_processing', 'bag_recording', 'pipeline_stopped')}
        for name in ('depth', 'depth_filtered'):
            path = output / 'single_photo' / name / '000000.png'
            array = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if array is None or array.dtype != np.uint16 or array.shape != (480, 640) or not np.any(array):
                raise RuntimeError('Invalid raw/derived 16-bit depth PNG: ' + name)
        path = output / 'single_photo/raw_streams.bag'
        if path.stat().st_size < 10000:
            raise RuntimeError('SDK bag file is missing or too small')
        playback_pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device_from_file(str(path), False)
        active = playback_pipeline.start(config)
        active.get_device().as_playback().set_real_time(False)
        frames = playback_pipeline.wait_for_frames(10000)
        if not frames.get_color_frame() or not frames.get_depth_frame():
            raise RuntimeError('Recorded bag does not replay both native color and depth')
        report['bag_playback'] = dict(passed=True, bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            native_color_frame=frames.get_color_frame().get_frame_number(),
            native_depth_frame=frames.get_depth_frame().get_frame_number())
        report['passed'] = True
    except Exception as exc:
        report['error'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            process.stdin.close()
        if playback_pipeline is not None:
            try:
                playback_pipeline.stop()
            except Exception as exc:
                report['passed'] = False
                report['playback_stop_error'] = str(exc)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
