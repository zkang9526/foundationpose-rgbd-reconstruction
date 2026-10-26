#!/usr/bin/env python3
"""Read current D435i depth-sensor settings; no streaming or setting changes."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import traceback

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
output = args.output.resolve()
if output.exists():
    parser.error('Use a new output report; preserve previous evidence')
report = dict(passed=False, scope='current_sensor_options_read_only',
              timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              streaming_started=False, device_options_modified=False)
try:
    import pyrealsense2 as rs
    context = rs.context()
    device = next((device for device in context.query_devices()
                   if 'D435I' in device.get_info(rs.camera_info.name).upper()), None)
    if device is None:
        raise RuntimeError('No D435i found')
    report['serial_number'] = device.get_info(rs.camera_info.serial_number)
    try:
        advanced = rs.rs400_advanced_mode(device)
        report['advanced_mode_enabled'] = advanced.is_enabled()
        if advanced.is_enabled():
            settings = advanced.serialize_json()
            snapshot = output.with_name(output.stem + '_advanced_settings.json')
            with snapshot.open('x', encoding='utf-8') as stream:
                stream.write(settings)
            report['advanced_settings_snapshot'] = dict(path=str(snapshot),
                sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                scope='current configuration only; no historical settings recovery')
    except RuntimeError as exc:
        report['advanced_settings_read_error'] = str(exc)
    sensor = device.first_depth_sensor()
    report['options'] = {}
    for name in ('emitter_enabled', 'laser_power', 'enable_auto_exposure',
                 'exposure', 'gain', 'visual_preset', 'emitter_always_on'):
        option = getattr(rs.option, name, None)
        if option is None or not sensor.supports(option):
            report['options'][name] = dict(supported=False)
            continue
        try:
            value = sensor.get_option(option)
            limits = sensor.get_option_range(option)
            item = dict(supported=True, value=value, minimum=limits.min,
                        maximum=limits.max, step=limits.step, default=limits.default)
            try:
                item['value_description'] = sensor.get_option_value_description(option, value)
            except RuntimeError:
                pass
            report['options'][name] = item
        except RuntimeError as exc:
            report['options'][name] = dict(supported=True, read_error=str(exc))
    report['passed'] = True
except Exception as exc:
    report['error'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    traceback.print_exc()
output.parent.mkdir(parents=True, exist_ok=True)
with output.open('x', encoding='utf-8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps(report, ensure_ascii=False), flush=True)
raise SystemExit(0 if report['passed'] else 1)
