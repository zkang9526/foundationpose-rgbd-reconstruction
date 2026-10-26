"""Exercise a dedicated live smoke server, never the operator's calibration session.

Checks the actual HTTP controls and recorded frame times, then stops the server.
Not a physical calibration accuracy test. Run through the project logger.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.request

import cv2
import numpy as np

from common import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new result file')
    base = 'http://127.0.0.1:%d' % args.port

    def get(path):
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.read()

    def post(path):
        request = urllib.request.Request(base + path, data=b'', method='POST',
                                         headers={'X-Calibration-Control': '1'})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 202

    report = dict(passed=False, physical_camera_accuracy_test=False)
    try:
        initial = json.loads(get('/status'))
        session = Path(initial['output'])
        # Refuse to control a human metrology session by accident.
        assert session.name.startswith('smoke_delay_'), 'Expected a dedicated smoke session'
        assert initial['trials'] == 0 and not initial['busy']
        html = get('/').decode('utf-8')
        board = initial['board']
        assert '%d×%d 内角点' % (board['cols'], board['rows']) in html
        assert '__BOARD_SPEC__' not in html and '__CAPTURE_DELAY__' not in html
        ir = cv2.imdecode(np.frombuffer(get('/ir_preview.jpg'), np.uint8), cv2.IMREAD_GRAYSCALE)
        assert ir.shape == (480, 1280)
        post('/capture')
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            state = json.loads(get('/status'))
            if state.get('last_trial') and not state['busy']:
                break
            time.sleep(.15)
        else:
            raise AssertionError('Delayed trial did not complete')
        trial = json.loads((session / 'trials' / '0001' / 'trial.json').read_text(encoding='utf-8'))
        info = trial['metadata']
        elapsed = info['monotonic_s'] - info['capture_request']['monotonic_s']
        assert elapsed >= initial['capture_delay_seconds'] - .15, 'Saved the click-time frame'
        assert 0 <= info['selected_frame_age_s'] <= .2
        assert state['trials'] == 1
        post('/capture')
        time.sleep(.25)
        post('/stop')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            final = json.loads((session / 'session.json').read_text(encoding='utf-8'))
            if final.get('ended_utc'):
                break
            time.sleep(.15)
        else:
            raise AssertionError('Stop did not finish')
        events = [json.loads(line) for line in (session / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
        assert final['trials'] == 1 and final['pipeline_stopped']
        assert any(event['action'] == 'capture_cancelled' for event in events)
        report.update(passed=True, session=str(session), board=board,
                      delayed_frame_elapsed_seconds=elapsed,
                      selected_frame_age_seconds=info['selected_frame_age_s'],
                      infrared_preview_shape=list(ir.shape),
                      cancelled_request_did_not_add_trial=True,
                      snapshot_not_physical_acceptance=True)
    except Exception as exc:
        report['error'] = repr(exc)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
