#!/usr/bin/env python3
"""Logged latest-frame D435i bridge with optional independent same-RGB ArUco reference."""
import argparse
import csv
import datetime
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
import cv2
import numpy as np
from capture_d435i import get_device_info, get_intrinsics, millimeter_depth
from cup_live_dashboard import make_server
from cup_pose_quality import image_change
from cup_aruco_reference import ARUCO_DICTIONARIES, ArucoReference, rigid_error
from cup_sam_mask import generate_sam_mask, validate_prompts
from cup_sam2_mask import run_sam2
from cup_reacquisition import target_signature, choose_target, fresh_frame_check
from run_cup_live import MESH_RELATIVE, MESH_SHA256, atomic_json, sha
from cup_mesh_selection import add_mesh_arguments, resolve_mesh


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/data/ZJC/foundationPos'))
    p.add_argument('--output', type=Path)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--duration-seconds', type=float, default=600)
    p.add_argument('--max-frames', type=int, default=2000)
    add_mesh_arguments(p)
    p.add_argument('--cup-yaw-init', action='store_true', help='Experimental init-only mask/protrusion yaw check; redcup72 axes only')
    p.add_argument('--no-cup-yaw-init', dest='cup_yaw_init', action='store_false', help='Disable experimental cup yaw check for comparison')
    p.add_argument('--mask-backend', choices=('sam', 'sam2', 'grabcut'), default='sam', help='First-frame prompted segmentation backend')
    p.add_argument('--no-auto-reacquire', dest='auto_reacquire', action='store_false', help='Disable full-frame SAM2 search after loss')
    p.add_argument('--auto-reacquire', dest='auto_reacquire', action='store_true', help='Enable full-frame target reacquisition (default)')
    p.set_defaults(auto_reacquire=True)
    p.add_argument('--recovery-interval-seconds', type=float, default=3)
    p.add_argument('--aruco-marker-length-m', type=float, help='REQUIRED measured black outer square side in meters to enable ArUco')
    p.add_argument('--aruco-id', type=int, default=0)
    p.add_argument('--aruco-dictionary', choices=ARUCO_DICTIONARIES, default='DICT_4X4_50')
    p.add_argument('--aruco-fixed-scene', action='store_true', help='Protocol: cup and marker rigidly fixed; move only camera')
    p.add_argument('--no-aruco-fixed-scene', dest='aruco_fixed_scene', action='store_false', help='Track moving cup/marker without fixed-scene error metrics')
    p.add_argument('--marker-from-mesh', type=Path, help='Independently calibrated T_marker_from_original_mesh, meters; never fit to test poses')
    p.add_argument('--replay-scene', type=Path)
    p.add_argument('--replay-mask-dir', type=Path)
    p.add_argument('--replay-proof', type=Path)
    p.add_argument('--replay-frame', default='000004')
    p.add_argument('--replay-count', type=int, default=120)
    p.add_argument('--replay-wait-for-roi', action='store_true')
    p.add_argument('--replay-loss-test', action='store_true', help='Offline-only 6-second target absence injection after 12 processed frames')
    p.add_argument('--replay-return-shift-x', type=int, default=0, help='Offline loss test only: translated return image/depth, explicitly synthetic')
    p.add_argument('--replay-return-frame-dir', type=Path, help='Offline loss test only: actual saved RGB-D from another scene/view')
    args = p.parse_args()
    if args.cup_yaw_init and args.mesh_profile != 'redcup72':
        p.error('--cup-yaw-init requires --mesh-profile redcup72')
    if not 1 <= args.port <= 65535 or args.duration_seconds <= 0 or args.max_frames < 1 or args.replay_count < 1 or args.recovery_interval_seconds <= 0:
        p.error('Invalid port, duration or frame count')
    if len(args.replay_frame) != 6 or not args.replay_frame.isdigit():
        p.error('Replay frame must have six decimal digits')
    if not 0 <= args.aruco_id < (1024 if args.aruco_dictionary == 'DICT_ARUCO_ORIGINAL' else 50):
        p.error('Marker ID outside configured dictionary')
    if (args.aruco_fixed_scene or args.marker_from_mesh) and args.aruco_marker_length_m is None:
        p.error('ArUco evaluation requires measured marker side length')
    if bool(args.replay_scene) != bool(args.replay_mask_dir) or bool(args.replay_scene) != bool(args.replay_proof):
        p.error('Replay requires scene, accepted mask directory and proof together')
    if args.replay_loss_test and not args.replay_scene:
        p.error('Loss injection is offline-only')
    if args.replay_return_shift_x and (not args.replay_loss_test or abs(args.replay_return_shift_x) > 150):
        p.error('Return shift requires offline loss test and at most 150px')
    if args.replay_return_frame_dir and (not args.replay_loss_test or args.replay_return_shift_x):
        p.error('Real return frame requires offline loss test without synthetic pixel shift')
    return args


