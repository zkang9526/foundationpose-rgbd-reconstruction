#!/usr/bin/env python3
"""Inspect a live bridge, or save a short native D435i/ArUco preflight (no pose GT)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/data/ZJC/foundationPos'))
    p.add_argument('--capture', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--frames', type=int, default=90)
    p.add_argument('--marker-id', type=int, default=6)
    p.add_argument('--length-m', type=float, default=.030)
    args = p.parse_args()
    processes = subprocess.check_output(['ps', '-eo', 'pid,etimes,args'], text=True).splitlines()
    active = [line for line in processes if any(term in line for term in
              ('setup/run_cup_live_fast.py', 'setup/run_cup_live.py', 'realsense-viewer', 'setup/capture_d435i.py'))]
    status = dict(active_camera_processes=active, free_data_gib=shutil.disk_usage(args.root).free / 1024**3)
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/status', timeout=3) as stream:
            status['live_status'] = json.loads(stream.read())
    except (OSError, urllib.error.URLError) as error:
        status['live_status'] = None
        status['live_status_error'] = str(error)
    if not args.capture:
        print(json.dumps(status, indent=2, ensure_ascii=False)); return
    if active or status['live_status'] is not None:
        raise RuntimeError('Existing camera/live process preserved; use its inputs or end it before independent preflight')
    if args.output is None or not 1 <= args.frames <= 600:
        p.error('Capture requires a new --output and 1..600 frames')
    import cv2
    import numpy as np
    import pyrealsense2 as rs
    from cup_aruco_reference import ArucoReference, rigid_error
    output = args.output.resolve()
    output.relative_to((args.root / 'foundationpose_data').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, output=str(output), marker_id=args.marker_id,
                  measured_black_side_m=args.length_m, physical_pose_accuracy_validated=False,
                  scope='marker visibility and pose reference preflight, no FoundationPose inference',
                  raw_marker_change_scope='Not jitter unless camera and scene stayed static throughout',
                  status_before_capture=status, frames=[], dictionaries={})
    dictionaries = ['DICT_4X4_50', 'DICT_5X5_50', 'DICT_6X6_50', 'DICT_7X7_50', 'DICT_ARUCO_ORIGINAL']
    references = {name: ArucoReference(args.length_m, args.marker_id, name) for name in dictionaries}
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    profile = None
    try:
        profile = pipeline.start(config)
        device = profile.get_device()
        scale = device.first_depth_sensor().get_depth_scale()
        intr = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        if any(abs(v) > 1e-10 for v in intr.coeffs):
            raise RuntimeError('Nonzero distortion requires an explicit reference-camera model')
        K = np.array([[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1.]])
        np.savetxt(output / 'K.txt', K)
        report.update(intrinsics=K.tolist(), distortion_coefficients=list(intr.coeffs),
                      serial=device.get_info(rs.camera_info.serial_number), depth_scale_m=scale)
        align = rs.align(rs.stream.color)
        for _ in range(30):
            pipeline.wait_for_frames(timeout_ms=5000)
        for index in range(args.frames):
            frames = align.process(pipeline.wait_for_frames(timeout_ms=5000))
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            rgb = np.asanyarray(color.get_data()).copy()
            raw_depth = np.asanyarray(depth.get_data()).copy()
            folder = output / f'{index:06d}'; folder.mkdir()
            np.save(folder / 'rgb.npy', rgb, allow_pickle=False)
            np.save(folder / 'depth.npy', raw_depth, allow_pickle=False)
            item = dict(frame=f'{index:06d}', host_wall_time_ns=time.time_ns(),
                        color_sdk_ms=color.get_timestamp(), depth_sdk_ms=depth.get_timestamp(),
                        color_frame_number=color.get_frame_number(), depth_frame_number=depth.get_frame_number(),
                        color_timestamp_domain=str(color.get_frame_timestamp_domain()),
                        depth_timestamp_domain=str(depth.get_frame_timestamp_domain()),
                        detections={name: reference.detect(rgb, K) for name, reference in references.items()},
                        sha256={name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                                for name in ('rgb.npy', 'depth.npy')})
            (folder / 'capture.json').write_text(json.dumps(item, indent=2) + '\n')
            report['frames'].append(item)
            if index in (0, args.frames // 2, args.frames - 1):
                image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                for name, detection in item['detections'].items():
                    if detection.get('found'):
                        corners = np.array(detection['corners_px'], np.int32)
                        cv2.polylines(image, [corners], True, (0, 255, 0), 2)
                        cv2.putText(image, name + ' id ' + str(args.marker_id), tuple(corners[0]),
                                    cv2.FONT_HERSHEY_SIMPLEX, .4, (0, 255, 0), 1)
                cv2.imwrite(str(output / f'preview_{index:06d}.png'), image)
        for name in dictionaries:
            all_values = [f['detections'][name] for f in report['frames']]
            accepted = [v for v in all_values if v['reference_accepted']]
            report['dictionaries'][name] = dict(found=sum(v['found'] for v in all_values),
                accepted=len(accepted), total=len(all_values),
                rejection_reasons={reason: sum(v.get('reason') == reason for v in all_values)
                                   for reason in sorted({v.get('reason') for v in all_values})},
                min_edge_pixels=[v['min_edge_pixels'] for v in all_values if v['found']],
                raw_change_from_first_accepted=[rigid_error(np.array(v['pose_camera_from_marker']),
                    np.array(accepted[0]['pose_camera_from_marker'])) for v in accepted] if accepted else [])
        matches = [name for name, value in report['dictionaries'].items() if value['found'] >= args.frames * .5]
        report.update(passed=True, detected_dictionary_families=matches,
                      unique_dictionary_family=matches[0] if len(matches) == 1 else None,
                      usable_reference_observed=any(v['accepted'] > 0 for v in report['dictionaries'].values()))
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        if profile is not None:
            pipeline.stop()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in report.items() if key != 'frames'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
