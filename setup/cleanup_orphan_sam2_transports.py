"""Terminate only orphan process groups from this task's interrupted SAM2 clone."""
import os
from pathlib import Path
import signal

groups = set()
for path in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        argv = path.read_bytes().split(b'\0')
        if b'https://github.com/facebookresearch/sam2.git' not in argv:
            continue
        stat = (path.parent / 'stat').read_text().split(') ', 1)[1].split()
        group = int(stat[2])
        leader = Path('/proc') / str(group) / 'cmdline'
        if not leader.exists() or not leader.read_bytes():
            groups.add(group)
    except OSError:
        continue
for group in groups:
    os.killpg(group, signal.SIGTERM)
print('Orphan SAM2 clone process groups stopped:', sorted(groups))
