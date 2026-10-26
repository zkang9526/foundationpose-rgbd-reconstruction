#!/usr/bin/env python3
"""Refresh repository metadata without repeating the completed GPU tests."""
import json
import subprocess
from pathlib import Path

path = Path("/data/environment_verification.json")
report = json.loads(path.read_text())
result = subprocess.run(["git", "-C", "/workspace/FoundationPose", "rev-parse", "HEAD"],
                        capture_output=True, text=True, check=True)
report["runtime"]["git_commit"] = {"available": True, "returncode": result.returncode,
                                   "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
path.write_text(json.dumps(report, indent=2) + "\n")
print("Recorded repository commit:", result.stdout.strip())
