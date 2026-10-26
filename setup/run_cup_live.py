#!/usr/bin/env python3
"""Ubuntu RGB-D latest-frame bridge, manual initialization, live view and records."""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid

from cup_live_dashboard import make_server
from capture_d435i import get_device_info, get_intrinsics, millimeter_depth
from cup_mesh_selection import add_mesh_arguments, resolve_mesh

MESH_RELATIVE = 'derived/cup_new72_geometric_tsdf_v2_clean_20261014_1920/cup_clean.obj'
MESH_SHA256 = '5b52c3fd9904aaac2b155960d6faabb72be9330e8bb6741c470ec1f4dae4d9de'


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/data/ZJC/foundationPos'))
    p.add_argument('--output', type=Path)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--duration-seconds', type=float, default=600)
    p.add_argument('--max-frames', type=int, default=2000)
    add_mesh_arguments(p)
    p.add_argument('--replay-scene', type=Path)
    p.add_argument('--replay-mask-dir', type=Path)
    p.add_argument('--replay-proof', type=Path)
    p.add_argument('--replay-frame', default='000004')
    p.add_argument('--replay-count', type=int, default=5)
    p.add_argument('--replay-wait-for-roi', action='store_true',
                   help='Replay with browser initialization, for control-path smoke testing only')
    args = p.parse_args()
    if (not 1 <= args.port <= 65535 or args.duration_seconds <= 0 or args.max_frames < 1
            or args.replay_count < 1 or len(args.replay_frame) != 6 or not args.replay_frame.isdigit()):
        p.error('Invalid port, duration or frame count')
    if bool(args.replay_scene) != bool(args.replay_mask_dir) or bool(args.replay_scene) != bool(args.replay_proof):
        p.error('Replay requires scene, mask-dir and accepted inference proof together')
    return args


