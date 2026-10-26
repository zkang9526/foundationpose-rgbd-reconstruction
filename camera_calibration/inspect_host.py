"""Read-only host/device/session inventory for the isolated calibration task."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    result = dict(platform=platform.platform(), executable=sys.executable, packages={})
    for name in ('pyrealsense2', 'opencv-python', 'opencv-python-headless', 'numpy'):
        try:
            result['packages'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result['packages'][name] = None
    import pyrealsense2 as rs
    result['devices'] = []
    for d in rs.context().query_devices():
        result['devices'].append({n: d.get_info(getattr(rs.camera_info, n)) for n in
                                  ('name', 'serial_number', 'firmware_version', 'usb_type_descriptor')})
    if os.name != 'nt':
        r = subprocess.run(['pgrep', '-af', 'run_cup_live|capture_d435i|realsense-viewer'],
                           capture_output=True, text=True)
        result['camera_processes'] = r.stdout
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/status', timeout=3) as f:
            result['existing_live_status'] = json.load(f)
    except Exception as e:
        result['existing_live_status_error'] = str(e)
    (a.output / 'report.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