def main():
    args = arguments()
    root = args.root.resolve(strict=True)
    dataroot = (root / 'foundationpose_data').resolve(strict=True)
    mesh_selection = resolve_mesh(dataroot, args.mesh_profile)
    output = (args.output or dataroot / 'live_sessions' / ('cup_fast_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])).resolve()
    output.relative_to(dataroot)
    output.mkdir(parents=True, exist_ok=False)
    for name in ('frames', 'requests', 'responses', 'processing', 'worker_code'):
        (output / name).mkdir()
    state = dict(lock=threading.RLock(), state='loading', output=str(output), completed=0, failed=0,
                 message='加载模型；初始化及模型加载结束前保持相机与杯子停稳', latest=None, frozen=None,
                 candidate=None, pending_register=None, tracking=False, pose=None, revision=0, quality_rejected=0)
    state.update(segmentation_backend={'sam': 'SAM ViT-B', 'sam2': 'SAM2.1 Hiera Tiny', 'grabcut': 'GrabCut'}[args.mask_backend],
                 mask_busy=False, auto_busy=False, auto_result=None, target_reference=None, epoch=0,
                 confirmation_frames=0, pose_valid=False)
    report = dict(passed=False, status='starting', output=str(output),
                  source='offline_replay_30Hz_repeated_image' if args.replay_scene else 'live_d435i',
                  completed_frames=0, failed_frames=0, quality_rejected_frames=0,
                  pose_definition='T_camera_from_original_mesh_meters', camera_axes='OpenCV x right y down z forward',
                  pose_is_ground_truth=False, absolute_pose_accuracy_validated=False,
                  inputs='rgb.npy uint8 RGB and depth.npy uint16 millimeters, lossless authoritative pixels',
                  display='overlay.jpg is lossy display only; never used as inference/reference input',
                  skipped_capture_frames_are_not_saved=True, capture_fps_requested=30,
                  official_tracking_iterations=2, official_registration_iterations=5,
                  segmentation_backend=args.mask_backend,
                  automatic_reacquisition=args.auto_reacquire, recovery_attempts=0, recovery_confirmations_required=3,
                  aruco=dict(enabled=args.aruco_marker_length_m is not None, dictionary=args.aruco_dictionary, marker_id=args.aruco_id,
                             measured_black_side_m=args.aruco_marker_length_m, fixed_scene=args.aruco_fixed_scene,
                             independently_calibrated_marker_from_mesh=str(args.marker_from_mesh) if args.marker_from_mesh else None),
                  code_sha256={}, note=os.environ.get('FP_RUN_NOTE', ''))
    report.update(mesh_profile=args.mesh_profile, mesh_path=mesh_selection['path'], mesh_selection=mesh_selection)
    report['cup_yaw_initialization']=args.cup_yaw_init
    report['synthetic_target_absence_test'] = args.replay_loss_test
    report['synthetic_return_shift_x_px'] = args.replay_return_shift_x
    state.update(loss_test_started=None, loss_test_done=False)
    state['aruco_settings'] = report['aruco']
    reference = ArucoReference(args.aruco_marker_length_m, args.aruco_id, dictionary=args.aruco_dictionary, fixed_scene=args.aruco_fixed_scene,
                              marker_from_mesh=np.loadtxt(args.marker_from_mesh) if args.marker_from_mesh else None) if args.aruco_marker_length_m is not None else None
    if args.marker_from_mesh:
        shutil.copy2(args.marker_from_mesh, output / 'independent_marker_from_mesh.txt')
        report['aruco']['calibration_sha256'] = sha(output / 'independent_marker_from_mesh.txt')
    stop = threading.Event()
    capture_errors = []
    pipeline = server = worker = logstream = capture_thread = None
    pending = None
    failure = None
    sequence = 0
    started = time.monotonic()
    completed_times, track_times = [], []
    track_segments = []
    auto_thread = None
    last_search = 0.
    indexed = set()
    K = replay_rgb = replay_depth = replay_mask = None
    return_rgb = return_depth = None

    def jpeg(rgb):
        ok, data = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError('Preview encode failed')
        return data.tobytes()

    def control(path, value):
        with state['lock']:
            if path == '/freeze':
                if state['latest'] is None or pending is not None or state['mask_busy']:
                    raise ValueError('等待当前帧完成，再冻结画面')
                state.update(tracking=False, frozen=state['latest'], candidate=None, state='selecting_roi', pose=None, pose_valid=False,
                             reference_evaluation=dict(reason='paused for mask selection'))
                state['preview_jpeg'] = jpeg(state['frozen']['rgb'])
                state['revision'] += 1
                message = '保持相机、杯子不动；框选完整杯身和杯把'
            elif path == '/mask':
                frozen = state['frozen']
                rect = value.get('rect')
                if frozen is None or state['tracking'] or state['pending_register'] is not None or state['mask_busy'] or state['auto_busy']:
                    raise ValueError('先冻结画面')
                points, labels = value.get('points', []), value.get('labels', [])
                validate_prompts(rect, points, labels)
                state['candidate'] = None
                if args.mask_backend in ('sam', 'sam2'):
                    revision = state['revision']
                    state.update(mask_busy=True, message='SAM分割中；保持相机和杯子停稳')
                    state['lock'].release()
                    try:
                        if args.mask_backend == 'sam2':
                            binary, mask_metadata = run_sam2(root, output, frozen['rgb'], rect, points, labels, frozen)
                        else:
                            binary, mask_metadata = generate_sam_mask(root, output, frozen['rgb'], rect, points, labels, frozen)
                    except Exception as error:
                        state['lock'].acquire()
                        state['message'] = str(error)
                        state['lock'].release()
                        raise
                    finally:
                        state['lock'].acquire()
                        state['mask_busy'] = False
                    if state['revision'] != revision or stop.is_set():
                        raise ValueError('分割期间状态改变；结果已留档，请重新冻结')
                else:
                    mask = np.zeros((480, 640), np.uint8)
                    cv2.grabCut(frozen['rgb'], mask, tuple(rect), np.zeros((1, 65)), np.zeros((1, 65)), 5, cv2.GC_INIT_WITH_RECT)
                    binary = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8) * 255
                    mask_metadata = dict(backend='GrabCut', mask_is_ground_truth=False)
                if np.count_nonzero((binary > 0) & (frozen['depth'] > 0)) < 100:
                    raise ValueError('框内有效深度不足，调整摆放或框选')
                candidate_id = uuid.uuid4().hex
                state['candidate'] = dict(mask=binary, rectangle=rect, points=points, labels=labels, metadata=mask_metadata, id=candidate_id)
                state['candidate_id'] = candidate_id
                vis = frozen['rgb'].copy()
                selected = binary > 0
                vis[selected] = (0.65 * vis[selected] + 0.35 * np.array([255, 220, 0])).astype(np.uint8)
                cv2.drawContours(vis, cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2], -1, (255, 255, 0), 1)
                state['preview_jpeg'] = jpeg(vis)
                message = '检查黄色Mask；漏选可加前景点，误选可加背景点，再生成。检查通过后初始化'
            elif path == '/initialize':
                if state['candidate'] is None or state['frozen'] is None or pending is not None:
                    raise ValueError('先冻结并生成Mask')
                if args.mask_backend in ('sam', 'sam2') and value.get('candidate_id') != state['candidate']['id']:
                    raise ValueError('提示已改变或Mask版本过期，请重新生成Mask')
                frozen = state['frozen']
                check = image_change(frozen['rgb'], state['latest']['rgb'], state['candidate']['mask'])
                check['motion'] = fresh_frame_check(frozen['rgb'], state['latest']['rgb'], state['candidate']['mask'])
                check['consistent'] = check['consistent'] and check['motion']['consistent']
                with (output / 'initialization_checks.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(dict(stage='before_register', check=check)) + '\n')
                if not check['consistent']:
                    raise ValueError('冻结后画面变化明显；停稳相机和杯子，重新冻结、框选')
                frame = dict(frozen, mask=state['candidate']['mask'].copy(),
                             initialization=dict(method='same frozen RGB + ' + state['segmentation_backend'], roi=state['candidate']['rectangle'],
                                                 points=state['candidate']['points'], labels=state['candidate']['labels'],
                                                 segmentation=state['candidate']['metadata'], mask_is_ground_truth=False))
                state.update(pending_register=frame, frozen=None, candidate=None, tracking=False, state='initializing')
                state.update(epoch=state['epoch'] + 1, confirmation_frames=0, pose=None, pose_valid=False,
                             reference_evaluation=dict(reason='initialization pending confirmation'))
                state['revision'] += 1
                message = '初始化中；右侧结果出现且状态进入跟踪后，再移动相机'
            elif path == '/pause':
                state.update(tracking=False, state='paused', pending_register=None, pose=None, pose_valid=False,
                             reference_evaluation=dict(reason='tracking paused'))
                state['revision'] += 1
                message = '已暂停；冻结并重新框选可初始化，ArUco误差参考首帧保持不变'
            elif path == '/stop':
                stop.set()
                message = '停止并保存全部已提交帧、误差和运行证据'
            state['message'] = message
            with (output / 'controls.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(time_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), action=path, input=value), ensure_ascii=False) + '\n')
            return message

    def acquire():
        nonlocal sequence
        next_tick = time.monotonic()
        try:
            while not stop.is_set():
                if args.replay_scene:
                    if stop.wait(max(0, next_tick - time.monotonic())):
                        break
                    next_tick = max(next_tick + 1 / 30, time.monotonic())
                    frame = dict(rgb=replay_rgb, depth=replay_depth, source=report['source'],
                                 source_frame=args.replay_frame, rgb_sdk_timestamp_ms=None, depth_sdk_timestamp_ms=None)
                    if args.replay_loss_test:
                        with state['lock']:
                            if state['completed'] >= 12 and state['loss_test_started'] is None:
                                state['loss_test_started'] = time.monotonic()
                            absence = state['loss_test_started'] is not None and time.monotonic() - state['loss_test_started'] < 6
                        if absence:
                            frame.update(rgb=np.full_like(replay_rgb, 90), depth=np.full_like(replay_depth, 1500),
                                         source='synthetic_uniform_background_target_absence')
                        elif state['loss_test_started'] is not None:
                            state['loss_test_done'] = True
                            if return_rgb is not None:
                                frame.update(rgb=return_rgb, depth=return_depth, source='actual_saved_RGBD_return_view')
                            elif args.replay_return_shift_x:
                                matrix = np.float32([[1, 0, args.replay_return_shift_x], [0, 1, 0]])
                                frame.update(rgb=cv2.warpAffine(replay_rgb, matrix, (640, 480), borderValue=(90, 90, 90)),
                                             depth=cv2.warpAffine(replay_depth, matrix, (640, 480), flags=cv2.INTER_NEAREST, borderValue=1500),
                                             source='synthetic_shifted_return_from_saved_RGBD')
                else:
                    pair = align.process(pipeline.wait_for_frames(5000))
                    color, depthframe = pair.get_color_frame(), pair.get_depth_frame()
                    if not color or not depthframe:
                        continue
                    gap = abs(color.get_timestamp() - depthframe.get_timestamp())
                    if color.get_frame_timestamp_domain() != depthframe.get_frame_timestamp_domain() or gap > 1000 / 30 + .001:
                        raise ValueError('RGB/depth SDK timestamp pairing invalid')
                    if get_intrinsics(depthframe.profile) != report['color_intrinsics']:
                        raise ValueError('Aligned depth intrinsics differ from RGB')
                    raw, rejected = millimeter_depth(np.asanyarray(depthframe.get_data()), native_scale, np)
                    frame = dict(rgb=np.asanyarray(color.get_data()).copy(), depth=raw, source=report['source'],
                                 rgb_sdk_timestamp_ms=color.get_timestamp(), depth_sdk_timestamp_ms=depthframe.get_timestamp(),
                                 rgb_depth_timestamp_gap_ms=gap, timestamp_domain=str(color.get_frame_timestamp_domain()),
                                 rgb_frame_number=color.get_frame_number(), depth_frame_number=depthframe.get_frame_number(),
                                 converted_depth_rejected_pixels=rejected)
                sequence += 1
                frame.update(sequence=sequence, received_monotonic=time.monotonic(), received_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                with state['lock']:
                    state['latest'] = frame
        except Exception as error:
            if not stop.is_set():
                capture_errors.append(str(error))
                stop.set()

    def submit(frame, operation, index):
        identifier = '%06d' % index
        folder = output / 'frames' / identifier
        folder.mkdir()
        np.save(str(folder / 'rgb.npy'), frame['rgb'], allow_pickle=False)
        np.save(str(folder / 'depth.npy'), frame['depth'], allow_pickle=False)
        atomic_json(folder / 'capture.json', {k: v for k, v in frame.items() if k not in ('rgb', 'depth', 'mask')})
        names = ['rgb.npy', 'depth.npy', 'capture.json']
        aruco = reference.detect(frame['rgb'], K) if reference else dict(found=False, reference_accepted=False, reason='ArUco disabled')
        state['aruco_status'] = dict(aruco, source_frame=identifier)
        atomic_json(folder / 'aruco.json', aruco)
        names.append('aruco.json')
        if operation == 'register':
            if not cv2.imwrite(str(folder / 'mask.png'), frame['mask']):
                raise RuntimeError('Initialization mask write failed')
            names.append('mask.png')
        request = dict(operation=operation, K=K.tolist(), frame=identifier,
                       input_sha256={name: sha(folder / name) for name in names}, source=report['source'], saved_depth_unit='millimeter',
                       tracking_epoch=state['epoch'], target_reference=state['target_reference'] or
                       (target_signature(frame['rgb'], frame['mask'], frame['depth'], K) if operation == 'register' else None))
        atomic_json(output / 'requests' / (identifier + '.json'), request)
        return dict(id=identifier, capture=frame, operation=operation, submitted=time.monotonic(), revision=state['revision'], aruco=aruco,
                    target_reference=request['target_reference'])

    def record_response(item, response, drained=False):
        folder = output / 'frames' / item['id']
        accepted = bool(response['passed'] and response.get('tracking_consistent', False))
        if accepted and item['operation'] == 'register':
            with state['lock']:
                latest = state['latest']
            check = image_change(item['capture']['rgb'], latest['rgb'], item['capture']['mask'])
            check['motion'] = fresh_frame_check(item['capture']['rgb'], latest['rgb'], item['capture']['mask'])
            check['consistent'] = check['consistent'] and check['motion']['consistent']
            response['initialization_current_frame_check'] = check
            accepted = check['consistent']
            if reference and args.aruco_fixed_scene and item['aruco'].get('reference_accepted'):
                latest_marker = reference.detect(latest['rgb'], K)
                if latest_marker.get('reference_accepted'):
                    movement = rigid_error(np.array(latest_marker['pose_camera_from_marker']), np.array(item['aruco']['pose_camera_from_marker']))
                    response['initialization_marker_movement_check'] = movement
                    accepted = accepted and movement['translation_error_mm'] <= 5 and movement['rotation_error_deg'] <= 2
        response.update(accepted_for_tracking=accepted, drained_after_stop=drained,
                        bridge_seconds=time.monotonic() - item['submitted'],
                        host_receive_to_result_seconds=time.monotonic() - item['capture']['received_monotonic'])
        current = item['revision'] == state['revision'] and not drained
        response.update(accepted_for_tracking=bool(accepted and current), state_revision_current=current)
        if drained:
            response['acceptance_reason'] = 'drained_after_stop'
        elif not current:
            response['acceptance_reason'] = 'superseded_by_operator_control'
        elif not response['passed']:
            response['acceptance_reason'] = 'inference_failed'
        elif not response.get('tracking_consistent'):
            response['acceptance_reason'] = 'mesh_depth_or_appearance_guard_rejected'
        elif not accepted:
            response['acceptance_reason'] = 'registration_current_frame_or_marker_motion_rejected'
        else:
            response['acceptance_reason'] = 'accepted'
        if accepted and current:
            if item['operation'] == 'register':
                state['confirmation_frames'] = 0
                track_times.clear()
                track_segments.append([])
                state['processing_fps'] = 0.
            else:
                state['confirmation_frames'] += 1
        confirmed = bool(accepted and current and state['confirmation_frames'] >= 3)
        response['pose_confirmed'] = confirmed
        if accepted and current:
            response['acceptance_reason'] = 'accepted_confirmed' if confirmed else 'accepted_pending_confirmation'
        evaluation = reference.evaluate(np.array(response['pose']), item['aruco'], item['id'], confirmed) if reference and response['passed'] else dict(relative_errors=None, absolute_errors=None, reason='reference disabled or inference failed')
        response['reference_evaluation'] = evaluation
        atomic_json(folder / 'reference_evaluation.json', evaluation)
        # Worker result.json remains the immutable GPU result; host_result adds bridge/ref checks.
        atomic_json(folder / 'host_result.json', response)
        with (output / 'frame_events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(response, allow_nan=False) + '\n')
        fields = ['frame', 'operation', 'inference_passed', 'tracking_consistent', 'reference_found', 'reference_accepted', 'anchor_frame', 'relative_translation_mm', 'relative_rotation_deg', 'anchored_object_translation_mm', 'anchored_object_rotation_deg', 'absolute_translation_mm', 'absolute_rotation_deg', 'host_latency_ms']
        row = dict(frame=item['id'], operation=item['operation'], inference_passed=response['passed'], tracking_consistent=accepted,
                   reference_found=item['aruco']['found'], reference_accepted=item['aruco']['reference_accepted'], anchor_frame=evaluation.get('anchor_frame'),
                   host_latency_ms=response['host_receive_to_result_seconds'] * 1000)
        for scope in ('relative', 'anchored_object', 'absolute'):
            error = evaluation.get(scope + '_errors') or {}
            row[scope + '_translation_mm'] = error.get('translation_error_mm')
            row[scope + '_rotation_deg'] = error.get('rotation_error_deg')
        csvpath = output / 'aruco_errors.csv'
        first = not csvpath.exists()
        with csvpath.open('a', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            if first:
                writer.writeheader()
            writer.writerow(row)
        indexed.add(item['id'])
        with state['lock']:
            if response['passed']:
                report['completed_frames'] += 1
                completed_times.append(time.monotonic())
                if item['operation'] == 'track' and current and accepted:
                    track_times.append(time.monotonic())
                    if track_segments:
                        track_segments[-1].append(track_times[-1])
                state.update(completed=report['completed_frames'])
                if confirmed and item['revision'] == state['revision'] and not drained:
                    state.update(pose=response['pose'], pose_valid=True, result_time=time.monotonic(),
                                 overlay_jpeg=(folder / response['overlay_file']).read_bytes(), reference_evaluation=evaluation)
                if len(track_times) > 1:
                    state['processing_fps'] = (len(track_times) - 1) / (track_times[-1] - track_times[0])
                if not accepted:
                    report['quality_rejected_frames'] += 1
                    state['quality_rejected'] = report['quality_rejected_frames']
            else:
                report['failed_frames'] += 1
                state['failed'] = report['failed_frames']
            if item['revision'] == state['revision'] and not drained:
                if not accepted:
                    state.update(tracking=False, state='needs_reinitialization', pose=None, pose_valid=False, confirmation_frames=0,
                                 processing_fps=0., reference_evaluation=dict(reason='target missing or pose rejected', relative_errors=None, absolute_errors=None),
                                 message='目标丢失或当前结果未通过检查；自动搜索原目标，重新出现后请短暂停稳')
                else:
                    if state['target_reference'] is None and item['operation'] == 'register':
                        state['target_reference'] = item['target_reference']
                        atomic_json(output / 'target_reference.json', dict(reference=state['target_reference'], source_frame=item['id']))
                    state.update(tracking=True, state='tracking_estimate_unverified' if confirmed else 'verifying_reacquisition',
                                 message='正在跟踪，姿态精度未验证' if confirmed else '新姿态验证中；连续3帧通过后恢复显示')

    def search_target(frame, revision):
        try:
            masks, metadata = run_sam2(root, output, frame['rgb'], capture=frame, mode='search', depth=frame['depth'])
            selected, check = choose_target(state['target_reference'], frame['rgb'], frame['depth'], K, masks, metadata['candidates'])
            attempt = output / metadata['attempt']
            atomic_json(attempt / 'target_selection.json', dict(check=check, reference=state['target_reference']))
            result = dict(revision=revision, frame=frame, metadata=metadata, check=check,
                          mask=masks[selected].astype(np.uint8) * 255 if selected is not None else None)
        except Exception as error:
            result = dict(revision=revision, error=str(error), mask=None)
        with state['lock']:
            state.update(auto_result=result, auto_busy=False)
            with (output / 'recovery_events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(event='search_result', time_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    revision=revision, source_sequence=frame['sequence'], matched=result['mask'] is not None,
                    metadata=result.get('metadata'), selection=result.get('check'), error=result.get('error'))) + '\n')

    try:
        if sha(Path(mesh_selection['path'])) != mesh_selection['sha256']:
            raise ValueError('Metric mesh SHA mismatch')
        if args.auto_reacquire or args.mask_backend == 'sam2':
            for path in (dataroot / 'environments/sam2/bin/python', dataroot / 'checkpoints/sam2/installation.json'):
                if not path.is_file():
                    raise RuntimeError('SAM2 environment is unavailable: ' + str(path) + '; provision with setup/provision_cup_sam2.py')
        for name in ('run_cup_live_fast.py', 'run_cup_live_worker.py', 'run_cup_live.py', 'run_cup_live_fast.sh',
                     'cup_live_dashboard.py', 'cup_mesh_selection.py', 'cup_handle_yaw.py', 'cup_sam_mask.py', 'cup_sam_worker.py', 'cup_sam2_mask.py', 'cup_sam2_worker.py', 'sam2_runtime_environment.py', 'cup_reacquisition.py', 'capture_d435i.py', 'cup_pose_quality.py', 'cup_aruco_reference.py', 'summarize_cup_aruco_session.py', 'run_cup_mesh_inference.py', 'verify_demo.py'):
            shutil.copy2(root / 'setup' / name, output / 'worker_code' / name)
            report['code_sha256'][name] = sha(output / 'worker_code' / name)
        report['mesh_sha256'] = mesh_selection['sha256']
        report['opencv_version'] = cv2.__version__
        if args.replay_scene:
            proof = json.loads(args.replay_proof.read_text(encoding='utf-8'))
            if not proof.get('passed'):
                raise ValueError('Replay proof did not pass')
            selected = next(item for item in proof['frames'] if item['id'] == args.replay_frame)
            paths = dict(rgb=args.replay_scene / 'rgb' / (args.replay_frame + '.png'), depth=args.replay_scene / 'depth' / (args.replay_frame + '.png'), mask=args.replay_mask_dir / 'masks' / (args.replay_frame + '.png'))
            for name, path in paths.items():
                if sha(path) != selected['inputs'][name]['sha256']:
                    raise ValueError('Replay input differs from accepted proof')
            replay_rgb = cv2.cvtColor(cv2.imread(str(paths['rgb'])), cv2.COLOR_BGR2RGB)
            replay_depth = cv2.imread(str(paths['depth']), cv2.IMREAD_UNCHANGED)
            replay_mask = cv2.imread(str(paths['mask']), cv2.IMREAD_UNCHANGED)
            K = np.loadtxt(args.replay_scene / 'cam_K.txt').reshape(3, 3)
            if not np.allclose(K, proof['camera_matrix'], atol=1e-7, rtol=0) or replay_depth.dtype != np.uint16:
                raise ValueError('Replay intrinsics or millimeter format differ')
            report.update(K=K.tolist(), camera_connected=False, replay_repeats_same_image=not args.replay_loss_test, replay_proof_sha256=sha(args.replay_proof))
            if args.replay_return_frame_dir:
                folder = args.replay_return_frame_dir.resolve(strict=True)
                folder.relative_to(dataroot)
                return_rgb = np.load(folder / 'rgb.npy', allow_pickle=False)
                return_depth = np.load(folder / 'depth.npy', allow_pickle=False)
                if return_rgb.shape != replay_rgb.shape or return_depth.shape != replay_depth.shape or return_depth.dtype != np.uint16:
                    raise ValueError('Return view format differs')
                if not np.allclose(np.loadtxt(folder.parent.parent / 'K.txt').reshape(3, 3), K, atol=1e-7, rtol=0):
                    raise ValueError('Return-view K differs')
                report['return_view'] = dict(folder=str(folder), rgb_sha256=sha(folder / 'rgb.npy'), depth_sha256=sha(folder / 'depth.npy'))
        else:
            import pyrealsense2 as rs
            devices = list(rs.context().query_devices())
            chosen = next((d for d in devices if 'D435I' in d.get_info(rs.camera_info.name).upper()), None)
            if chosen is None:
                raise RuntimeError('Attach D435i to Ubuntu USB 3 before starting')
            report['device'] = get_device_info(rs, chosen)
            if not str(report['device'].get('usb_type_descriptor', '')).startswith('3'):
                raise ValueError('D435i requires USB 3')
            config = rs.config(); config.enable_device(report['device']['serial_number'])
            config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
            config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
            pipeline = rs.pipeline(); profile = pipeline.start(config)
            native_scale = float(profile.get_device().first_depth_sensor().get_depth_scale())
            align = rs.align(rs.stream.color)
            intrinsics = get_intrinsics(profile.get_stream(rs.stream.color))
            if any(abs(v) > 1e-12 for v in intrinsics['distortion_coefficients']):
                raise ValueError('This entry requires native zero-distortion RGB pinhole profile')
            K = np.array([[intrinsics['fx'], 0, intrinsics['cx']], [0, intrinsics['fy'], intrinsics['cy']], [0, 0, 1]])
            for _ in range(30):
                pipeline.wait_for_frames(5000)
            report.update(camera_connected=True, color_intrinsics=intrinsics, K=K.tolist(), native_depth_scale_m=native_scale,
                          align_to='color', saved_depth_scale_m=.001, sdk_version=importlib.metadata.version('pyrealsense2'))
        np.savetxt(output / 'K.txt', K, fmt='%.12g')
        atomic_json(output / 'session.json', report)
        capture_thread = threading.Thread(target=acquire, daemon=True)
        capture_thread.start()
        server = make_server('127.0.0.1', args.port, state, control, stop)
        mapped = '/data/' + output.relative_to(dataroot).as_posix()
        command = ['/usr/bin/python3', str(root / 'setup/run_logged.py'), '--root', str(root), '--label', 'cup_live_fast_gpu_worker',
                   '--note', report['source'] + '; official pretrained; two track iterations; no GT', '--', 'docker', 'exec', '-w',
                   '/workspace/FoundationPose', 'foundationpose', '/opt/conda/envs/my/bin/python', '-B', '-u', mapped + '/worker_code/run_cup_live_worker.py',
                   '--session', mapped, '--repo', '/workspace/FoundationPose', '--mesh', '/data/' + mesh_selection['relative'], '--mesh-sha256', mesh_selection['sha256'], '--fast']
        if args.cup_yaw_init:
            command.append('--cup-yaw-init')
        report['worker_command'] = command
        logstream = (output / 'worker_stdout.log').open('wb')
        worker = subprocess.Popen(command, stdout=logstream, stderr=subprocess.STDOUT)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        print(json.dumps(dict(output=str(output), preview='http://127.0.0.1:' + str(args.port), source=report['source'])), flush=True)
        deadline = time.monotonic() + 120
        while not (output / 'ready.json').exists() and not stop.is_set():
            if worker.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('GPU worker not ready; see worker_stdout.log')
            stop.wait(.05)
        state.update(state='waiting_for_roi', message='模型与图像已就绪；请冻结画面、框选杯子和杯把、生成Mask并确认初始化')
        index, last_submitted_sequence = 0, -1
        run_started = time.monotonic(); preview_time = disk_time = 0
        while not stop.is_set() and time.monotonic() - run_started < args.duration_seconds:
            if worker.poll() is not None:
                raise RuntimeError('GPU worker exited unexpectedly')
            if time.monotonic() - disk_time > 2:
                disk_time = time.monotonic()
                if shutil.disk_usage(output).free < 1024 ** 3:
                    raise RuntimeError('Output filesystem reached 1GiB free')
            with state['lock']:
                frame = state['latest']
            if frame is None:
                stop.wait(.001); continue
            if state['frozen'] is None and time.monotonic() - preview_time >= .1:
                display = frame['rgb']
                # Before initialization, expose reference visibility on native RGB.
                # This display check never anchors or contributes an error sample.
                if reference and not state['tracking'] and pending is None:
                    marker = reference.detect(frame['rgb'], K)
                    state['aruco_status'] = dict(marker, source_frame='preview:' + str(frame['sequence']))
                    if marker.get('found'):
                        display = display.copy()
                        color = (0, 255, 80) if marker['reference_accepted'] else (255, 140, 0)
                        cv2.polylines(display, [np.array(marker['corners_px'], np.int32)], True, color, 2)
                data = jpeg(display)
                with state['lock']:
                    if state['frozen'] is None:
                        state['preview_jpeg'] = data
                preview_time = time.monotonic()
            if pending is not None:
                responsepath = output / 'responses' / (pending['id'] + '.json')
                if not responsepath.exists():
                    if time.monotonic() - pending['submitted'] > 120:
                        raise RuntimeError('GPU response timeout')
                    stop.wait(.001); continue
                record_response(pending, json.loads(responsepath.read_text(encoding='utf-8')))
                pending = None
                atomic_json(output / 'session.json', report)
                if index >= (min(args.max_frames, args.replay_count) if args.replay_scene else args.max_frames):
                    break
            with state['lock']:
                chosen, operation = None, None
                result = state['auto_result']
                if result is not None:
                    state['auto_result'] = None
                    if result['revision'] == state['revision'] and state['state'] == 'searching_target':
                        motion = fresh_frame_check(result['frame']['rgb'], frame['rgb'], result['mask']) if result['mask'] is not None else None
                        with (output / 'recovery_events.jsonl').open('a', encoding='utf-8') as stream:
                            stream.write(json.dumps(dict(event='search_consumed', time_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                revision=state['revision'], attempt=result.get('metadata', {}).get('attempt'), motion=motion,
                                queued_for_registration=bool(motion and motion['consistent']))) + '\n')
                        if motion and motion['consistent']:
                            state.update(pending_register=dict(result['frame'], mask=result['mask'],
                                initialization=dict(method='automatic full-frame SAM2 proposals + initial target appearance/size gates',
                                                    segmentation=result['metadata'], selection=result['check'], motion=motion, mask_is_ground_truth=False)),
                                         epoch=state['epoch'] + 1, confirmation_frames=0, state='initializing', pose=None, pose_valid=False,
                                         message='已找到匹配候选，正在重新估计位姿；请保持停稳，随后连续3帧验证通过才恢复显示')
                        else:
                            if result.get('error'):
                                message = '搜索失败，证据已保存：' + result['error']
                            elif result['mask'] is None:
                                message = '尚无明确匹配候选；请让完整杯身和杯把重新入镜'
                            else:
                                flow = motion.get('median_flow_px') if motion else None
                                detail = ('（搜索期间位移中位%.1f像素，门限3像素）' % flow) if flow is not None else '（可跟踪特征不足）'
                                message = '已找到匹配候选，但画面仍变化' + detail + '；请连续停稳约5秒，系统会继续自动尝试'
                            state.update(state='needs_reinitialization', message=message)
                if (args.auto_reacquire and state['target_reference'] is not None and state['state'] == 'needs_reinitialization'
                        and pending is None and not state['auto_busy'] and time.monotonic() - last_search >= args.recovery_interval_seconds):
                    last_search = time.monotonic()
                    report['recovery_attempts'] += 1
                    state.update(state='searching_target', auto_busy=True, pose=None, pose_valid=False,
                                 message='全图搜索原目标；请让完整杯子入镜并停稳，候选检查和位姿注册需要数秒')
                    auto_thread = threading.Thread(target=search_target, args=(frame, state['revision']), daemon=True)
                    auto_thread.start()
                if state['pending_register'] is not None:
                    chosen, operation = state['pending_register'], 'register'
                    state['pending_register'] = None
                elif args.replay_scene and not args.replay_wait_for_roi and index == 0:
                    chosen = dict(frame, mask=replay_mask, initialization=dict(method='accepted heldout mask; repeated offline smoke'))
                    operation = 'register'; state['state'] = 'initializing'
                elif state['tracking'] and frame['sequence'] > last_submitted_sequence:
                    if pending is None and index and previous_operation == 'track' and frame['received_monotonic'] - previous_capture > 2:
                        state.update(tracking=False, state='needs_reinitialization', pose=None, pose_valid=False, processing_fps=0.,
                                     message='处理帧间隔超过2秒；搜索原目标并重新注册')
                    else:
                        chosen, operation = frame, 'track'
                if chosen is not None:
                    pending = submit(chosen, operation, index)
                    last_submitted_sequence = chosen['sequence']; previous_capture = chosen['received_monotonic']; previous_operation = operation; index += 1
            stop.wait(.001)
        report['stop_reason'] = 'operator_stop' if stop.is_set() else 'session_limit'
        if capture_errors:
            raise RuntimeError('Camera acquisition failed: ' + capture_errors[0])
    except Exception as error:
        failure = str(error)
        report.update(error=failure, traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        stop.set(); (output / 'stop.flag').write_text('stop\n', encoding='utf-8')
        if capture_thread is not None:
            capture_thread.join(timeout=6)
        if auto_thread is not None:
            auto_thread.join(timeout=110)
        if pipeline is not None:
            try:
                pipeline.stop(); report['pipeline_stopped'] = True
            except Exception as error:
                failure = failure or str(error)
        if server is not None:
            server.shutdown(); server.server_close()
            mask_deadline = time.monotonic() + 125
            while state['mask_busy'] and time.monotonic() < mask_deadline:
                time.sleep(.05)
        if worker is not None:
            try:
                report['worker_exit_code'] = worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.terminate(); failure = failure or 'GPU worker stop timeout'
            if report.get('worker_exit_code') not in (None, 0):
                failure = failure or 'GPU worker failed; inspect worker report'
        if pending is not None and pending['id'] not in indexed:
            path = output / 'responses' / (pending['id'] + '.json')
            if path.exists():
                record_response(pending, json.loads(path.read_text(encoding='utf-8')), drained=True)
        if logstream is not None:
            logstream.close()
        report.update(passed=failure is None and report['completed_frames'] > 0 and report['failed_frames'] == 0,
                      status='failed' if failure else 'stopped', error=failure, capture_frames_seen=sequence,
                      elapsed_seconds=time.monotonic() - started, ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      steady_processing_fps=(sum(len(v)-1 for v in track_segments if len(v)>1) /
                          sum(v[-1]-v[0] for v in track_segments if len(v)>1)) if any(len(v)>1 for v in track_segments) else None,
                      fps_scope='weighted continuous tracking segments; excludes search/pause/reinitialization')
        atomic_json(output / 'session.json', report)
        if (output / 'frame_events.jsonl').exists():
            summary_command = ['/usr/bin/python3', str(root / 'setup/run_logged.py'), '--root', str(root),
                               '--label', 'cup_aruco_session_error_summary', '--note', 'All attempts and reference coverage; first-frame bias is excluded, not absolute GT',
                               '--', sys.executable, '-B', str(output / 'worker_code/summarize_cup_aruco_session.py'),
                               '--session', str(output), '--output', str(output / 'evaluation_summary')]
            summary_exit = subprocess.run(summary_command, check=False).returncode
            atomic_json(output / 'summary_status.json', dict(exit_code=summary_exit, passed=summary_exit == 0))
            if summary_exit:
                report.update(passed=False, status='failed', error=failure or 'Session summary failed; see child run records')
        print(json.dumps(dict(passed=report['passed'], completed=report['completed_frames'], quality_rejected=report['quality_rejected_frames'],
                              source=report['source'], steady_fps=report['steady_processing_fps'], output=str(output), error=failure)), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
