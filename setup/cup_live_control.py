#!/usr/bin/env python3
"""Save an explicit local bridge control/status response and display snapshots."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--action', choices=('status', 'freeze', 'mask', 'initialize', 'pause', 'stop'), default='status')
    p.add_argument('--data', type=Path, help='JSON object sent to the selected control endpoint')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--port', type=int, default=8765)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = 'http://127.0.0.1:' + str(args.port)
    request_data = json.loads(args.data.read_text()) if args.data else {}
    request = urllib.request.Request(base + '/' + args.action)
    if args.action != 'status':
        request = urllib.request.Request(base + '/' + args.action, data=json.dumps(request_data).encode(),
                                         headers={'Content-Type': 'application/json'})
    (args.output / 'request.json').write_text(json.dumps(dict(action=args.action, input=request_data), indent=2) + '\n')
    try:
        with urllib.request.urlopen(request, timeout=115) as stream:
            result = json.loads(stream.read())
    except urllib.error.HTTPError as error:
        (args.output / 'failure.json').write_bytes(error.read())
        raise
    (args.output / 'response.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.action != 'stop':
        with urllib.request.urlopen(base + '/status', timeout=5) as stream:
            state = json.loads(stream.read())
        (args.output / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
        for name in ('preview.jpg', 'overlay.jpg'):
            try:
                with urllib.request.urlopen(base + '/' + name, timeout=5) as stream:
                    (args.output / name).write_bytes(stream.read())
            except urllib.error.HTTPError as error:
                if error.code != 503:
                    raise
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
