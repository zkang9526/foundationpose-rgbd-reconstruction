#!/usr/bin/env python3
"""Append evidence-based session notes without replacing existing Ubuntu indexes."""
import argparse
from pathlib import Path
import os
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--event-id", required=True)
parser.add_argument("--experiment", type=Path, required=True)
parser.add_argument("--issues", type=Path, required=True)
parser.add_argument("--root", type=Path, default=Path("/data/ZJC/foundationPos"),
                    help="Project root; default retains existing Ubuntu behavior")
args = parser.parse_args()
root = args.root.resolve(strict=True)
marker = "<!-- " + args.event_id + " -->"
with (root / ".records.lock").open("a+b") as lock:
    if sys.platform.startswith("linux"):
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    elif os.name == "nt":
        import msvcrt
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
    try:
        for target, source in ((root / "EXPERIMENT_LOG.md", args.experiment), (root / "ISSUES.md", args.issues)):
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            if marker not in existing:
                with target.open("a", encoding="utf-8") as stream:
                    stream.write("\n" + marker + "\n" + source.read_text(encoding="utf-8") + "\n")
    finally:
        if sys.platform.startswith("linux"):
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        elif os.name == "nt":
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
print("Session notes archived:", args.event_id)
