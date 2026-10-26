#!/usr/bin/env python3
"""Bounded static RGB-D comparison; back up and restore camera configuration.

Changes processing presets and depth auto-exposure, never calibration. Regions
are manually chosen samples for the current cup placement, not object masks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import traceback

from realsense_capture_options import CaptureOptions
from verify_d435i import intrinsics_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--warmup', type=int, default=90)
    parser.add_argument('--frames', type=int, default=30)
    args = parser.parse_args()
    if args.warmup < 0 or args.frames < 1:
        parser.error('Invalid frame count')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, scope='static_raw_depth_preset_comparison_no_calibration_or_metric_accuracy_verdict',
                  output=str(output), variants={}, original_settings_restored=False)
    pipeline = None
    advanced = None
    original = None
    options = None
    try:
        import numpy as np
        from PIL import Image
        import pyrealsense2 as rs
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        profile = pipeline.start(config)
        device = profile.get_device()
        if 'D435I' not in device.get_info(rs.camera_info.name).upper():
            raise RuntimeError('Connected device is not D435i')
        report['serial_number'] = device.get_info(rs.camera_info.serial_number)
        sensor = device.first_depth_sensor()
        advanced = rs.rs400_advanced_mode(device)
        if not advanced.is_enabled():
            raise RuntimeError('Advanced mode is disabled; comparison will not enable it')
        original = advanced.serialize_json()
        (output / 'camera_settings_before.json').write_text(original, encoding='utf-8')
        report['original_settings_sha256'] = hashlib.sha256(original.encode()).hexdigest()
        original_preset = sensor.get_option(rs.option.visual_preset)
        report['original_preset'] = original_preset
        align = rs.align(rs.stream.color)
        scale = sensor.get_depth_scale()
        Kinfo = intrinsics_info(profile.get_stream(rs.stream.color))
        K = np.array([[Kinfo['fx'], 0, Kinfo['cx']], [0, Kinfo['fy'], Kinfo['cy']], [0, 0, 1]])
        regions = dict(body_core=[267, 315, 324, 355], dark_band_core=[268, 387, 324, 400],
                       visible_bottom_core=[275, 275, 313, 285])
        report['sample_regions_xyxy_exclusive'] = regions
        report['sample_regions_are_full_masks'] = False
        variants = [('current', 'device-default', False),
                    ('current_ae', 'device-default', True),
                    ('high_accuracy_ae', 'high-accuracy', True),
                    ('high_density_ae', 'high-density', True)]
        for name, preset, enable_ae in variants:
            sensor.set_option(rs.option.visual_preset, original_preset)
            advanced.load_json(original)
            folder = output / name
            folder.mkdir()
            (folder / 'rgb').mkdir()
            (folder / 'depth').mkdir()
            item = dict(passed=False, warnings=[], requested_preset=preset, enable_depth_ae=enable_ae, frames=[])
            report['variants'][name] = item
            options = CaptureOptions(rs, sensor, item, device, folder)
            options.configure(preset, False)
            if enable_ae:
                sensor.set_option(rs.option.enable_auto_exposure, 1)
            for _ in range(args.warmup):
                pipeline.wait_for_frames(5000)
            (folder / 'camera_settings_active.json').write_text(advanced.serialize_json(), encoding='utf-8')
            print('Comparing ' + name + ' ...', flush=True)
            seen = set()
            for index in range(args.frames):
                native = pipeline.wait_for_frames(5000)
                frames = align.process(native)
                color, depth_frame = frames.get_color_frame(), frames.get_depth_frame()
                if not color or not depth_frame:
                    raise RuntimeError('Incomplete RGB-D pair')
                pair = (color.get_frame_number(), depth_frame.get_frame_number())
                if pair in seen:
                    raise RuntimeError('Repeated frame pair')
                seen.add(pair)
                rgb = np.asanyarray(color.get_data()).copy()
                depth = np.asanyarray(depth_frame.get_data()).copy()
                filename = '%06d.png' % index
                Image.fromarray(rgb).save(folder / 'rgb' / filename)
                Image.fromarray(depth).save(folder / 'depth' / filename)
                ratios = {'whole_image': float(np.count_nonzero(depth) / depth.size)}
                for region, (x0, y0, x1, y1) in regions.items():
                    crop = depth[y0:y1, x0:x1]
                    ratios[region] = float(np.count_nonzero(crop) / crop.size)
                item['frames'].append(dict(index=index, color_frame_number=pair[0], depth_frame_number=pair[1],
                    color_timestamp_ms=color.get_timestamp(), depth_timestamp_ms=depth_frame.get_timestamp(),
                    nonzero_raw_depth_ratios=ratios,
                    depth_exposure_us=sensor.get_option(rs.option.exposure)))
            Image.fromarray(rgb).save(folder / 'rgb.png')
            Image.fromarray(depth).save(folder / 'depth.png')
            np.savetxt(folder / 'K.txt', K)
            (folder / 'depth_scale.txt').write_text(str(scale) + '\n')
            item['color_intrinsics'] = Kinfo
            item['aligned_depth_intrinsics'] = intrinsics_info(depth_frame.profile)
            item['files'] = dict(rgb='rgb.png', depth='depth.png', K='K.txt', depth_scale='depth_scale.txt')
            item['mean_nonzero_raw_depth_ratios'] = {key: float(np.mean([
                frame['nonzero_raw_depth_ratios'][key] for frame in item['frames']])) for key in ratios}
            options.restore()
            options = None
            item['passed'] = True
            (folder / 'report.json').write_text(json.dumps(item, indent=2) + '\n')
            print(json.dumps(dict(variant=name, mean_ratios=item['mean_nonzero_raw_depth_ratios'])), flush=True)
        report['passed'] = True
    except Exception as exc:
        report['error'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        try:
            if options is not None:
                options.restore()
            if original is not None:
                sensor.set_option(rs.option.visual_preset, original_preset)
                advanced.load_json(original)
                # Verify stable serialized parameters, allowing exposure/gain
                # readings to evolve while depth/color auto-exposure is on.
                before = json.loads(original)['parameters']
                after = json.loads(advanced.serialize_json())['parameters']
                volatile = set()
                for prefix in ('', 'color-'):
                    if before.get('controls-' + prefix + 'autoexposure-auto') == 'True':
                        volatile.update(('controls-' + prefix + 'autoexposure-manual', 'controls-' + prefix + 'gain'))
                differences = sorted(k for k in before.keys() | after.keys()
                                     if k not in volatile and before.get(k) != after.get(k))
                report['restore_differences'] = differences
                report['original_settings_restored'] = not differences
                if differences:
                    raise RuntimeError('Camera settings restoration differs: ' + ', '.join(differences))
        except Exception as exc:
            report['passed'] = False
            report['restore_error'] = str(exc)
        if pipeline is not None:
            try:
                pipeline.stop()
                report['pipeline_stopped'] = True
            except Exception as exc:
                report['passed'] = False
                report['pipeline_stop_error'] = str(exc)
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], original_settings_restored=report['original_settings_restored'],
                         output=str(output))), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
