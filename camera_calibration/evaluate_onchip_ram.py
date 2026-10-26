"""Compare saved on-chip candidate in volatile RAM, then restore original.

Never calls write_calibration, reset_to_factory_calibration or a calibration
routine. get_calibration_table reads flash; restoration is commanded explicitly
and independently checked by a final native dual-IR acquisition.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

import pyrealsense2 as rs


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--health-summary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    reference = json.loads(a.health_summary.read_text(encoding='utf-8'))
    if sha(a.original) != reference['calibration_table_before']['sha256']:
        raise ValueError('Original table provenance mismatch')
    candidate_meta = reference['scans'][0]['candidate_table']
    if reference['scans'][0]['name'] != 'intrinsic' or sha(a.candidate) != candidate_meta['sha256']:
        raise ValueError('Candidate provenance mismatch')
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    source = a.output / 'source'
    source.mkdir()
    root = Path(__file__).parent
    for f in (Path(__file__), root/'capture_ir_pair_check.py', root/'common.py', root/'board.json'):
        shutil.copy2(f, source/f.name)
    original, candidate = a.original.read_bytes(), a.candidate.read_bytes()
    shutil.copy2(a.original, a.output/'original_table.bin')
    shutil.copy2(a.candidate, a.output/'candidate_table.bin')
    status = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  serial='238222071455', persistent_write_implemented=False,
                  volatile_tables_explicitly_switched=True, original_sha256=sha(a.original),
                  candidate_sha256=sha(a.candidate), health_summary_sha256=sha(a.health_summary),
                  runs=[], errors=[], original_ram_restore_command_succeeded=False,
                  scope='Short native-IR consistency comparison only; not absolute depth or RGB-D boundary acceptance')
    write(a.output/'summary.json', status)
    device = auto = None
    baseline_verified = False
    code = 1

    def capture(label):
        target = a.output/label
        command = [sys.executable, '-B', str(root/'capture_ir_pair_check.py'), '--output', str(target),
                   '--operator-static-reported', '--note', 'User reports fixed camera and raised checkerboard; volatile calibration state '+label]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        (a.output/(label+'_stdout.txt')).write_text(result.stdout, encoding='utf-8')
        (a.output/(label+'_stderr.txt')).write_text(result.stderr, encoding='utf-8')
        row = dict(label=label, command=command, exit_code=result.returncode, output=str(target))
        state_path = target/'session.json'
        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding='utf-8'))
            row['raw_dy_by_algorithm'] = state.get('all_points_raw_dy_by_algorithm')
            row['emitter_restore'] = state.get('emitter_restore')
            row['pipeline_stopped'] = state.get('pipeline_stopped')
        status['runs'].append(row)
        write(a.output/'summary.json', status)
        print(json.dumps(row), flush=True)
        if result.returncode:
            raise RuntimeError('Native IR acquisition failed: '+label)

    try:
        context = rs.context()
        matches = [d for d in context.query_devices() if d.get_info(rs.camera_info.serial_number)==status['serial']]
        if len(matches)!=1:
            raise RuntimeError('Expected exact device serial')
        device = matches[0]
        auto = device.as_auto_calibrated_device()
        flash = bytes(auto.get_calibration_table())
        (a.output/'flash_before.bin').write_bytes(flash)
        if flash != original:
            raise RuntimeError('Current flash differs from original backup; refusing comparison')
        baseline_verified = True
        auto.set_calibration_table(list(original))
        status['initial_original_ram_command_succeeded'] = True
        capture('original_before')
        auto.set_calibration_table(list(candidate))
        status['candidate_ram_command_succeeded'] = True
        capture('candidate_volatile')
        code = 0
    except BaseException as e:
        status['errors'].append(dict(phase='comparison', message=str(e), traceback=traceback.format_exc()))
        code = 130 if isinstance(e, KeyboardInterrupt) else 1
    finally:
        if auto is not None and baseline_verified:
            try:
                auto.set_calibration_table(list(original))
                status['original_ram_restore_command_succeeded'] = True
                flash_after = bytes(auto.get_calibration_table())
                (a.output/'flash_after.bin').write_bytes(flash_after)
                status['flash_unchanged_verified'] = flash_after == original
                if not status['flash_unchanged_verified']:
                    raise RuntimeError('Persistent table mismatch')
                capture('original_restored')
            except BaseException as e:
                code = 1
                status['errors'].append(dict(phase='restore_or_verify', message=str(e), traceback=traceback.format_exc()))
        status.update(ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), exit_code=code)
        write(a.output/'summary.json', status)
        files = [dict(path=str(f.relative_to(a.output)), sha256=sha(f), bytes=f.stat().st_size)
                 for f in sorted(a.output.rglob('*')) if f.is_file()]
        write(a.output/'manifest.json', dict(files=files))
        print(json.dumps(dict(output=str(a.output), exit_code=code,
                              original_ram_restore_command_succeeded=status['original_ram_restore_command_succeeded'],
                              flash_unchanged_verified=status.get('flash_unchanged_verified'))), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
