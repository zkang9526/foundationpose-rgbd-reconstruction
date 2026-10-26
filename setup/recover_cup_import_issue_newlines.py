#!/usr/bin/env python3
"""Recover only proven CRLF-to-LF changes after a failed cup-batch import.

Run on Ubuntu with --root /data/ZJC/foundationPos and --incoming pointing to
the existing failed stage. Verifies the whole ZIP, every staged file and every
recorded imported output before any repair. Does not re-import or append indexes.
Original failed import_report.json and successful journal appends are preserved.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from import_cup_offline_batch import (
    PROJECT_ROOT, file_fingerprint, json_bytes, publish_bytes, relative_to,
    route_member, safe_path, sha256_file, utc_now, verify_archive,
)


def checked_issue_newline_change(name, expected, actual):
    """Allow precisely one known byte transformation in historical run issues."""
    if not re.fullmatch(r"foundationpose_data/runs/[^/]+/issues\.md", name):
        raise ValueError("Unexpected changed output outside historical run issues: " + name)
    if b"\r\n" not in expected or expected == actual:
        raise ValueError("Changed issue does not contain a recoverable CRLF change: " + name)
    if expected.replace(b"\r\n", b"\n") != actual:
        raise ValueError("Issue differs by more than CRLF-to-LF normalization: " + name)
    # These are UTF-8 Markdown issue records, never arbitrary binary data.
    expected.decode("utf-8")
    actual.decode("utf-8")


def validate_failed_import(root, incoming, failed):
    if (failed.get("status") != "failed" or failed.get("passed") is not False
            or failed.get("archive_sha256_verified") is not True
            or failed.get("extraction_verified") is not True):
        raise ValueError("Recovery requires the original failed, fully extracted verified import")
    if failed.get("project_root") != str(root) or failed.get("incoming") != str(incoming):
        raise ValueError("Failed import belongs to a different project or incoming stage")
    batch_id = failed.get("batch_id")
    if not isinstance(batch_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", batch_id):
        raise ValueError("Failed report has an unsafe batch-id")
    error = failed.get("error", "")
    prefix = "Imported output changed before completion: "
    if not isinstance(error, str) or not error.startswith(prefix):
        raise ValueError("Failed import was not stopped by the final output checksum verification")
    if not re.fullmatch(r"foundationpose_data/runs/[^/]+/issues\.md", error[len(prefix):]):
        raise ValueError("Original final checksum failure is not a historical issues.md")
    commands = failed.get("append_commands")
    if not isinstance(commands, list) or len(commands) != 3:
        raise ValueError("Expected all three completed index/session append commands")
    expected_helpers = ["import_windows_run_records.py", "append_manual_records.py", "append_manual_records.py"]
    expected_events = [None, "CUP-REFERENCE-MASK-DEPTH-20261013", "CUP-RECONNECT-TEST-QA-20261013"]
    for item, helper, event in zip(commands, expected_helpers, expected_events):
        argv = item.get("argv")
        if (item.get("exit_code") != 0 or not isinstance(argv, list) or len(argv) < 2
                or argv[1] != str(root / "setup" / helper)):
            raise ValueError("Historical journal append did not complete successfully")
        if event is not None:
            if "--event-id" not in argv or argv.index("--event-id") + 1 >= len(argv):
                raise ValueError("Historical session append lacks event-id")
            if argv[argv.index("--event-id") + 1] != event:
                raise ValueError("Historical session append event-id differs")
    return batch_id


def expected_output(root, payload, name, entry, expected):
    if entry.get("source_sha256") != expected["sha256"] or entry.get("source_bytes") != expected["bytes"]:
        raise ValueError("Import entry no longer matches manifest: " + name)
    source = safe_path(payload, payload / name)
    relative, replaceable = route_member(name)
    if relative is None:
        if entry.get("target_relative") is not None or entry.get("action") != "staged_windows_note_only":
            raise ValueError("Unexpected staged-note output route: " + name)
        target = source
    else:
        if entry.get("target_relative") != relative:
            raise ValueError("Import output route differs from source route: " + name)
        target = safe_path(root, root / relative)
        if entry.get("action") not in ("identical_skip", "new_file_imported", "updated_with_backup"):
            raise ValueError("Import entry was not completely published: " + name)
    if entry.get("output_path") is not None and entry["output_path"] != str(target):
        raise ValueError("Recorded output_path differs from safe route: " + name)
    shell = name.startswith("setup/") and source.suffix == ".sh"
    expected_sha = (hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                    if shell else expected["sha256"])
    if entry.get("output_sha256") != expected_sha:
        raise ValueError("Recorded imported output SHA differs from allowed source transformation: " + name)
    if entry.get("planned_output_sha256", expected_sha) != expected_sha:
        raise ValueError("Planned imported output SHA differs from allowed source transformation: " + name)
    return source, target, expected_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--incoming", required=True, type=Path)
    args = parser.parse_args()
    report_path = None
    report = {"schema_version": 1, "start_utc": utc_now(), "passed": False,
              "status": "validating", "repairs": [], "network_or_ssh_used": False,
              "index_or_session_append_reexecuted": False, "rollback_on_failure": False,
              "failed_import_report_modified": False, "original_evidence_preserved": True}
    try:
        if not args.root.is_absolute() or os.name != "posix":
            raise ValueError("Recovery requires the absolute Ubuntu project /data/ZJC/foundationPos")
        root = args.root.resolve(strict=True)
        if root != PROJECT_ROOT.resolve(strict=True) or not root.is_dir():
            raise ValueError("Recovery requires the Ubuntu project /data/ZJC/foundationPos")
        incoming_arg = args.incoming if args.incoming.is_absolute() else Path.cwd() / args.incoming
        incoming = safe_path(root, incoming_arg)
        stage_relative = relative_to(incoming, root / "foundationpose_data/incoming")
        if stage_relative is None or not stage_relative.parts or not incoming.is_dir():
            raise ValueError("--incoming must be an existing stage below foundationpose_data/incoming")
        candidate_report = safe_path(root, incoming / "recovery_report.json")
        if os.path.lexists(str(candidate_report)):
            raise ValueError("Recovery evidence already exists; refusing another repair")
        report_path = candidate_report
        import_path = safe_path(root, incoming / "import_report.json")
        failed_raw = import_path.read_bytes()
        failed_sha = hashlib.sha256(failed_raw).hexdigest()
        failed = json.loads(failed_raw.decode("utf-8-sig"))
        batch_id = validate_failed_import(root, incoming, failed)
        report.update(project_root=str(root), incoming=str(incoming), batch_id=batch_id,
                      historical_import_failed=True, historical_import_error=failed["error"],
                      historical_import_report_path=str(import_path),
                      historical_import_report_sha256=failed_sha,
                      historical_journal_append_helpers_passed=True,
                      historical_append_commands=failed["append_commands"],
                      existing_journals_already_appended=True)
        archive_value = failed.get("archive")
        if not isinstance(archive_value, str) or not Path(archive_value).is_absolute():
            raise ValueError("Historical import archive path is invalid")
        archive_path = safe_path(incoming, Path(archive_value))
        expected, manifest_raw, fingerprint = verify_archive(archive_path, incoming, report)
        if (failed.get("archive_sha256") != report["archive_sha256"]
                or failed.get("manifest_sha256") != report["manifest_sha256"]
                or failed.get("verified_archive_files") != len(expected)):
            raise ValueError("Historical import checksum evidence differs from verified archive")
        payload = safe_path(root, incoming / "verified_payload")
        if not payload.is_dir() or failed.get("verified_payload") != str(payload):
            raise ValueError("Historical verified payload path differs from failed stage")
        if (safe_path(payload, payload / "manifest.json")).read_bytes() != manifest_raw:
            raise ValueError("Staged manifest differs from the verified ZIP")
        entries = failed.get("files")
        if not isinstance(entries, list) or len(entries) != len(expected):
            raise ValueError("Historical imported output list does not fully cover the archive")
        mapped = {}
        for item in entries:
            name = item.get("archive_path")
            if name not in expected or name in mapped:
                raise ValueError("Unexpected or duplicate historical import entry")
            mapped[name] = item
        plans = []
        outputs = []
        report["status"] = "verifying_every_payload_and_output_before_repair"
        for index, name in enumerate(sorted(expected), 1):
            source = safe_path(payload, payload / name)
            if source.stat().st_size != expected[name]["bytes"] or sha256_file(source) != expected[name]["sha256"]:
                raise ValueError("Verified payload changed: " + name)
            source, target, target_sha = expected_output(root, payload, name, mapped[name], expected[name])
            actual = sha256_file(target)
            output = {"archive_path": name, "output_path": str(target),
                      "expected_output_sha256": target_sha, "before_sha256": actual}
            outputs.append(output)
            if actual != target_sha:
                original, current = source.read_bytes(), target.read_bytes()
                checked_issue_newline_change(name, original, current)
                if hashlib.sha256(current).hexdigest() != actual:
                    raise RuntimeError("Issue changed while comparing newlines: " + name)
                plans.append({"name": name, "source": source, "target": target,
                              "before_sha256": actual, "expected_sha256": target_sha,
                              "before_fingerprint": file_fingerprint(target)})
            if index % 500 == 0 or index == len(expected):
                print(json.dumps({"stage": "preflight_checked", "files": index,
                                  "total": len(expected), "allowed_newline_repairs": len(plans)}), flush=True)
        if not plans:
            raise ValueError("No proven historical issues.md CRLF-to-LF changes require repair")
        report.update(verified_payload_files=len(expected), preflight_output_files=len(outputs),
                      every_payload_and_output_preflight_verified=True,
                      planned_newline_repairs=len(plans), outputs=outputs)
        backup_root = safe_path(root, root / "foundationpose_data/import_backups" /
                                (batch_id + "_newline_recovery"))
        if os.path.lexists(str(backup_root)):
            raise ValueError("Recovery backup directory already exists; refusing overwrite")
        backup_root.mkdir(parents=True)
        report.update(status="restoring_only_proven_issue_newline_changes", backup_root=str(backup_root))
        for plan in plans:
            source, target, name = plan["source"], plan["target"], plan["name"]
            if (file_fingerprint(target) != plan["before_fingerprint"]
                    or sha256_file(target) != plan["before_sha256"]
                    or sha256_file(source) != plan["expected_sha256"]):
                raise RuntimeError("Issue or payload changed after recovery preflight: " + name)
            backup = safe_path(root, backup_root / name)
            publish_bytes(target, backup, root, batch_id + "-newline-backup", plan["before_sha256"])
            if (file_fingerprint(target) != plan["before_fingerprint"]
                    or sha256_file(target) != plan["before_sha256"]):
                raise RuntimeError("Issue changed after backup: " + name)
            publish_bytes(source, target, root, batch_id + "-newline-repair",
                          plan["expected_sha256"], replace=True)
            report["repairs"].append({"archive_path": name, "target_path": str(target),
                                      "backup_path": str(backup),
                                      "backup_sha256": sha256_file(backup),
                                      "before_sha256": plan["before_sha256"],
                                      "restored_sha256": sha256_file(target),
                                      "expected_sha256": plan["expected_sha256"],
                                      "allowed_transformation_proved": "payload CRLF replaced by LF exactly equals prior imported bytes"})
        report["status"] = "final_verification_of_every_imported_output"
        for item in outputs:
            path = safe_path(root, Path(item["output_path"]))
            actual = sha256_file(path)
            item["final_sha256"] = actual
            if actual != item["expected_output_sha256"]:
                raise RuntimeError("Imported output changed during recovery: " + item["archive_path"])
        # Recheck stage source bytes as well as all imported outputs after repair.
        for name, item in expected.items():
            if sha256_file(safe_path(payload, payload / name)) != item["sha256"]:
                raise RuntimeError("Payload changed during recovery: " + name)
        if file_fingerprint(archive_path) != fingerprint or sha256_file(archive_path) != report["archive_sha256"]:
            raise RuntimeError("ZIP changed during recovery")
        if import_path.read_bytes() != failed_raw or sha256_file(import_path) != failed_sha:
            raise RuntimeError("Historical failed import report changed during recovery")
        report.update(status="passed", passed=True, end_utc=utc_now(),
                      repaired_issue_files=len(plans), imported_output_sha256_verified=True,
                      final_verified_output_files=len(outputs), final_verified_payload_files=len(expected),
                      historical_failed_import_preserved=True,
                      inference_or_reconstruction_executed=False)
        with report_path.open("xb") as output:
            output.write(json_bytes(report))
        print(json.dumps({"passed": True, "report": str(report_path), "batch_id": batch_id,
                          "repaired_issue_files": len(plans), "verified_output_files": len(outputs),
                          "historical_import_remains_failed_evidence": True,
                          "indexes_or_sessions_reappended": False}), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                      passed=False, end_utc=utc_now(), error_type=type(error).__name__, error=str(error))
        if report_path is not None:
            try:
                with report_path.open("xb") as output:
                    output.write(json_bytes(report))
            except OSError as output_error:
                print("Could not save recovery evidence: " + str(output_error), file=sys.stderr)
        print(json.dumps({"passed": False, "error_type": report["error_type"],
                          "error": report["error"], "report": str(report_path) if report_path else None}),
              file=sys.stderr, flush=True)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    sys.exit(main())
