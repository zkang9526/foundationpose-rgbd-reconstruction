"""Operate an explicitly identified local calibration session with evidence."""
import argparse
import json
from pathlib import Path
import urllib.request

from common import now, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--expect-output', type=Path, required=True)
    p.add_argument('--action', choices=('status', 'capture', 'stop'), required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error('Use a new evidence file')
    base = 'http://127.0.0.1:%d' % a.port
    with urllib.request.urlopen(base + '/status', timeout=5) as response:
        before = json.load(response)
    if Path(before['output']).resolve() != a.expect_output.resolve():
        raise ValueError('Live session differs from explicitly expected output; control refused')
    report = dict(created_utc=now(), action=a.action, before=before)
    if a.action != 'status':
        request = urllib.request.Request(base + '/' + a.action, data=b'', method='POST',
                                         headers={'X-Calibration-Control': '1'})
        with urllib.request.urlopen(request, timeout=5) as response:
            report['http_status'] = response.status
            report['response'] = response.read().decode('utf-8')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(a.output, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
