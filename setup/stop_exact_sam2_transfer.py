"""Stop only this task's explicit transfer/provision subprocess group."""
import argparse
import os
from pathlib import Path
import signal

p = argparse.ArgumentParser()
p.add_argument('--phase', choices=['download', 'install', 'assets'], required=True)
args = p.parse_args()
expected = '/data/ZJC/foundationPos/foundationpose_data/incoming/' + {'download': 'download_sam2_torch_wheel.py', 'install': 'provision_cup_sam2_sparse2.py', 'assets': 'provision_cup_sam2_cached.py'}[args.phase]
relative = 'foundationpose_data/incoming/' + expected.rsplit('/', 1)[1]
stopped = []
for entry in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        argv = entry.read_bytes().split(b'\0')
        if not argv or 'python' not in Path(os.fsdecode(argv[0])).name:
            continue
        if os.fsencode(expected) not in argv and os.fsencode(relative) not in argv:
            continue
        if args.phase == 'assets' and b'--assets-only' not in argv:
            continue
        pid = int(entry.parent.name)
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        stopped.append(pid)
    except (OSError, ProcessLookupError):
        continue
print('Stopped exact task process groups:', stopped)
