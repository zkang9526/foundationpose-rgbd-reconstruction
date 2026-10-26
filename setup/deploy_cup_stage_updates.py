#!/usr/bin/env python3
"""Deploy a small, hashed payload of cup helpers, guides and ended run evidence.

Ubuntu only. Stage files under incoming/<stage>/payload/<project-relative-path>
and pass a manifest {"files":[{"path":...,"sha256":...,"bytes":...}]}.
No archives, network, raw images, model data or environment files are handled.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from import_cup_offline_batch import (
    GUIDES, PROJECT_ROOT, canonical_member, file_fingerprint, json_bytes,
    publish_bytes, relative_to, safe_path, sha256_file, utc_now,
)


def deployment_scope(name):
    canonical_member(name if "/" in name else "windows_notes/" + name)
    parts = PurePosixPath(name).parts
    if len(parts) == 1 and name in GUIDES:
        return "guide", True
    if len(parts) == 2 and parts[0] == "setup" and PurePosixPath(name).suffix in {".py", ".sh", ".ps1"}:
        return "setup", True
    if len(parts) >= 2 and parts[0] == "reports":
        return "report", False
    if (len(parts) >= 4 and parts[:2] == ("foundationpose_data", "runs")
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,160}", parts[2])):
        return "ended_windows_run", False
    raise ValueError("File outside small update scopes: " + name)


def read_manifest(path):
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8-sig"))
    files = document.get("files") if isinstance(document, dict) else None
    if not isinstance(files, list) or not files or len(files) > 50000:
        raise ValueError("Manifest needs a nonempty files list of at most 50000 entries")
    expected = {}
    folded = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Manifest file must be an object")
        name, digest, size = item.get("path"), item.get("sha256"), item.get("bytes")
        if not isinstance(name, str):
            raise ValueError("Manifest path must be a string")
        kind, replaceable = deployment_scope(name)
        if (name.casefold() in folded or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
                or type(size) is not int or size < 0 or size > 256 * 1024 * 1024):
            raise ValueError("Invalid, duplicate or excessive manifest file: " + name)
        expected[name] = {"sha256": digest.lower(), "bytes": size,
                          "kind": kind, "replaceable": replaceable}
        folded.add(name.casefold())
    if sum(item["bytes"] for item in expected.values()) > 4 * 1024 ** 3:
        raise ValueError("Small update payload exceeds 4 GiB")
    return expected, hashlib.sha256(raw).hexdigest()


def preflight(root, payload, expected):
    actual_files = set()
    for directory, directories, files in os.walk(str(payload), followlinks=False):
        for name in directories + files:
            safe_path(payload, Path(directory) / name)
        for name in files:
            source = safe_path(payload, Path(directory) / name)
            if not source.is_file():
                raise ValueError("Payload entry is not a regular file")
            actual_files.add(source.relative_to(payload).as_posix())
    if actual_files != set(expected):
        raise ValueError("Staged payload file list differs from manifest")
    entries = []
    run_ids = set()
    for name in sorted(expected):
        item = expected[name]
        source, target = safe_path(payload, payload / name), safe_path(root, root / name)
        source_sha = sha256_file(source)
        if source.stat().st_size != item["bytes"] or source_sha != item["sha256"]:
            raise ValueError("Staged source differs from manifest: " + name)
        shell = item["kind"] == "setup" and source.suffix == ".sh"
        transformed = source.read_bytes().replace(b"\r\n", b"\n") if shell else None
        output_sha = hashlib.sha256(transformed).hexdigest() if shell else source_sha
        entry = {"path": name, "kind": item["kind"], "source_sha256": source_sha,
                 "source_bytes": item["bytes"], "output_sha256": output_sha,
                 "shell_crlf_to_lf": shell,
                 "shell_bytes_changed": shell and source_sha != output_sha,
                 "action": "new_file", "existing_sha256": None,
                 "existing_fingerprint": None}
        if os.path.lexists(str(target)):
            if not target.is_file():
                raise ValueError("Existing target is not a regular file: " + name)
            entry["existing_fingerprint"] = file_fingerprint(target)
            old_sha = sha256_file(target)
            entry["existing_sha256"] = old_sha
            if old_sha == output_sha:
                entry["action"] = "identical_skip"
            elif item["replaceable"]:
                entry["action"] = "replace_with_backup"
            else:
                raise ValueError("Existing report/run evidence differs; preserved without replacement: " + name)
        entries.append(entry)
        if item["kind"] == "ended_windows_run":
            run_ids.add(PurePosixPath(name).parts[2])
    for run_id in sorted(run_ids):
        name = "foundationpose_data/runs/" + run_id + "/run.json"
        if name not in expected:
            raise ValueError("Each staged run must include its ended run.json: " + run_id)
        run = json.loads((payload / name).read_text(encoding="utf-8-sig"))
        if (not isinstance(run.get("end"), str) or not run["end"]
                or type(run.get("exit_code")) is not int
                or run.get("status") not in ("passed", "failed", "interrupted")
                or not run.get("metadata", {}).get("platform", "").startswith("Windows")
                or run.get("run_id") != run_id):
            raise ValueError("Staged run is not an ended Windows record: " + run_id)
    if run_ids:
        # Refuse to append through the old helper which rewrites Windows issues.
        importer_name = "setup/import_windows_run_records.py"
        importer = payload / importer_name if importer_name in expected else root / importer_name
        syntax = ast.parse(safe_path(root, importer).read_text(encoding="utf-8-sig"))
        calls = [node for node in ast.walk(syntax) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "append_records"]
        if not calls or any(not any(keyword.arg == "write_run_issue"
                                    and isinstance(keyword.value, ast.Constant)
                                    and keyword.value.value is False
                                    for keyword in call.keywords) for call in calls):
            raise ValueError("Run import helper lacks explicit write_run_issue=False protection")
    return entries, sorted(run_ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--incoming", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--payload", type=Path, help="Defaults to incoming/payload")
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    report_path = None
    report = {"schema_version": 1, "start_utc": utc_now(), "passed": False,
              "status": "validating", "files": [], "network_or_ssh_used": False,
              "raw_or_model_data_modified": False, "server_journals_replaced": False,
              "rollback_on_failure": False, "partial_evidence_preserved": True}
    try:
        if not args.root.is_absolute() or os.name != "posix":
            raise ValueError("Deployment requires absolute Ubuntu project /data/ZJC/foundationPos")
        root = args.root.resolve(strict=True)
        if root != PROJECT_ROOT.resolve(strict=True) or not root.is_dir():
            raise ValueError("Deployment requires Ubuntu project /data/ZJC/foundationPos")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", args.batch_id):
            raise ValueError("batch-id must be a safe single directory name")
        incoming = safe_path(root, args.incoming if args.incoming.is_absolute() else Path.cwd() / args.incoming)
        relative = relative_to(incoming, root / "foundationpose_data/incoming")
        if relative is None or not relative.parts or not incoming.is_dir():
            raise ValueError("Incoming must be an existing stage below foundationpose_data/incoming")
        candidate_report = safe_path(root, incoming / "deployment_report.json")
        if os.path.lexists(str(candidate_report)):
            raise ValueError("deployment_report.json exists; use a fresh update stage")
        report_path = candidate_report
        manifest_arg = args.manifest if args.manifest.is_absolute() else Path.cwd() / args.manifest
        manifest = safe_path(incoming, manifest_arg)
        payload_arg = args.payload or incoming / "payload"
        payload = safe_path(incoming, payload_arg if payload_arg.is_absolute() else Path.cwd() / payload_arg)
        if payload == incoming or not payload.is_dir():
            raise ValueError("Payload must be an existing separate child folder inside incoming")
        expected, manifest_sha = read_manifest(manifest)
        entries, run_ids = preflight(root, payload, expected)
        backup_root = safe_path(root, root / "foundationpose_data/import_backups" / args.batch_id)
        if os.path.lexists(str(backup_root)):
            raise ValueError("Deployment backup batch already exists; use a new batch-id")
        report.update(project_root=str(root), incoming=str(incoming), payload=str(payload),
                      manifest=str(manifest), manifest_sha256=manifest_sha, batch_id=args.batch_id,
                      files=entries, ended_windows_runs=run_ids, preflight_passed=True,
                      backup_root=str(backup_root), status="deploying")
        backup_root.mkdir(parents=True)
        for entry in entries:
            name = entry["path"]
            source, target = safe_path(payload, payload / name), safe_path(root, root / name)
            if sha256_file(source) != entry["source_sha256"]:
                raise RuntimeError("Staged source changed since preflight: " + name)
            previous = entry["existing_fingerprint"]
            if previous is not None:
                if (not target.is_file() or file_fingerprint(target) != previous
                        or sha256_file(target) != entry["existing_sha256"]):
                    raise RuntimeError("Target changed since preflight: " + name)
            elif os.path.lexists(str(target)):
                raise RuntimeError("New target appeared since preflight: " + name)
            if entry["action"] == "identical_skip":
                continue
            replacing = entry["action"] == "replace_with_backup"
            if replacing:
                backup = safe_path(root, backup_root / name)
                publish_bytes(target, backup, root, args.batch_id, entry["existing_sha256"])
                entry.update(backup_path=str(backup), backup_sha256=sha256_file(backup))
                if file_fingerprint(target) != previous or sha256_file(target) != entry["existing_sha256"]:
                    raise RuntimeError("Target changed after backup: " + name)
            transformed = source.read_bytes().replace(b"\r\n", b"\n") if entry["shell_crlf_to_lf"] else None
            publish_bytes(source, target, root, args.batch_id, entry["output_sha256"],
                          transformed=transformed, replace=replacing)
            entry["action"] = "updated_with_backup" if replacing else "new_file_deployed"
        for entry in entries:
            if sha256_file(safe_path(root, root / entry["path"])) != entry["output_sha256"]:
                raise RuntimeError("Deployed output changed: " + entry["path"])
        if run_ids:
            report["status"] = "appending_ended_windows_run_indexes"
            command = [sys.executable, str(root / "setup/import_windows_run_records.py")]
            completed = subprocess.run(command, cwd=str(root), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            output = completed.stdout.decode("utf-8", errors="replace")
            report["run_index_append"] = {"argv": command, "exit_code": completed.returncode, "output": output}
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
            if completed.returncode != 0:
                raise RuntimeError("Protected Windows run index append failed")
        for entry in entries:
            if (sha256_file(safe_path(root, root / entry["path"])) != entry["output_sha256"]
                    or sha256_file(safe_path(payload, payload / entry["path"])) != entry["source_sha256"]):
                raise RuntimeError("Source/output changed after deployment or index append: " + entry["path"])
            entry["final_output_sha256_verified"] = True
        if sha256_file(manifest) != manifest_sha:
            raise RuntimeError("Manifest changed during deployment")
        report.update(status="passed", passed=True, end_utc=utc_now(),
                      verified_output_files=len(entries),
                      run_index_append_performed=bool(run_ids),
                      historical_run_issues_rewritten=False,
                      inference_or_reconstruction_executed=False)
        with report_path.open("xb") as output:
            output.write(json_bytes(report))
        print(json.dumps({"passed": True, "report": str(report_path), "files": len(entries),
                          "ended_windows_runs": len(run_ids)}, ensure_ascii=False), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                      passed=False, end_utc=utc_now(), error_type=type(error).__name__, error=str(error))
        if report_path is not None:
            try:
                with report_path.open("xb") as output:
                    output.write(json_bytes(report))
            except OSError as report_error:
                print("Could not save deployment evidence: " + str(report_error), file=sys.stderr)
        print(json.dumps({"passed": False, "error": report["error"],
                          "report": str(report_path) if report_path else None}), file=sys.stderr, flush=True)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    sys.exit(main())
