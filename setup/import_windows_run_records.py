#!/usr/bin/env python3
"""Append transferred Windows run records to Ubuntu indexes without replacing them."""
import json
from pathlib import Path

from run_logged import append_records

root = Path("/data/ZJC/foundationPos")
index = root / "EXPERIMENT_LOG.md"
known = index.read_text(encoding="utf-8") if index.exists() else ""
imported = []
for path in sorted((root / "foundationpose_data/runs").glob("*/run.json")):
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("end") is None or report.get("exit_code") is None:
        continue
    if not report.get("metadata", {}).get("platform", "").startswith("Windows"):
        continue
    relative = path.parent.relative_to(root).as_posix()
    if relative in known:
        continue
    # Imported run directories are immutable evidence. Only append server indexes;
    # regenerating issues.md here would change historical Windows CRLF bytes.
    append_records(root, path.parent, report, write_run_issue=False)
    known += "\n" + relative
    imported.append(report.get("run_id", path.parent.name))
print(json.dumps({"imported_windows_runs": imported, "count": len(imported)}))
