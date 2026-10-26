"""Exercise volatile-table cleanup on fake SDK/capture failures; no camera API.

The fake SDK is installed before loading the comparison module. It implements
no flash-write method. Test data remains separate from all physical results.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original, candidate = bytes([17])*512, bytes([23])*512
    digest = lambda v: hashlib.sha256(v).hexdigest()
    results = []
    for scenario in ('success', 'candidate_capture_failure', 'candidate_set_failure', 'restore_failure', 'flash_mismatch'):
        folder = args.output/scenario
        folder.mkdir()
        (folder/'original.bin').write_bytes(original)
        (folder/'candidate.bin').write_bytes(candidate)
        (folder/'health.json').write_text(json.dumps(dict(
            calibration_table_before=dict(sha256=digest(original)),
            scans=[dict(name='intrinsic', candidate_table=dict(sha256=digest(candidate)))])), encoding='utf-8')
        calls = []

        class Auto:
            def get_calibration_table(self):
                return list(candidate if scenario == 'flash_mismatch' else original)

            def set_calibration_table(self, value):
                value = bytes(value)
                calls.append('original' if value == original else 'candidate')
                if scenario == 'candidate_set_failure' and value == candidate:
                    raise RuntimeError('Fake candidate apply failure')
                if scenario == 'restore_failure' and len(calls) == 3:
                    raise RuntimeError('Fake restore failure')

        auto = Auto()

        class Device:
            def get_info(self, key):
                return '238222071455'

            def as_auto_calibrated_device(self):
                return auto

        fake = types.ModuleType('pyrealsense2')
        fake.camera_info = types.SimpleNamespace(serial_number=0)
        fake.context = lambda: types.SimpleNamespace(query_devices=lambda: [Device()])
        previous_sdk = sys.modules.get('pyrealsense2')
        sys.modules['pyrealsense2'] = fake
        spec = importlib.util.spec_from_file_location('comparison_under_test', Path(__file__).with_name('evaluate_onchip_ram.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_run = module.subprocess.run
        previous_argv = sys.argv

        def fake_capture(command, **kwargs):
            output = Path(command[command.index('--output')+1])
            output.mkdir()
            (output/'session.json').write_text(json.dumps(dict(pipeline_stopped=True,
                emitter_restore=dict(verified=True))), encoding='utf-8')
            failed = scenario == 'candidate_capture_failure' and output.name == 'candidate_volatile'
            return types.SimpleNamespace(returncode=1 if failed else 0, stdout='Fake capture\n', stderr='')

        try:
            module.subprocess.run = fake_capture
            sys.argv = ['evaluate_onchip_ram.py', '--original', str(folder/'original.bin'), '--candidate', str(folder/'candidate.bin'),
                        '--health-summary', str(folder/'health.json'), '--output', str(folder/'comparison')]
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = module.main()
            (folder/'simulated_stdout.txt').write_text(stream.getvalue(), encoding='utf-8')
        finally:
            module.subprocess.run = previous_run
            sys.argv = previous_argv
            if previous_sdk is None:
                del sys.modules['pyrealsense2']
            else:
                sys.modules['pyrealsense2'] = previous_sdk
        summary = json.loads((folder/'comparison'/'summary.json').read_text(encoding='utf-8'))
        expected_code = 0 if scenario == 'success' else 1
        expected_calls = [] if scenario == 'flash_mismatch' else ['original', 'candidate', 'original']
        if calls != expected_calls or code != expected_code:
            raise AssertionError((scenario, calls, code))
        if scenario not in ('restore_failure', 'flash_mismatch') and not summary['original_ram_restore_command_succeeded']:
            raise AssertionError('Cleanup was not executed')
        if scenario == 'restore_failure' and (summary['original_ram_restore_command_succeeded'] or not summary['errors']):
            raise AssertionError('Restore failure was hidden')
        results.append(dict(scenario=scenario, exit_code=code, ram_commands=calls, passed=True))
    report = dict(passed=True, camera_opened=False, physical_ground_truth=False, cases=results)
    (args.output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
