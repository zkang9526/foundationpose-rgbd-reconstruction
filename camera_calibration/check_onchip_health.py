"""Generate candidates/raw health, then explicitly restore original RAM table.

Run only through the project logger after reviewing this source. Candidates are
never explicitly applied by this script. Original flash-table bytes are backed
up and explicitly restored to volatile RAM in finally; command success is not
RAM-byte readback verification. No persistent write/reset, advanced-mode toggle,
focal-length procedure or tare procedure is implemented.
"""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

import cv2
import numpy as np
import pyrealsense2 as rs


SERIAL = '238222071455'
REFERENCE = 'https://github.com/realsenseai/librealsense/blob/master/wrappers/python/examples/depth_auto_calibration_example.py'
HEALTH_BINDING_REFERENCE = 'https://github.com/IntelRealSense/librealsense/blob/v2.55.1/wrappers/python/pyrs_device.cpp#L108-L119'
CONTROL_OPTIONS = ('visual_preset', 'emitter_enabled', 'laser_power',
                   'enable_auto_exposure', 'exposure', 'gain', 'thermal_compensation')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def raw_json(value):
    """Preserve nesting/type and raw values without assigning health semantics."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else dict(type='float', repr=repr(value))
    if isinstance(value, (tuple, list)):
        return dict(type=type(value).__name__, items=[raw_json(v) for v in value])
    if isinstance(value, dict):
        return {str(k): raw_json(v) for k, v in value.items()}
    return dict(type=type(value).__name__, repr=repr(value))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def options(sensor):
    result = {}
    for option in sensor.get_supported_options():
        name = str(option)
        try:
            r = sensor.get_option_range(option)
            result[name] = dict(value=float(sensor.get_option(option)),
                                read_only=bool(sensor.is_option_read_only(option)),
                                range=dict(min=float(r.min), max=float(r.max), step=float(r.step), default=float(r.default)))
        except Exception as e:
            result[name] = dict(read_error=str(e))
    return result


def controls(sensor):
    return {name: float(sensor.get_option(getattr(rs.option, name))) for name in CONTROL_OPTIONS
            if hasattr(rs.option, name) and sensor.supports(getattr(rs.option, name))}


def save_table(device, output):
    data = bytes(device.get_calibration_table())
    if not data:
        raise RuntimeError('SDK returned an empty calibration table')
    Path(output).write_bytes(data)
    return dict(file=Path(output).name, bytes=len(data), sha256=sha(output),
                readback_storage='flash; not volatile RAM-byte verification')


def restore_original_ram(device, backup):
    """Only restore known original bytes; never interpret flash as a RAM readback."""
    record = dict(utc=now(), table_bytes=len(backup), table_sha256=hashlib.sha256(backup).hexdigest(),
                  target='volatile RAM', command='set_calibration_table(original_backup)',
                  command_attempted=True, command_succeeded=False,
                  ram_table_bytes_readback_verified=False,
                  verification_scope='SDK command completed without exception; no independent RAM-byte readback API is used')
    try:
        device.set_calibration_table(list(backup))
        record['command_succeeded']=True
    except BaseException as e:
        # Preserve cleanup evidence and continue control restoration even after
        # another interrupt. The caller marks the complete run failed.
        record['error']=dict(type=type(e).__name__, message=str(e), traceback=traceback.format_exc())
    return record


def profile_info(profile):
    v = profile.as_video_stream_profile()
    i = v.get_intrinsics()
    return dict(stream=str(profile.stream_type()), index=profile.stream_index(),
                format=str(profile.format()), fps=profile.fps(), unique_id=profile.unique_id(),
                width=v.width(), height=v.height(),
                intrinsics=dict(fx=i.fx, fy=i.fy, ppx=i.ppx, ppy=i.ppy,
                                model=str(i.model), coeffs=list(i.coeffs)))


def capture_sample(pipe, output, sensor, warmup_frames):
    deadline = time.monotonic()+15.
    for _ in range(warmup_frames):
        if time.monotonic() > deadline:
            raise RuntimeError('Warm-up exceeded 15 seconds')
        pipe.wait_for_frames(1000)
    samples = []
    scale = float(sensor.get_depth_scale())
    for index in range(3):
        f = pipe.wait_for_frames(1000).get_depth_frame()
        if not f:
            raise RuntimeError('Missing native depth sample')
        depth = np.asanyarray(f.get_data()).copy()
        if depth.shape != (144, 256) or depth.dtype != np.uint16:
            raise RuntimeError('Unexpected native depth shape/dtype')
        name = 'native_depth_%02d' % index
        np.save(output/(name+'.npy'), depth, allow_pickle=False)
        if not cv2.imwrite(str(output/(name+'.png')), depth):
            raise OSError('Depth PNG save failed')
        # Central half of width and height, recorded explicitly, not a pass gate.
        x0, x1, y0, y1 = 64, 192, 36, 108
        roi = depth[y0:y1, x0:x1]
        samples.append(dict(index=index, frame_number=f.get_frame_number(),
                            sdk_timestamp_ms=f.get_timestamp(), timestamp_domain=str(f.get_frame_timestamp_domain()),
                            host_utc=now(), shape=list(depth.shape), dtype=str(depth.dtype),
                            depth_scale_m=scale, valid_fraction_whole=float(np.mean(depth>0)),
                            center_roi_xyxy=[x0,y0,x1,y1], center_valid_fraction=float(np.mean(roi>0)),
                            files=[dict(file=name+suffix, sha256=sha(output/(name+suffix))) for suffix in ('.npy','.png')]))
    write_json(output/'native_depth_samples.json', samples)
    return samples


def restore_controls(sensor, original):
    """Restore commanded controls; do not freeze naturally changing AE outputs."""
    records = []
    # A preset restore can alter other values, so process it first and verify all
    # subsequent controls. Manual exposure/gain are restored only in manual mode.
    for name in CONTROL_OPTIONS:
        if name not in original:
            continue
        option = getattr(rs.option, name)
        try:
            current = float(sensor.get_option(option))
            if name in ('exposure', 'gain') and original.get('enable_auto_exposure') == 1.:
                records.append(dict(option=name, before=original[name], actual=current,
                                    action='not_forced_auto_exposure_dynamic_output', verified=None))
                continue
            changed = current != original[name]
            if changed:
                if sensor.is_option_read_only(option):
                    raise RuntimeError('Changed control is now read-only')
                sensor.set_option(option, original[name])
            actual = float(sensor.get_option(option))
            records.append(dict(option=name, before=original[name], actual=actual,
                                action='restored' if changed else 'unchanged', verified=actual==original[name]))
        except Exception as e:
            records.append(dict(option=name, before=original[name], verified=False, error=str(e)))
    return records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--serial', default=SERIAL, choices=(SERIAL,))
    p.add_argument('--warmup-frames', type=int, default=90)
    args = p.parse_args()
    if not 30 <= args.warmup_frames <= 450:
        p.error('Warm-up must be 30..450 frames')
    args.output = args.output.resolve()
    if os.name == 'nt' and args.output.drive.upper() != 'E:':
        p.error('Windows outputs must be on E:')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'source').mkdir()
    shutil.copy2(__file__, args.output/'source'/Path(__file__).name)
    sdk_version = importlib.metadata.version('pyrealsense2')
    summary = dict(created_utc=now(), status='starting', serial=args.serial, sdk_version=sdk_version,
                   python_version=sys.version, numpy_version=np.__version__, opencv_version=cv2.__version__,
                   source_sha256=sha(__file__), reference_example=REFERENCE,
                   scope='vendor on-chip diagnostic candidate generation only; not checkerboard GT or physical calibration acceptance',
                   candidate_explicitly_applied_by_script=False, persistent_calibration_write_implemented=False,
                   advanced_mode_toggle_implemented=False, flash_table_readback_unchanged_verified=False,
                   original_ram_restore_command_succeeded=False, ram_table_bytes_readback_verified=False,
                   requested_profile=dict(stream='depth', width=256, height=144, format='z16', fps=90),
                   timeout_ms_per_scan=30000, warmup_frames=args.warmup_frames, scans=[], errors=[],
                   notes=['Only thermal_compensation may be temporarily commanded off before diagnostics.',
                          'Emitter, preset, auto-exposure and manual controls are preserved; changed controls are restored in finally.',
                          'Exposure and gain are dynamic measurements under AE and are recorded, not forced to their initial samples.',
                          'Candidate table bytes and SDK raw health components are stored without reinterpreting their tuple semantics.',
                          'SDK v2.55.1 Python on-chip binding returns (table, (health, 0.0)); the second number is a literal placeholder, not a post-calibration health score.',
                          'candidate_explicitly_applied_by_script=False describes only the absence of an explicit candidate application; on-chip firmware may affect active state.',
                          'get_calibration_table reads flash; identical before/after bytes certify flash readback only, not active volatile calibration.',
                          'Finally explicitly sends the original backed-up table to volatile RAM; success means the SDK command returned, not that RAM bytes were independently read back.',
                          'No SDK/FW installation or upgrade, factory reset, focal-length or tare procedure is performed.',
                          'Flash mismatch is recorded as failure; no candidate or original table is written to flash.'],
                   health_binding_reference=HEALTH_BINDING_REFERENCE)
    write_json(args.output/'summary.json', summary)
    device = sensor = auto = None
    original, baseline_table, original_table_backup = {}, None, None
    result_code = 1
    try:
        if sdk_version.split('.')[:3] != ['2','55','1']:
            raise RuntimeError('Expected existing SDK 2.55.1; refusing to change or upgrade it')
        context = rs.context()
        matches = [d for d in context.query_devices() if d.supports(rs.camera_info.serial_number)
                   and d.get_info(rs.camera_info.serial_number)==args.serial]
        if len(matches)!=1:
            raise RuntimeError('Expected exactly one connected target serial')
        device = matches[0]
        summary['device'] = {str(info):device.get_info(info) for info in
                             (rs.camera_info.name,rs.camera_info.serial_number,rs.camera_info.firmware_version,
                              rs.camera_info.product_line,rs.camera_info.usb_type_descriptor) if device.supports(info)}
        if device.get_info(rs.camera_info.product_line)!='D400':
            raise RuntimeError('Target is not D400')
        if device.supports(rs.camera_info.usb_type_descriptor) and not device.get_info(rs.camera_info.usb_type_descriptor).startswith('3'):
            raise RuntimeError('USB3 connection required for requested native profile')
        sensor = device.first_depth_sensor()
        original = controls(sensor)
        write_json(args.output/'options_before.json', dict(created_utc=now(), controls=original, all_options=options(sensor)))
        auto = device.as_auto_calibrated_device()
        baseline_table = save_table(auto,args.output/'calibration_table_before.bin')
        saved_backup=(args.output/'calibration_table_before.bin').read_bytes()
        if hashlib.sha256(saved_backup).hexdigest()!=baseline_table['sha256']:
            raise RuntimeError('Saved original flash-table backup failed SHA verification')
        original_table_backup=saved_backup
        summary['calibration_table_before'] = baseline_table
        write_json(args.output/'summary.json', summary)
        if 'thermal_compensation' in original and original['thermal_compensation']!=0.:
            sensor.set_option(rs.option.thermal_compensation,0.)
            if float(sensor.get_option(rs.option.thermal_compensation))!=0.:
                raise RuntimeError('Thermal compensation did not turn off')
        summary['active_controls_before_scans'] = controls(sensor)
        write_json(args.output/'options_diagnostic.json', dict(created_utc=now(), controls=controls(sensor), all_options=options(sensor)))
        summary['status']='running'
        for scan_name,scan_parameter in (('intrinsic',0),('extrinsic',1)):
            folder=args.output/('scan_'+scan_name)
            folder.mkdir()
            scan=dict(name=scan_name, scan_parameter=scan_parameter, started_utc=now(), status='starting',
                      parameters={'calib type':0,'speed':2,'scan parameter':scan_parameter,'white_wall_mode':0},
                      timeout_ms=30000, candidate_explicitly_applied_by_script=False, progress=[])
            summary['scans'].append(scan)
            pipe=None
            try:
                pipe=rs.pipeline(context)
                cfg=rs.config()
                cfg.enable_device(args.serial)
                cfg.enable_stream(rs.stream.depth,256,144,rs.format.z16,90)
                active=pipe.start(cfg)
                scan['active_profiles']=[profile_info(v) for v in active.get_streams()]
                if len(scan['active_profiles'])!=1 or any(scan['active_profiles'][0][k]!=v for k,v in
                    dict(width=256,height=144,fps=90,index=0).items()):
                    raise RuntimeError('Actual stream does not match requested native depth profile')
                if 'thermal_compensation' in original:
                    actual_thermal=float(sensor.get_option(rs.option.thermal_compensation))
                    if actual_thermal!=0.:
                        sensor.set_option(rs.option.thermal_compensation,0.)
                        actual_thermal=float(sensor.get_option(rs.option.thermal_compensation))
                    scan['active_thermal_compensation']=actual_thermal
                    if actual_thermal!=0.:
                        raise RuntimeError('Thermal compensation is active during the diagnostic profile')
                scan['options_before_call']=options(sensor)
                scan['samples']=capture_sample(pipe,folder,sensor,args.warmup_frames)
                def progress(value):
                    item=dict(utc=now(), raw_progress=raw_json(value))
                    scan['progress'].append(item)
                    with (folder/'progress.jsonl').open('a',encoding='utf-8') as f:
                        f.write(json.dumps(item,ensure_ascii=False)+'\n')
                started=time.monotonic()
                scan['status']='sdk_call_running'
                write_json(folder/'scan.json',scan)
                returned=active.get_device().as_auto_calibrated_device().run_on_chip_calibration(
                    json.dumps(scan['parameters']),progress,30000)
                scan['sdk_call_seconds']=time.monotonic()-started
                if not isinstance(returned,(tuple,list)) or len(returned)<2:
                    scan['raw_unexpected_return']=raw_json(returned)
                    raise RuntimeError('Unexpected SDK return structure; no candidate interpretation attempted')
                candidate=bytes(returned[0])
                if not candidate:
                    raise RuntimeError('Empty candidate table')
                (folder/'candidate_table.bin').write_bytes(candidate)
                scan['candidate_table']=dict(file='candidate_table.bin',bytes=len(candidate),sha256=sha(folder/'candidate_table.bin'))
                scan['raw_health']=dict(sdk_return_type=type(returned).__name__,sdk_return_arity=len(returned),
                                       health_components=[raw_json(v) for v in returned[1:]],
                                       raw_health_repr=repr(returned[1:]),interpretation=None,
                                       sdk_v2551_binding_semantics=dict(
                                           return_shape='(table, (health, 0.0))',
                                           second_health_tuple_number='literal placeholder; not a measured after score',
                                           source=HEALTH_BINDING_REFERENCE))
                write_json(folder/'health_raw.json',scan['raw_health'])
                scan['status']='candidate_generated'
            except Exception as e:
                scan['status']='failed'
                scan['error']=dict(message=str(e),traceback=traceback.format_exc())
            finally:
                if pipe is not None:
                    try:
                        pipe.stop()
                        scan['pipeline_stopped']=True
                    except Exception as e:
                        scan['pipeline_stopped']=False
                        scan['pipeline_stop_error']=str(e)
                scan['ended_utc']=now()
                try:
                    scan['options_after_call']=options(sensor)
                    scan['flash_table_readback']=save_table(auto,folder/'calibration_table_readback.bin')
                    scan['flash_table_readback_unchanged_verified']=scan['flash_table_readback']['sha256']==baseline_table['sha256']
                except Exception as e:
                    scan['readback_error']=str(e)
                    scan['flash_table_readback_unchanged_verified']=False
                write_json(folder/'scan.json',scan)
                write_json(args.output/'summary.json',summary)
            if not scan.get('flash_table_readback_unchanged_verified'):
                raise RuntimeError('Flash table changed or readback failed; refusing further scans; original RAM restoration will be attempted in finally')
            print(json.dumps(dict(scan=scan_name,status=scan['status'],raw_health=scan.get('raw_health'),
                                  flash_table_readback_unchanged_verified=scan.get('flash_table_readback_unchanged_verified'))),flush=True)
        result_code=0 if all(s['status']=='candidate_generated' and s.get('pipeline_stopped') for s in summary['scans']) else 1
    except KeyboardInterrupt:
        summary['errors'].append(dict(type='KeyboardInterrupt',message='Interrupted; cleanup attempted'))
        result_code=130
    except Exception as e:
        summary['errors'].append(dict(message=str(e),traceback=traceback.format_exc()))
        result_code=1
    finally:
        # This restoration precedes any option/report work so those failures
        # cannot skip the explicit original-table command.
        if auto is not None and original_table_backup is not None:
            summary['original_ram_restoration']=restore_original_ram(auto,original_table_backup)
            summary['original_ram_restore_command_succeeded']=summary['original_ram_restoration']['command_succeeded']
            if not summary['original_ram_restore_command_succeeded']:
                result_code=1
        if sensor is not None and original:
            summary['control_restoration']=restore_controls(sensor,original)
            if any(v.get('verified') is False for v in summary['control_restoration']):
                result_code=1
            try:
                write_json(args.output/'options_after_restore.json',dict(created_utc=now(),controls=controls(sensor),all_options=options(sensor),restoration=summary['control_restoration']))
            except Exception as e:
                summary['errors'].append(dict(options_after_restore_error=str(e)));result_code=1
        if auto is not None and baseline_table is not None:
            try:
                summary['calibration_table_after']=save_table(auto,args.output/'calibration_table_after.bin')
                summary['flash_table_readback_unchanged_verified']=summary['calibration_table_after']['sha256']==baseline_table['sha256']
                if not summary['flash_table_readback_unchanged_verified']:
                    result_code=1
            except Exception as e:
                summary['errors'].append(dict(final_table_readback_error=str(e)));result_code=1
        summary.update(ended_utc=now(),status='complete' if result_code==0 else 'failed',exit_code=result_code)
        write_json(args.output/'summary.json',summary)
        files=[dict(name=str(f.relative_to(args.output)),sha256=sha(f),bytes=f.stat().st_size)
               for f in sorted(args.output.rglob('*')) if f.is_file()]
        write_json(args.output/'manifest.json',dict(files=files))
        print(json.dumps(dict(output=str(args.output),status=summary['status'],exit_code=result_code,
                              flash_table_readback_unchanged_verified=summary['flash_table_readback_unchanged_verified'],
                              original_ram_restore_command_succeeded=summary['original_ram_restore_command_succeeded'],
                              ram_table_bytes_readback_verified=False,
                              scans=[dict(name=s['name'],status=s['status']) for s in summary['scans']])),flush=True)
    return result_code


if __name__=='__main__':
    sys.exit(main())
