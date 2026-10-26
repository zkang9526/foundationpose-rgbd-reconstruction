#!/usr/bin/env python3
"""Verify actual Linux execution records; close only the deliberate failure test."""
import datetime
import json
from pathlib import Path

root = Path("/data/ZJC/foundationPos")
runs = root / "foundationpose_data/runs"


def newest(label):
    choices = []
    for path in runs.glob("*/run.json"):
        report = json.loads(path.read_text())
        if report.get("label") == label:
            choices.append((report["start"], path.parent, report))
    assert choices, "Missing actual run: " + label
    return sorted(choices, key=lambda value: value[0])[-1][1:]


passed_dir, passed = newest("d435i_format_check")
failed_dir, failed = newest("logging_expected_failure")
assert passed["status"] == "passed" and passed["exit_code"] == 0
assert failed["status"] == "failed" and failed["child_exitcode"] == failed["exit_code"] == 7
for run_dir, report in ((passed_dir, passed), (failed_dir, failed)):
    assert report["start"] and report["end"] and report["duration_seconds"] >= 0
    assert (run_dir / "command.txt").read_text().strip() == report["command"]
    assert (run_dir / "environment.json").is_file()
    assert (run_dir / "notes.md").is_file()
    assert (run_dir / "source/run_logged.py").is_file()
    assert "append failed" not in " ".join(report["warnings"]).lower()
console = (failed_dir / "console.log").read_text()
assert "LOGGER_STDOUT_MARKER" in console and "LOGGER_STDERR_MARKER" in console
assert (failed_dir / "issues.md").is_file()
assert failed_dir.relative_to(root).as_posix() in (root / "ISSUES.md").read_text()
assert passed_dir.relative_to(root).as_posix() in (root / "EXPERIMENT_LOG.md").read_text()
summary = {
    "passed": True, "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "scope": "Logging infrastructure validation; no new camera capture or model inference",
    "successful_run": str(passed_dir), "expected_failed_run": str(failed_dir),
    "expected_failed_exit_code": 7,
    "checks": ["command", "stdout_and_stderr", "exit_code", "timing", "environment",
               "source_snapshot", "notes", "experiment_index", "issue_index"],
}
destination = root / "foundationpose_data/logging_validation_20261013.json"
destination.write_text(json.dumps(summary, indent=2) + "\n")
resolution = (
    "\n## 留档验证结论：预期失败测试已验证\n\n"
    "- 验证时间：{}。\n"
    "- 运行目录：`{}`。\n"
    "- 此命令人为退出 7，符合预期；stdout、stderr、退出码及问题证据均保留。\n"
    "- 最新状态：验证完成，非实际相机或模型故障；保留原始失败记录。\n"
    "- 复验依据：`foundationpose_data/logging_validation_20261013.json`。\n"
).format(summary["checked_at_utc"], failed_dir.relative_to(root).as_posix())
with (root / ".records.lock").open("a") as lock:
    import fcntl
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    for path in (root / "ISSUES.md", root / "EXPERIMENT_LOG.md", failed_dir / "issues.md"):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(resolution)
print(json.dumps(summary, ensure_ascii=False))
