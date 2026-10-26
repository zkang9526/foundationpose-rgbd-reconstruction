"""Minimal, short dual-IR capture; run only after the camera is released.

Requests native IR1 and IR2 Y8 640x480 at 30 Hz, without RGB, depth or align.
The only sensor option changed is a temporary emitter OFF, restored in finally.
No camera calibration table or preset is written. A user report of a stationary
setup is kept separately from automated temporal validation (not performed).
"""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

import cv2
import numpy as np
import pyrealsense2 as rs

from common import extrinsic, intrinsic


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def stats(values):
    a = np.asarray(values, dtype=float)
    if not a.size or not np.isfinite(a).all():
        raise ValueError('Missing/nonfinite statistic')
    return dict(n=int(a.size), mean=float(a.mean()), median=float(np.median(a)),
                p95=float(np.percentile(a, 95)), rms=float(np.sqrt(np.mean(a*a))),
                std_population=float(a.std()), minimum=float(a.min()), maximum=float(a.max()))


def options(sensor, names):
    result = {}
    for name in names:
        option = getattr(rs.option, name, None)
        if option is None:
            result[name] = dict(supported=False)
            continue
        try:
            if sensor.supports(option):
                result[name] = dict(supported=True, value=float(sensor.get_option(option)))
            else:
                result[name] = dict(supported=False)
        except Exception as error:
            result[name] = dict(read_error=str(error))
    return result


def profile_info(profile):
    video = profile.as_video_stream_profile()
    return dict(stream=str(profile.stream_type()), stream_index=profile.stream_index(),
                format=str(profile.format()), fps=profile.fps(), unique_id=profile.unique_id(),
                width=video.width(), height=video.height(), intrinsics=intrinsic(profile))


def frame_info(frame):
    result = dict(number=int(frame.get_frame_number()), sdk_timestamp_ms=float(frame.get_timestamp()),
                  timestamp_domain=str(frame.get_frame_timestamp_domain()), metadata={})
    for name in ('frame_counter', 'frame_timestamp', 'sensor_timestamp', 'backend_timestamp',
                 'time_of_arrival', 'actual_exposure', 'gain_level', 'auto_exposure', 'actual_fps'):
        field = getattr(rs.frame_metadata_value, name, None)
        if field is None:
            continue
        try:
            if frame.supports_frame_metadata(field):
                result['metadata'][name] = dict(supported=True, value=int(frame.get_frame_metadata(field)))
            else:
                result['metadata'][name] = dict(supported=False)
        except Exception as error:
            result['metadata'][name] = dict(read_error=str(error))
    return result


def detect(gray, board, algorithm):
    started = time.monotonic()
    size = (int(board['cols']), int(board['rows']))
    if algorithm == 'classic_subpix':
        flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
        found, corners = cv2.findChessboardCorners(gray, size, flags)
        if found:
            corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1),
                                      (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, .001))
        description = 'findChessboardCorners ADAPTIVE_THRESH|NORMALIZE_IMAGE; cornerSubPix window 5x5, 50 iterations, epsilon .001'
    else:
        found, corners = cv2.findChessboardCornersSB(gray, size, cv2.CALIB_CB_NORMALIZE_IMAGE)
        description = 'findChessboardCornersSB NORMALIZE_IMAGE; no extra filtering or pixel shift'
    return dict(found=bool(found), corners_px=corners.reshape(-1, 2).tolist() if found else None,
                elapsed_seconds=time.monotonic()-started, method=description)


