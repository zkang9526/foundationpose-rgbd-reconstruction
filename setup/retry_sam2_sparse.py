"""Stop only the exact slow SAM2 clone, preserve partial bytes, retry sparse source."""
import os
from pathlib import Path
import signal
import time

source = Path('/data/ZJC/foundationPos/foundationpose_data/tools/sam2')
assert source.resolve().parent == Path('/data/ZJC/foundationPos/foundationpose_data/tools').resolve()
pids = []
for path in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        argv = path.read_bytes().split(b'\0')
    except OSError:
        continue
    if argv and Path(os.fsdecode(argv[0])).name == 'git' and b'clone' in argv and os.fsencode(str(source)) in argv:
        pid = int(path.parent.name)
        os.kill(pid, signal.SIGTERM)
        pids.append(pid)
time.sleep(2)
if not pids:
    raise RuntimeError('Exact clone no longer running; inspect before retry')
backup = source.with_name('sam2_partial_clone_20261015_1319')
if backup.exists():
    raise RuntimeError('Partial clone archive already exists')
source.rename(backup)
print('Stopped exact SAM2 clone PIDs:', pids, '; partial evidence preserved:', backup)
