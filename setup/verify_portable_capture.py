#!/usr/bin/env python3
"""Validate Unix-generated RGB-D samples on Windows before a camera is moved."""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sample = root / "foundationpose_data/portable_capture_validation_20261013"
result = subprocess.run([sys.executable, str(root / "setup/check_capture_files.py"), str(sample)], check=False)
if result.returncode:
    raise SystemExit(result.returncode)
report = {
    "passed": True,
    "scope": "Cross-platform saved RGB-D file validation only; no Windows camera streaming",
    "sample": str(sample),
    "source": "Ubuntu camera_capture_format_check_20261013: 30 paired frames",
}
(root / "reports/windows_portable_capture_validation_20261013.json").write_text(json.dumps(report, indent=2) + "\n")