def physical_order(source, destination):
    """Choose only identity or 180-degree list reversal using centered 2D shape.

    Centering is used only for discrete index selection. The original points
    remain unchanged for every dx/dy statistic. No displacement is subtracted
    from the diagnostic, and no rotation/scale/homography is fitted.
    """
    source, destination = np.asarray(source, float), np.asarray(destination, float)
    if source.shape != destination.shape or source.ndim != 2 or source.shape[1] != 2:
        raise ValueError('Point-list shape mismatch')
    centered = source-source.mean(axis=0)
    choices = [destination, destination[::-1]]
    scores = [float(np.sqrt(np.mean(np.sum((centered-(c-c.mean(axis=0)))**2, axis=1))))
              for c in choices]
    best = int(np.argmin(scores))
    gap = float(abs(scores[1]-scores[0]))
    result = dict(choices=['raw_list_order', 'physical_180_degree_list_reversal'],
                  centered_2D_shape_rms_px=scores, selected_index=best if gap >= 3. else None,
                  score_gap_px=gap, minimum_gap_px=3.,
                  rule='Only physical 180-degree order; choose by full centered x/y shape, not by minimum dy; no point shift in reported residuals')
    if result['selected_index'] is not None:
        selected = choices[best]
        delta = selected-source
        result['selected_destination_corners_px'] = selected.tolist()
        result['raw_destination_minus_source_dx_px'] = stats(delta[:, 0])
        result['raw_destination_minus_source_dy_px'] = stats(delta[:, 1])
        result['raw_absolute_dy_px'] = stats(np.abs(delta[:, 1]))
        result['per_corner_raw_dx_dy_px'] = delta.tolist()
    # Both raw options are retained, including ambiguity and nonselected order.
    result['all_order_dy_statistics'] = [dict(choice=i, signed=stats((c-source)[:, 1]),
                                             absolute=stats(np.abs((c-source)[:, 1])))
                                        for i, c in enumerate(choices)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--serial', default='238222071455')
    parser.add_argument('--board', type=Path, default=Path(__file__).with_name('board.json'))
    parser.add_argument('--note', default='Human setup details not supplied')
    parser.add_argument('--operator-static-reported', action='store_true',
                        help='Record a human report only; does not enable automatic stationary acceptance')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    board = json.loads(args.board.read_text(encoding='utf-8'))
    if board['rows'] == board['cols'] or min(board['rows'], board['cols']) < 2:
        raise ValueError('This discrete two-order checker requires a nonsquare rectangular board')
    source = args.output / 'source'
    source.mkdir()
    import common
    sources = []
    for original in (Path(__file__), Path(common.__file__), args.board):
        target = source / original.name
        shutil.copy2(original, target)
        sources.append(dict(name=target.name, bytes=target.stat().st_size, sha256=sha(target)))
    write_json(args.output / 'source_manifest.json', dict(files=sources))
    state = dict(started_utc=now(), output=str(args.output.resolve()), serial_requested=args.serial,
                 requested_streams=['infrared index 1 Y8 640x480 30Hz', 'infrared index 2 Y8 640x480 30Hz'],
                 color_requested=False, depth_requested=False, align_used=False,
                 warmup_frames=30, requested_pairs=3, requested_received_frame_interval=10,
                 board=board, operator_note=args.note, operator_static_reported=args.operator_static_reported,
                 automated_temporal_stationarity_validated=False, physical_calibration_accepted=False,
                 calibration_or_preset_written=False, device_options_written=['temporary emitter_enabled only'],
                 python_version=sys.version, opencv_version=cv2.__version__, numpy_version=np.__version__,
                 sdk_package_version=importlib.metadata.version('pyrealsense2'),
                 source_manifest_sha256=sha(args.output / 'source_manifest.json'),
                 pairs=[], errors=[], pipeline_stopped=False)
    write_json(args.output / 'session.json', state)
    sensor = pipeline = None
    emitter_original = None
    started = False
    captured = []
    code = 0
    option_names = ('emitter_enabled', 'laser_power', 'visual_preset', 'enable_auto_exposure', 'exposure', 'gain')
    temperature_names = ('asic_temperature', 'projector_temperature', 'motion_module_temperature')
    try:
        context = rs.context()
        devices = [d for d in context.query_devices()
                   if d.supports(rs.camera_info.serial_number) and d.get_info(rs.camera_info.serial_number) == args.serial]
        if len(devices) != 1:
            raise RuntimeError('Expected exact serial %s; found %d matching devices' % (args.serial, len(devices)))
        device = devices[0]
        state['device'] = {name: device.get_info(getattr(rs.camera_info, name)) for name in
                           ('name', 'serial_number', 'firmware_version', 'usb_type_descriptor')
                           if device.supports(getattr(rs.camera_info, name))}
        sensor = device.first_depth_sensor()
        before = dict(created_utc=now(), options=options(sensor, option_names),
                      temperatures=options(sensor, temperature_names), before_pipeline_start=True)
        write_json(args.output / 'sensor_settings_before.json', before)
        if not sensor.supports(rs.option.emitter_enabled):
            raise RuntimeError('Cannot perform explicit temporary emitter OFF on this sensor')
        emitter_original = float(sensor.get_option(rs.option.emitter_enabled))
        state['emitter_before'] = emitter_original
        write_json(args.output / 'session.json', state)
        config = rs.config()
        config.disable_all_streams()
        config.enable_device(args.serial)
        config.enable_stream(rs.stream.infrared, 1, 640, 480, rs.format.y8, 30)
        config.enable_stream(rs.stream.infrared, 2, 640, 480, rs.format.y8, 30)
        pipeline = rs.pipeline(context)
        active = pipeline.start(config)
        started = True
        if active.get_device().get_info(rs.camera_info.serial_number) != args.serial:
            raise RuntimeError('Active serial differs from requested serial')
        sensor = active.get_device().first_depth_sensor()
        activated = list(active.get_streams())
        if len(activated) != 2 or sorted(p.stream_index() for p in activated) != [1, 2]:
            raise RuntimeError('Unexpected stream count or indexes in minimal IR configuration')
        for p in activated:
            v = p.as_video_stream_profile()
            if p.stream_type() != rs.stream.infrared or p.format() != rs.format.y8 or p.fps() != 30 or (v.width(), v.height()) != (640, 480):
                raise RuntimeError('Active stream is not requested native IR Y8 profile')
        if float(sensor.get_option(rs.option.emitter_enabled)) != 0.:
            sensor.set_option(rs.option.emitter_enabled, 0.)
        actual = float(sensor.get_option(rs.option.emitter_enabled))
        state['emitter_during'] = actual
        if actual != 0.:
            raise RuntimeError('Temporary emitter OFF readback failed')
        profiles = {name: active.get_stream(rs.stream.infrared, index) for name, index in (('ir1', 1), ('ir2', 2))}
        factory = dict(created_utc=now(), device=state['device'], profiles={k: profile_info(p) for k, p in profiles.items()},
                       intrinsics={k: intrinsic(p) for k, p in profiles.items()},
                       extrinsics=dict(ir1_to_ir2=extrinsic(profiles['ir1'], profiles['ir2'], rs),
                                       ir2_to_ir1=extrinsic(profiles['ir2'], profiles['ir1'], rs)),
                       geometry_convention='T_destination_from_source; meters; raw native pixel coordinates',
                       sensor_options_during=options(sensor, option_names),
                       color_depth_align_enabled=False, calibration_table_written=False)
        write_json(args.output / 'factory.json', factory)
        for _ in range(30):
            pipeline.wait_for_frames(5000)
        # Capture all three pairs before expensive chessboard detection; real
        # SDK frame-number gaps are retained instead of assuming exactly 10.
        for index in range(3):
            for _ in range(1 if index == 0 else 10):
                frames = pipeline.wait_for_frames(5000)
            pair = {name: frames.get_infrared_frame(stream_index)
                    for name, stream_index in (('ir1', 1), ('ir2', 2))}
            if not all(pair.values()):
                raise RuntimeError('A requested IR frame is missing')
            info = {name: frame_info(frame) for name, frame in pair.items()}
            arrays = {name: np.asanyarray(frame.get_data()).copy() for name, frame in pair.items()}
            if any(array.dtype != np.uint8 or array.shape != (480, 640) for array in arrays.values()):
                raise RuntimeError('Raw IR buffer shape/dtype differs from native Y8')
            domains_match = info['ir1']['timestamp_domain'] == info['ir2']['timestamp_domain']
            metadata = dict(index=index+1, host_utc=now(), monotonic_s=time.monotonic(), streams=info,
                            domains_match=domains_match,
                            frame_numbers_equal=info['ir1']['number'] == info['ir2']['number'],
                            ir2_minus_ir1_sdk_timestamp_ms=(info['ir2']['sdk_timestamp_ms']-info['ir1']['sdk_timestamp_ms']) if domains_match else None,
                            temperatures=options(sensor, temperature_names),
                            emitter_readback=float(sensor.get_option(rs.option.emitter_enabled)),
                            automated_stationarity_validated=False)
            if captured:
                metadata['ir1_sdk_frame_number_gap_from_previous_saved_pair'] = info['ir1']['number']-captured[-1]['metadata']['streams']['ir1']['number']
                metadata['ir2_sdk_frame_number_gap_from_previous_saved_pair'] = info['ir2']['number']-captured[-1]['metadata']['streams']['ir2']['number']
            captured.append(dict(arrays=arrays, metadata=metadata))
    except BaseException as error:
        code = 130 if isinstance(error, KeyboardInterrupt) else 1
        state['errors'].append(dict(phase='capture', type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
    finally:
        if sensor is not None and emitter_original is not None:
            try:
                before_restore = float(sensor.get_option(rs.option.emitter_enabled))
                if before_restore != emitter_original:
                    sensor.set_option(rs.option.emitter_enabled, emitter_original)
                restored = float(sensor.get_option(rs.option.emitter_enabled))
                state['emitter_restore'] = dict(expected=emitter_original, before_restore=before_restore,
                                               actual=restored, verified=restored == emitter_original,
                                               restored_before_pipeline_stop=True,
                                               sensor_options_after_restore=options(sensor, option_names),
                                               temperatures_after=options(sensor, temperature_names))
                write_json(args.output / 'sensor_settings_after_restore.json', state['emitter_restore'])
                if restored != emitter_original:
                    raise RuntimeError('Emitter restoration readback differs from original value')
            except Exception as error:
                code = code or 1
                state['errors'].append(dict(phase='emitter_restore', message=str(error)))
        if pipeline is not None and started:
            try:
                pipeline.stop()
                state['pipeline_stopped'] = True
            except Exception as error:
                code = code or 1
                state['errors'].append(dict(phase='pipeline_stop', message=str(error)))
        state['camera_phase_ended_utc'] = now()
        state['captured_pairs'] = len(captured)
        write_json(args.output / 'session.json', state)
    # From this point onward, all work uses copied buffers after camera release.
    aggregate = {algorithm: [] for algorithm in ('classic_subpix', 'sb')}
    try:
        saved_pairs = []
        for item in captured:
            folder = args.output / 'pairs' / ('%04d' % item['metadata']['index'])
            folder.mkdir(parents=True, exist_ok=False)
            files = []
            for name, array in item['arrays'].items():
                np.save(folder / (name+'.npy'), array, allow_pickle=False)
                if not cv2.imwrite(str(folder / (name+'.png')), array):
                    raise OSError('Failed to save raw IR PNG')
                for suffix in ('.npy', '.png'):
                    p = folder / (name+suffix)
                    files.append(dict(name=p.name, bytes=p.stat().st_size, sha256=sha(p)))
            # Persist every raw pair before running either corner algorithm, so
            # an offline detector failure cannot discard another captured pair.
            write_json(folder / 'raw_capture.json', dict(metadata=item['metadata'], files=files))
            saved_pairs.append((item, folder, files))
        for item, folder, files in saved_pairs:
            result = dict(metadata=item['metadata'], files=files, algorithms={}, classic_vs_sb_same_image={})
            for algorithm in aggregate:
                detection = {name: detect(array, board, algorithm) for name, array in item['arrays'].items()}
                value = dict(detections=detection, geometric_accuracy_accepted=False)
                if all(d['found'] for d in detection.values()):
                    value['physical_order_and_raw_dy'] = physical_order(detection['ir1']['corners_px'], detection['ir2']['corners_px'])
                    order = value['physical_order_and_raw_dy']
                    if order['selected_index'] is not None:
                        aggregate[algorithm].append(np.asarray(order['per_corner_raw_dx_dy_px'])[:, 1])
                result['algorithms'][algorithm] = value
            for name in ('ir1', 'ir2'):
                classic = result['algorithms']['classic_subpix']['detections'][name]
                sb = result['algorithms']['sb']['detections'][name]
                if classic['found'] and sb['found']:
                    result['classic_vs_sb_same_image'][name] = physical_order(classic['corners_px'], sb['corners_px'])
            write_json(folder / 'pair.json', result)
            state['pairs'].append(dict(index=item['metadata']['index'], pair_json=str((folder/'pair.json').relative_to(args.output)),
                                       pair_json_sha256=sha(folder / 'pair.json'), metadata=item['metadata'],
                                       detection_found={a: {n: d['found'] for n, d in v['detections'].items()} for a, v in result['algorithms'].items()},
                                       raw_dy_by_algorithm={a: v.get('physical_order_and_raw_dy', {}).get('raw_destination_minus_source_dy_px')
                                                            for a, v in result['algorithms'].items()}))
        state['all_points_raw_dy_by_algorithm'] = {
            algorithm: dict(usable_pairs=len(values), signed=stats(np.concatenate(values)), absolute=stats(np.abs(np.concatenate(values))))
            if values else dict(usable_pairs=0) for algorithm, values in aggregate.items()}
    except BaseException as error:
        code = code or (130 if isinstance(error, KeyboardInterrupt) else 1)
        state['errors'].append(dict(phase='offline_saved_buffer_analysis', type=type(error).__name__,
                                  message=str(error), traceback=traceback.format_exc()))
    state['limitations'] = [
        'Native IR-only configuration isolates RGB/depth/align processing and mixed-stream frame selection from this test.',
        'Three short pairs are not a multiview calibration, automated stationarity acceptance, temperature sweep or physical GT.',
        'No image is shifted, rectified, scaled or warped before detection or residual calculation.',
        'Only identity/physical 180-degree correspondence is considered; centered-shape scoring is used only for index ordering.',
        'Raw dy can reflect image geometry, corner estimation, timing or camera calibration; it is not an absolute millimeter error.',
        'Both detectors operate on the same images and therefore are not independent physical reference instruments.',
        'Only temporary emitter_enabled is restored and verified; other sensor options are recorded, not claimed to have been independently restored.']
    state.update(ended_utc=now(), status='finished' if code == 0 else 'failed', exit_code=code)
    write_json(args.output / 'session.json', state)
    manifest_files = [dict(name=str(p.relative_to(args.output)), bytes=p.stat().st_size, sha256=sha(p))
                      for p in sorted(args.output.rglob('*')) if p.is_file()]
    write_json(args.output / 'manifest.json', dict(files=manifest_files))
    print(json.dumps(dict(output=str(args.output.resolve()), status=state['status'], captured_pairs=len(captured),
                          emitter_restore=state.get('emitter_restore'), pipeline_stopped=state['pipeline_stopped'],
                          raw_dy=state.get('all_points_raw_dy_by_algorithm'), errors=state['errors']), ensure_ascii=False), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
