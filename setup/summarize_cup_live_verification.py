#!/usr/bin/env python3
"""Verify downloaded live-bridge smoke inputs, poses and overlays; export report."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--http-report-copy', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.http_report_copy.exists():
        p.error('Output reports must be new')
    failed = args.evidence / 'cup_live_replay_v1_20261014_2103'
    failed_report = json.loads((failed / 'session.json').read_text())
    assert not failed_report['passed'] and failed_report['completed_frames'] == 0
    assert 'verify_demo' in (failed / 'worker_stdout.log').read_text()
    folders = [args.evidence / 'cup_live_replay_v2_20261014_2107',
               args.evidence / 'cup_live_http_gpu_smoke_v1_20261014_2113/session']
    sessions = []
    for folder in folders:
        host = json.loads((folder / 'session.json').read_text())
        gpu = json.loads((folder / 'worker_report.json').read_text())
        assert host['passed'] and gpu['passed'] and host['source'] == 'offline_replay'
        verified = []
        requests = sorted((folder / 'requests').glob('*.json'))
        for path in requests:
            request = json.loads(path.read_text())
            frame = folder / 'frames' / path.stem
            resultpath = folder / 'responses' / path.name
            result = json.loads(resultpath.read_text())
            assert result['request_sha256'] == sha(path) and result['passed']
            for name, digest in request['input_sha256'].items():
                assert sha(frame / name) == digest
            assert sha(frame / 'pose_camera_from_mesh.txt') == result['pose_sha256']
            assert sha(frame / 'overlay.png') == result['overlay_sha256']
            assert json.loads((frame / 'result.json').read_text()) == result
            verified.append(dict(frame=path.stem, operation=request['operation'],
                                 request_sha256=sha(path), result_sha256=sha(resultpath)))
        assert len(requests) == host['completed_frames'] == gpu['frames_completed']
        sessions.append(dict(path=str(folder), frames=verified, host_report_sha256=sha(folder / 'session.json'),
                             worker_report_sha256=sha(folder / 'worker_report.json')))
    testpath = args.evidence / 'cup_live_http_gpu_smoke_v1_20261014_2113/report.json'
    test = json.loads(testpath.read_text())
    assert test['passed'] and all(test['checks'].values()) and not test['live_camera_validated']
    args.http_report_copy.write_bytes(testpath.read_bytes())
    report = dict(passed=True, scope='Transferred offline smoke evidence integrity',
                  live_camera_validated=False, pose_accuracy_validated=False,
                  failed_first_run_retained=True, verified_sessions=sessions,
                  test_report_sha256=sha(testpath), packages=test['packages'],
                  hardware_pending=True, sdk_device_count_at_test=test['sdk_device_count'])
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, sessions=len(sessions), frames=sum(len(s['frames']) for s in sessions),
                          live_camera_validated=False, output=str(args.output))))


if __name__ == '__main__':
    main()