def main():
    args = parse_args()
    import cv2
    import numpy as np
    root = args.root.resolve(strict=True)
    dataroot = (root / 'foundationpose_data').resolve(strict=True)
    mesh_selection = resolve_mesh(dataroot, args.mesh_profile)
    mesh = Path(mesh_selection['path'])
    output = args.output or dataroot / 'live_sessions' / ('cup_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    output = output.resolve()
    output.relative_to(dataroot)
    output.mkdir(parents=True, exist_ok=False)
    for name in ('frames', 'requests', 'responses', 'processing', 'worker_code'):
        (output / name).mkdir()
    report = dict(passed=False, status='preflight', source='offline_replay' if args.replay_scene else 'live_d435i',
                  output=str(output), completed_frames=0, failed_frames=0,
                  pose_is_ground_truth=False, pose_accuracy_validated=False,
                  camera_axes='OpenCV: x right, y down, z forward',
                  pose_definition='T_camera_from_original_mesh_meters',
                  point_equation='p_camera_m = R @ p_mesh_m + t_m',
                  limits=dict(duration_seconds=args.duration_seconds, processed_frames=args.max_frames),
                  skipped_capture_frames_are_not_saved=True,
                  capture_settings_modified=False, bag_recorded=False,
                  note=os.environ.get('FP_RUN_NOTE', ''), code_sha256={})
    report.update(mesh_profile=args.mesh_profile, mesh_path=str(mesh), mesh_selection=mesh_selection)
    state = dict(lock=threading.RLock(), state='loading', output=str(output), completed=0, failed=0,
                 message='加载模型；首次需要同一冻结帧的杯子Mask', latest=None, frozen=None,
                 candidate=None, pending_register=None, tracking=False, pose=None)
    stop = threading.Event()
    pipeline = server = worker = logstream = None
    started = time.monotonic()
    pending = None
    successful_times = []
    recorded_ids = set()
    records = output / 'frame_events.jsonl'
    failure = None

    def jpeg(color):
        ok, data = cv2.imencode('.jpg', cv2.cvtColor(color, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError('Preview encoding failed')
        return data.tobytes()

    def control(path, value):
        with state['lock']:
            if path == '/freeze':
                if state['latest'] is None:
                    raise ValueError('尚无相机画面')
                if pending is not None:
                    raise ValueError('当前帧正在推理，稍后再冻结')
                state.update(tracking=False, frozen=state['latest'], candidate=None, state='selecting_roi')
                state['preview_jpeg'] = jpeg(state['frozen']['rgb'])
                message = '画面已冻结；拖框包含完整杯身和杯把，并留少量背景'
            elif path == '/mask':
                frozen = state['frozen']
                if frozen is None or state['tracking'] or state['pending_register'] is not None:
                    raise ValueError('请先冻结画面')
                rectangle = value.get('rect')
                if not isinstance(rectangle, list) or len(rectangle) != 4 or any(type(v) is not int for v in rectangle):
                    raise ValueError('需要四个整数的矩形')
                x, y, w, h = rectangle
                if min(x, y) < 0 or min(w, h) < 12 or x + w > 640 or y + h > 480 or w >= 640 or h >= 480:
                    raise ValueError('框应位于图内，包含杯子并留少量背景')
                mask = np.zeros((480, 640), np.uint8)
                cv2.grabCut(frozen['rgb'], mask, tuple(rectangle), np.zeros((1, 65)),
                            np.zeros((1, 65)), 5, cv2.GC_INIT_WITH_RECT)
                binary = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8) * 255
                if np.count_nonzero((binary > 0) & (frozen['depth'] > 0)) < 100:
                    raise ValueError('Mask内有效深度不足，请重新框选或调整摆放')
                state['candidate'] = dict(mask=binary, rectangle=rectangle)
                vis = frozen['rgb'].copy()
                contours = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
                cv2.drawContours(vis, contours, -1, (255, 255, 0), 1)
                state['preview_jpeg'] = jpeg(vis)
                message = '检查黄色Mask：杯身和杯把完整、背景排除；确认后初始化。不满意可重框'
            elif path == '/initialize':
                if state['candidate'] is None or state['frozen'] is None or pending is not None:
                    raise ValueError('先冻结、框选并生成Mask')
                frame = dict(state['frozen'])
                frame['mask'] = state['candidate']['mask'].copy()
                frame['initialization'] = dict(method='browser/API ROI + GrabCut, explicitly selected same frozen frame',
                                               roi=state['candidate']['rectangle'], mask_is_ground_truth=False)
                state.update(pending_register=frame, frozen=None, candidate=None, tracking=False, state='initializing')
                message = '正在初始化；杯子先保持不动，检查右侧杯把投影后再缓慢移动'
            elif path == '/pause':
                state.update(tracking=False, state='paused', pending_register=None)
                message = '已暂停；冻结并重新框选可重新初始化'
            elif path == '/stop':
                stop.set()
                message = '正在停止相机、GPU worker并写入最终记录'
            state['message'] = message
            with (output / 'controls.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(time_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                             action=path, input=value), ensure_ascii=False) + '\n')
            return message

    def save_request(frame, operation, index):
        identifier = '%06d' % index
        folder = output / 'frames' / identifier
        folder.mkdir(exist_ok=False)
        if not cv2.imwrite(str(folder / 'rgb.png'), cv2.cvtColor(frame['rgb'], cv2.COLOR_RGB2BGR)):
            raise RuntimeError('Failed to save source RGB')
        if not cv2.imwrite(str(folder / 'depth.png'), frame['depth']):
            raise RuntimeError('Failed to save source depth')
        names = ['rgb.png', 'depth.png', 'capture.json']
        capture = {k: v for k, v in frame.items() if k not in ('rgb', 'depth', 'mask')}
        atomic_json(folder / 'capture.json', capture)
        if operation == 'register':
            if not cv2.imwrite(str(folder / 'mask.png'), frame['mask']):
                raise RuntimeError('Failed to save first-frame mask')
            names.append('mask.png')
        request = dict(operation=operation, K=report['K'], frame=identifier,
                       input_sha256={name: sha(folder / name) for name in names},
                       source=report['source'], saved_depth_unit='millimeter')
        atomic_json(output / 'requests' / (identifier + '.json'), request)
        return dict(id=identifier, capture=frame, submitted=time.monotonic(), operation=operation)

    try:
        if sha(mesh) != mesh_selection['sha256']:
            raise ValueError('Selected metric candidate mesh SHA differs')
        for name in ('run_cup_live.py', 'cup_live_dashboard.py', 'capture_d435i.py',
                     'run_cup_live_worker.py', 'run_cup_mesh_inference.py', 'verify_demo.py', 'run_cup_live.sh', 'cup_mesh_selection.py'):
            source = root / 'setup' / name
            shutil.copy2(source, output / 'worker_code' / name)
            report['code_sha256'][name] = sha(source)
        report['packages'] = {name: importlib.metadata.version(name) for name in ('numpy', 'pillow')}
        report['opencv_version'] = cv2.__version__
        if shutil.disk_usage(output).free < 1024 ** 3:
            raise RuntimeError('Less than 1 GiB free in output filesystem')
        replay_rgb = replay_depth = replay_mask = None
        if args.replay_scene:
            proof = json.loads(args.replay_proof.read_text(encoding='utf-8'))
            if proof.get('passed') is not True:
                raise ValueError('Replay needs a completed independent inference proof')
            selected = next(item for item in proof['frames'] if item['id'] == args.replay_frame)
            paths = dict(rgb=args.replay_scene / 'rgb' / (args.replay_frame + '.png'),
                         depth=args.replay_scene / 'depth' / (args.replay_frame + '.png'),
                         mask=args.replay_mask_dir / 'masks' / (args.replay_frame + '.png'))
            for name, path in paths.items():
                if sha(path) != selected['inputs'][name]['sha256']:
                    raise ValueError('Replay source differs from saved proof')
            replay_rgb = cv2.cvtColor(cv2.imread(str(paths['rgb'])), cv2.COLOR_BGR2RGB)
            replay_depth = cv2.imread(str(paths['depth']), cv2.IMREAD_UNCHANGED)
            replay_mask = cv2.imread(str(paths['mask']), cv2.IMREAD_UNCHANGED)
            if replay_depth.dtype != np.uint16:
                raise ValueError('Replay needs millimeter uint16 original depth')
            K = np.loadtxt(args.replay_scene / 'cam_K.txt').reshape(3, 3)
            if not np.allclose(K, proof['camera_matrix'], atol=1e-7, rtol=0):
                raise ValueError('Replay intrinsics differ from validated proof')
            report.update(K=K.tolist(), replay_frame=args.replay_frame,
                          replay_repeats_same_image=True, camera_connected=False,
                          replay_source_sha256={name: sha(path) for name, path in paths.items()},
                          replay_proof_sha256=sha(args.replay_proof))
        else:
            import pyrealsense2 as rs
            devices = list(rs.context().query_devices())
            report['devices'] = [get_device_info(rs, device) for device in devices]
            chosen = next((d for d in devices if 'D435I' in d.get_info(rs.camera_info.name).upper()), None)
            if chosen is None:
                raise RuntimeError('No D435i found on Ubuntu; attach camera to its USB 3 port before starting')
            report['device'] = get_device_info(rs, chosen)
            if not str(report['device'].get('usb_type_descriptor', '')).startswith('3'):
                raise RuntimeError('D435i must enumerate on USB 3 for this 640x480 RGB-D 30 FPS entry')
            config = rs.config()
            config.enable_device(report['device']['serial_number'])
            config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
            config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
            pipeline = rs.pipeline()
            profile = pipeline.start(config)
            native_scale = float(profile.get_device().first_depth_sensor().get_depth_scale())
            sensor = profile.get_device().first_depth_sensor()
            report['active_depth_options'] = {}
            for name in ('visual_preset', 'enable_auto_exposure', 'exposure', 'gain',
                         'emitter_enabled', 'laser_power', 'depth_units'):
                option = getattr(rs.option, name, None)
                if option is not None and sensor.supports(option):
                    report['active_depth_options'][name] = sensor.get_option(option)
            align = rs.align(rs.stream.color)
            color_intr = get_intrinsics(profile.get_stream(rs.stream.color))
            if any(abs(v) > 1e-12 for v in color_intr['distortion_coefficients']):
                raise ValueError('Native color profile is not the zero-distortion pinhole expected by this entry')
            K = np.array([[color_intr['fx'], 0, color_intr['cx']],
                          [0, color_intr['fy'], color_intr['cy']], [0, 0, 1]])
            for _ in range(30):
                pipeline.wait_for_frames(5000)
            report.update(camera_connected=True, sdk_version=importlib.metadata.version('pyrealsense2'),
                          color_intrinsics=color_intr, K=K.tolist(), native_depth_scale_m=native_scale,
                          depth_scale_m_per_saved_unit=0.001, align_to='color', capture_fps_requested=30)
            np.savetxt(output / 'K.txt', K, fmt='%.12g')
        report['mesh_sha256'] = mesh_selection['sha256']
        report['display_url'] = 'http://127.0.0.1:' + str(args.port)
        atomic_json(output / 'session.json', report)
        server = make_server('127.0.0.1', args.port, state, control, stop)
        mapped = '/data/' + output.relative_to(dataroot).as_posix()
        worker_command = ['/usr/bin/python3', str(root / 'setup/run_logged.py'), '--root', str(root),
                          '--label', 'cup_live_gpu_worker', '--note', report['source'] + '; metric candidate; no GT',
                          '--', 'docker', 'exec', '-w', '/workspace/FoundationPose', 'foundationpose',
                          '/opt/conda/envs/my/bin/python', '-B', '-u', mapped + '/worker_code/run_cup_live_worker.py',
                          '--session', mapped, '--repo', '/workspace/FoundationPose',
                          '--mesh', '/data/' + mesh_selection['relative'], '--mesh-sha256', mesh_selection['sha256']]
        report['worker_command'] = worker_command
        logstream = (output / 'worker_stdout.log').open('wb')
        worker = subprocess.Popen(worker_command, stdout=logstream, stderr=subprocess.STDOUT)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        print(json.dumps(dict(output=str(output), preview=report['display_url'], source=report['source'])), flush=True)
        deadline = time.monotonic() + 120
        while not (output / 'ready.json').exists():
            if worker.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('GPU worker failed to become ready; inspect worker_stdout.log')
            if stop.wait(0.1):
                break
        with state['lock']:
            state['state'] = 'waiting_for_roi' if not args.replay_scene or args.replay_wait_for_roi else 'offline_replay'
        frame_index, camera_count, replay_index = 0, 0, 0
        preview_time = 0
        previous_capture_time = None
        previous_operation = None
        run_started = time.monotonic()
        while not stop.is_set() and time.monotonic() - run_started < args.duration_seconds:
            if worker.poll() is not None:
                raise RuntimeError('GPU worker exited unexpectedly')
            if shutil.disk_usage(output).free < 1024 ** 3:
                raise RuntimeError('Output filesystem reached 1 GiB free; stop and retain records')
            if args.replay_scene:
                frame = dict(rgb=replay_rgb, depth=replay_depth, received_monotonic=time.monotonic(),
                             received_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                             source='offline_replay', source_frame=args.replay_frame,
                             rgb_sdk_timestamp_ms=None, depth_sdk_timestamp_ms=None)
                time.sleep(0.01)
            else:
                pair = align.process(pipeline.wait_for_frames(5000))
                color, depthframe = pair.get_color_frame(), pair.get_depth_frame()
                if not color or not depthframe:
                    continue
                aligned_intr = get_intrinsics(depthframe.profile)
                if (aligned_intr['width'] != 640 or aligned_intr['height'] != 480
                        or any(abs(aligned_intr[key] - color_intr[key]) > 1e-6 for key in ('fx', 'fy', 'cx', 'cy'))):
                    raise ValueError('Color and aligned-depth intrinsics mismatch')
                report['aligned_depth_intrinsics'] = aligned_intr
                converted, rejected = millimeter_depth(np.asanyarray(depthframe.get_data()), native_scale, np)
                color_time, depth_time = color.get_timestamp(), depthframe.get_timestamp()
                if color.get_frame_timestamp_domain() != depthframe.get_frame_timestamp_domain():
                    raise ValueError('RGB/depth timestamp domains differ')
                gap = abs(color_time - depth_time)
                if gap > 33.334:
                    report['timestamp_gap_rejected_frames'] = report.get('timestamp_gap_rejected_frames', 0) + 1
                    continue
                frame = dict(rgb=np.asanyarray(color.get_data()).copy(), depth=converted,
                             received_monotonic=time.monotonic(), received_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                             source='live_d435i', rgb_sdk_timestamp_ms=color_time, depth_sdk_timestamp_ms=depth_time,
                             rgb_depth_timestamp_gap_ms=gap, timestamp_domain=str(color.get_frame_timestamp_domain()),
                             rgb_frame_number=color.get_frame_number(), depth_frame_number=depthframe.get_frame_number(),
                             converted_depth_rejected_pixels=rejected)
                camera_count += 1
            with state['lock']:
                state['latest'] = frame
                if state['frozen'] is None and time.monotonic() - preview_time >= 0.1:
                    state['preview_jpeg'] = jpeg(frame['rgb'])
                    preview_time = time.monotonic()
            if pending is not None:
                responsepath = output / 'responses' / (pending['id'] + '.json')
                if not responsepath.exists():
                    if time.monotonic() - pending['submitted'] > 120:
                        raise RuntimeError('Timed out waiting for GPU response')
                    continue
                response = json.loads(responsepath.read_text(encoding='utf-8'))
                response['bridge_seconds'] = time.monotonic() - pending['submitted']
                response['host_receive_to_result_seconds'] = time.monotonic() - pending['capture']['received_monotonic']
                with records.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(response, allow_nan=False) + '\n')
                recorded_ids.add(pending['id'])
                with state['lock']:
                    if response['passed']:
                        report['completed_frames'] += 1
                        successful_times.append(time.monotonic())
                        state.update(completed=report['completed_frames'], pose=response['pose'], result_time=time.monotonic(),
                                     overlay_jpeg=jpeg(cv2.cvtColor(cv2.imread(str(output / 'frames' / pending['id'] / 'overlay.png')), cv2.COLOR_BGR2RGB)))
                        if len(successful_times) > 1:
                            state['processing_fps'] = (len(successful_times) - 1) / (successful_times[-1] - successful_times[0])
                        # A pause/freeze made during inference must not be undone by its response.
                        if state['state'] == 'initializing':
                            state.update(tracking=True, state='tracking_estimate_unverified')
                        previous_capture_time = pending['capture']['received_monotonic']
                        previous_operation = pending['operation']
                    else:
                        report['failed_frames'] += 1
                        state.update(failed=report['failed_frames'], tracking=False, state='needs_reinitialization', message=response.get('error', '推理失败'))
                        if args.replay_scene:
                            raise RuntimeError('Replay inference failed: ' + response.get('error', 'unknown'))
                pending = None
                atomic_json(output / 'session.json', report)
                if frame_index >= (min(args.replay_count, args.max_frames) if args.replay_scene else args.max_frames):
                    break
            with state['lock']:
                chosen_frame, operation = None, None
                if state['pending_register'] is not None:
                    chosen_frame, operation = state['pending_register'], 'register'
                    state['pending_register'] = None
                elif args.replay_scene and not args.replay_wait_for_roi and replay_index < args.replay_count:
                    chosen_frame, operation = dict(frame), 'register' if replay_index == 0 else 'track'
                    if operation == 'register':
                        chosen_frame['mask'] = replay_mask
                        chosen_frame['initialization'] = dict(method='accepted independent test mask; offline replay smoke only')
                    replay_index += 1
                elif state['tracking']:
                    if previous_operation == 'track' and previous_capture_time is not None and frame['received_monotonic'] - previous_capture_time > 2:
                        state.update(tracking=False, state='needs_reinitialization', message='处理帧间隔超过2秒，重新冻结框选')
                    else:
                        chosen_frame, operation = frame, 'track'
            if chosen_frame is not None:
                pending = save_request(chosen_frame, operation, frame_index)
                frame_index += 1
        report['capture_frames_seen'] = camera_count
        report['stop_reason'] = 'operator_stop' if stop.is_set() else 'session_limit'
    except Exception as error:
        failure = str(error)
        report.update(error=failure, traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        stop.set()
        (output / 'stop.flag').write_text('stop\n', encoding='utf-8')
        if pipeline is not None:
            try:
                pipeline.stop()
                report['pipeline_stopped'] = True
            except Exception as error:
                failure = failure or str(error)
                report['pipeline_stop_error'] = str(error)
        if server is not None:
            server.shutdown()
            server.server_close()
        if worker is not None:
            try:
                report['worker_exit_code'] = worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.terminate()
                failure = failure or 'GPU worker did not stop within 20 seconds'
                report['worker_stop_error'] = failure
            if report.get('worker_exit_code') not in (None, 0):
                failure = failure or 'GPU worker returned failure; see worker_report.json'
        # A user stop during inference still retains and indexes its final response.
        if pending is not None and pending['id'] not in recorded_ids:
            path = output / 'responses' / (pending['id'] + '.json')
            if path.exists():
                response = json.loads(path.read_text(encoding='utf-8'))
                response['bridge_seconds'] = time.monotonic() - pending['submitted']
                response['host_receive_to_result_seconds'] = time.monotonic() - pending['capture']['received_monotonic']
                response['drained_after_stop'] = True
                with records.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(response, allow_nan=False) + '\n')
                report['completed_frames' if response['passed'] else 'failed_frames'] += 1
        if logstream is not None:
            logstream.close()
        report.update(passed=failure is None and report['completed_frames'] > 0 and report['failed_frames'] == 0,
                      status='failed' if failure else 'stopped', elapsed_seconds=time.monotonic() - started,
                      ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        if failure:
            report['error'] = failure
        atomic_json(output / 'session.json', report)
        print(json.dumps(dict(passed=report['passed'], source=report['source'], completed=report['completed_frames'],
                              output=str(output), error=failure, accuracy_validated=False)), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
