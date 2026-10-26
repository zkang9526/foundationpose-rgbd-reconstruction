#!/usr/bin/env python3
"""Publish a small, evidence-based OBJ environment delivery manifest."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys


def fingerprint(path, root):
    return dict(path=path.relative_to(root).as_posix(), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    if root not in output.parents or output.exists():
        parser.error('output must be a new file inside the project')
    reports = {
        'windows_camera': 'foundationpose_data/windows_captures/obj_env_check_20261014_132150_762/report.json',
        'windows_options': 'foundationpose_data/windows_captures/obj_options_final_20261014_133130_611/report.json',
        'ubuntu_open3d': 'reports/open3d_20261014_1333_surface/report.json',
    }
    evidence = {}
    for name, relative in reports.items():
        path = root / relative
        content = json.loads(path.read_text(encoding='utf-8-sig'))
        if content.get('passed') is not True:
            raise RuntimeError('Environment evidence has not passed: ' + relative)
        evidence[name] = dict(file=fingerprint(path, root), report=content)
    sources = ['setup/prepare_d435i_windows.ps1', 'setup/capture_d435i_photos.py',
               'setup/realsense_capture_options.py', 'setup/start_obj_photos.ps1',
               'setup/verify_obj_windows_options.py', 'setup/verify_obj_environment.py',
               'setup/run_obj_environment_check.sh', 'setup/run_logged.py',
               'setup/finalize_obj_setup.py']
    for name in sources:
        if name.endswith('.py'):
            ast.parse((root / name).read_text(encoding='utf-8-sig'), filename=name)
    viewer = root / '.assets_download/Intel.RealSense.Viewer.2.55.1.exe'
    item = fingerprint(viewer, root)
    if item['sha256'] != 'ced0bd623f2df2e86f074ff8ee0fd89637c92f25f44fbf2d24262a325a8990c0':
        raise RuntimeError('Viewer changed since its signed-binary verification')
    document = dict(passed=True, scope='environment_and_capture_options_only',
                    real_object_obj_ready=False, evidence=evidence,
                    viewer=item, sources=[fingerprint(root / name, root) for name in sources],
                    guide='reports/OBJ_ENVIRONMENT_SETUP_20261014.md',
                    known_pending=['object_mask_and_registration', 'real_mesh_quality', 'BundleSDF_exit_139'])
    with output.open('x', encoding='utf-8') as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(passed=True, output=str(output), evidence_count=len(evidence)), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
