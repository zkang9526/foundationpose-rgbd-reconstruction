#!/usr/bin/env python3
"""Verify and import one staged Windows cup batch into the Ubuntu project.

Python 3.8+, standard library only. No network access or archive instructions are
executed. Existing data is never replaced. Changed setup sources and selected
guides are backed up before replacement; server journals are appended by the
existing project helpers. Failure evidence and partial imports are retained.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile


PROJECT_ROOT = Path("/data/ZJC/foundationPos")
CHUNK_BYTES = 1024 * 1024
GUIDES = {
    "AGENTS.md", "REPRODUCTION_GUIDE.md", "CUP_NEXT_STEPS_20261013.md",
    "CUP_MANUAL_PHOTOS.md", "POSE_AND_TRAINING_GUIDE.md",
    "CUP_UBUNTU_RECONSTRUCTION_20261013.md",
    "README.md",
}
DATA_PREFIXES = (
    "foundationpose_data/windows_captures/", "foundationpose_data/derived/",
    "foundationpose_data/runs/", "reports/",
)
EXCLUDED_COMPONENTS = {
    ".git", ".ssh", ".aws", ".azure", ".kube", ".gnupg", ".venv",
    "venv", "env", ".env", ".windows-camera-venv", "__pycache__",
    "node_modules", ".conda", "site-packages", "weights", "checkpoints",
    "foundationpose", "foundationpose-conda",
}
EXCLUDED_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials",
    "credentials.json", "known_hosts", "authorized_keys", "environment.txt", "environ.txt",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pem", ".key", ".pfx", ".p12",
                     ".pt", ".pth", ".ckpt", ".onnx", ".safetensors"}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def relative_to(path, root):
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def safe_path(root, path):
    """Reject outside-root targets and any symlink/junction below the root."""
    lexical = Path(os.path.abspath(str(path)))
    relative = relative_to(lexical, root)
    if relative is None:
        raise ValueError("Path is outside the project: {}".format(path))
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Symlink is not allowed for import paths: {}".format(relative))
        if relative_to(cursor.resolve(strict=False), root) is None:
            raise ValueError("Path resolves outside the project: {}".format(relative))
    return lexical


def file_fingerprint(path):
    details = path.stat()
    return (details.st_dev, details.st_ino, details.st_size,
            details.st_mtime_ns, details.st_ctime_ns)


def sha256_file(path):
    before = file_fingerprint(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while True:
            block = source.read(CHUNK_BYTES)
            if not block:
                break
            size += len(block)
            digest.update(block)
    if file_fingerprint(path) != before or size != before[2]:
        raise RuntimeError("File changed while hashing: {}".format(path))
    return digest.hexdigest()


def canonical_member(name):
    if not isinstance(name, str) or not name:
        raise ValueError("Archive member name must be a nonempty string")
    if (name.startswith("/") or "\\" in name or ":" in name
            or any(ord(character) < 32 or ord(character) == 127 for character in name)):
        raise ValueError("Unsafe archive member name: {!r}".format(name))
    path = PurePosixPath(name)
    if (".." in path.parts or "." in name.split("/")
            or path.as_posix() != name or name.endswith("/")):
        raise ValueError("Noncanonical archive member name: {!r}".format(name))
    folded = [part.casefold() for part in path.parts]
    if (any(part in EXCLUDED_COMPONENTS for part in folded)
            or folded[-1] in EXCLUDED_NAMES or folded[-1].startswith(".env.")
            or path.suffix.casefold() in EXCLUDED_SUFFIXES):
        raise ValueError("Excluded private, environment or model member: {}".format(name))
    if name == "manifest.json":
        return name
    allowed = any(name.startswith(prefix) for prefix in DATA_PREFIXES)
    allowed = allowed or name.startswith("setup/")
    if name.startswith("windows_notes/"):
        allowed = len(path.parts) == 2 and path.suffix.casefold() == ".md"
    if not allowed:
        raise ValueError("Archive member is outside explicit import scopes: {}".format(name))
    return name


def expected_zip_sha256(sums, archive_name):
    matches = []
    for line in sums.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+[ *]?([^/\\]+)", line.strip())
        if not match:
            raise ValueError("Invalid SHA256SUMS entry")
        if match.group(2) == archive_name:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise ValueError("SHA256SUMS must contain exactly one matching archive entry")
    return matches[0]


def verify_archive(archive_path, incoming, report):
    sums = safe_path(incoming, incoming / "SHA256SUMS.txt")
    expected_sha256 = expected_zip_sha256(sums, archive_path.name)
    archive_fingerprint = file_fingerprint(archive_path)
    actual_sha256 = sha256_file(archive_path)
    if file_fingerprint(archive_path) != archive_fingerprint:
        raise RuntimeError("ZIP changed while checking uploaded SHA256")
    if actual_sha256 != expected_sha256:
        raise RuntimeError("Uploaded ZIP SHA256 differs from SHA256SUMS")
    report.update(archive_sha256=actual_sha256, archive_sha256_verified=True)
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > 100000:
            raise ValueError("Archive has too many members")
        names = []
        for info in infos:
            canonical_member(info.filename)
            mode = (info.external_attr >> 16) & 0xffff
            file_type = stat.S_IFMT(mode)
            if info.is_dir() or file_type not in (0, stat.S_IFREG):
                raise ValueError("Archive links, directories and special files are refused: {}".format(info.filename))
            if info.flag_bits & 1:
                raise ValueError("Encrypted archive entries are refused")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("Unsupported archive compression")
            names.append(info.filename)
        if len(names) != len({name.casefold() for name in names}):
            raise ValueError("Duplicate portable archive member names")
        if names.count("manifest.json") != 1:
            raise ValueError("Archive must contain one root manifest.json")
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > 64 * 1024 * 1024:
            raise ValueError("Manifest exceeds the size limit")
        manifest_raw = archive.read("manifest.json")
        manifest = json.loads(manifest_raw.decode("utf-8-sig"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
            raise ValueError("Manifest must contain a files list")
        expected = {}
        for item in manifest["files"]:
            if not isinstance(item, dict):
                raise ValueError("Manifest file entry must be an object")
            name = canonical_member(item.get("path"))
            digest = item.get("sha256")
            size = item.get("bytes")
            if (name == "manifest.json" or name in expected
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
                    or type(size) is not int or size < 0 or size > 4 * 1024 ** 3):
                raise ValueError("Invalid or duplicate manifest file entry: {}".format(name))
            expected[name] = {"sha256": digest.lower(), "bytes": size}
        if set(names) != set(expected) | {"manifest.json"}:
            raise ValueError("Archive member list differs from manifest")
        if sum(item["bytes"] for item in expected.values()) > 64 * 1024 ** 3:
            raise ValueError("Archive uncompressed payload exceeds the size limit")
        for name in sorted(expected):
            if archive.getinfo(name).file_size != expected[name]["bytes"]:
                raise RuntimeError("ZIP entry size differs from manifest: {}".format(name))
            digest = hashlib.sha256()
            size = 0
            with archive.open(name, "r") as source:
                while True:
                    block = source.read(CHUNK_BYTES)
                    if not block:
                        break
                    digest.update(block)
                    size += len(block)
            if size != expected[name]["bytes"] or digest.hexdigest() != expected[name]["sha256"]:
                raise RuntimeError("ZIP entry SHA256 mismatch: {}".format(name))
    if file_fingerprint(archive_path) != archive_fingerprint:
        raise RuntimeError("ZIP changed during verification")
    outside_manifest = safe_path(incoming, incoming / "manifest.json")
    if outside_manifest.exists() and outside_manifest.read_bytes() != manifest_raw:
        raise RuntimeError("Transferred outer manifest differs from ZIP manifest")
    package_report_path = safe_path(incoming, incoming / "package_report.json")
    if package_report_path.exists():
        package_report = json.loads(package_report_path.read_text(encoding="utf-8-sig"))
        if (package_report.get("passed") is not True
                or package_report.get("archive_sha256") != actual_sha256
                or package_report.get("manifest_sha256") != hashlib.sha256(manifest_raw).hexdigest()):
            raise RuntimeError("Transferred package report does not match the verified ZIP")
    report.update(manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                  verified_archive_files=len(expected), readiness=manifest.get("readiness"),
                  skipped_running_runs=manifest.get("skipped_running_runs", []))
    return expected, manifest_raw, archive_fingerprint


def extract_verified(archive_path, incoming, expected, manifest_raw, fingerprint, report):
    payload = safe_path(incoming, incoming / "verified_payload")
    if os.path.lexists(str(payload)):
        raise ValueError("verified_payload already exists; use a new incoming stage")
    payload.mkdir()
    report["verified_payload"] = str(payload)
    with zipfile.ZipFile(archive_path, "r") as archive:
        for index, name in enumerate(sorted(expected), 1):
            target = safe_path(payload, payload / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with archive.open(name, "r") as source, target.open("xb") as output:
                while True:
                    block = source.read(CHUNK_BYTES)
                    if not block:
                        break
                    output.write(block)
                    digest.update(block)
                    size += len(block)
            target.chmod(0o644)
            if size != expected[name]["bytes"] or digest.hexdigest() != expected[name]["sha256"]:
                raise RuntimeError("Extraction SHA256 mismatch: {}".format(name))
            if index % 200 == 0 or index == len(expected):
                print(json.dumps({"stage": "extracted", "files": index, "total": len(expected)}), flush=True)
    with (payload / "manifest.json").open("xb") as output:
        output.write(manifest_raw)
    if file_fingerprint(archive_path) != fingerprint:
        raise RuntimeError("ZIP changed during extraction")
    report["extraction_verified"] = True
    return payload


def route_member(name):
    if name.startswith("windows_notes/"):
        basename = PurePosixPath(name).name
        if basename in GUIDES:
            return basename, True
        return None, False
    return name, name.startswith("setup/")


def preflight(root, payload, expected, report):
    plans = []
    entries = []
    report["files"] = entries
    for name in sorted(expected):
        source = safe_path(payload, payload / name)
        source_sha256 = sha256_file(source)
        if source_sha256 != expected[name]["sha256"]:
            raise RuntimeError("Verified payload changed: {}".format(name))
        target_relative, replaceable = route_member(name)
        entry = {"archive_path": name, "source_sha256": source_sha256,
                 "source_bytes": expected[name]["bytes"]}
        entries.append(entry)
        if target_relative is None:
            entry.update(action="staged_windows_note_only", output_path=str(source),
                         output_sha256=source_sha256)
            continue
        target = safe_path(root, root / target_relative)
        normalize_shell = name.startswith("setup/") and source.suffix == ".sh"
        transformed = None
        if normalize_shell:
            shell_raw = source.read_bytes()
            if hashlib.sha256(shell_raw).hexdigest() != source_sha256:
                raise RuntimeError("Staged shell source changed: {}".format(name))
            transformed = shell_raw.replace(b"\r\n", b"\n")
        output_sha256 = hashlib.sha256(transformed).hexdigest() if transformed is not None else source_sha256
        entry.update(target_relative=target_relative, planned_output_sha256=output_sha256,
                     shell_crlf_to_lf=normalize_shell,
                     shell_bytes_changed=normalize_shell and output_sha256 != source_sha256)
        existing_fingerprint = None
        if os.path.lexists(str(target)):
            if not target.is_file():
                raise ValueError("Import target is not a regular file: {}".format(target_relative))
            existing_fingerprint = file_fingerprint(target)
            old_sha256 = sha256_file(target)
            entry["existing_sha256"] = old_sha256
            if old_sha256 == output_sha256:
                entry.update(action="identical_skip", output_sha256=old_sha256)
                continue
            if not replaceable:
                entry.update(action="conflict_preserved", output_sha256=old_sha256)
                report["conflicts"].append({"target_relative": target_relative,
                                           "existing_sha256": old_sha256,
                                           "incoming_sha256": output_sha256})
                continue
        entry["action"] = "replace_with_backup" if existing_fingerprint is not None else "new_file"
        plans.append({"source": source, "target": target, "relative": target_relative,
                      "transformed": transformed, "existing_fingerprint": existing_fingerprint,
                      "entry": entry})
    if report["conflicts"]:
        raise RuntimeError("Data conflicts were preserved; {} files require review".format(len(report["conflicts"])))
    # Both journal append helpers are explicitly authorized project tools.
    required = ("setup/import_windows_run_records.py", "setup/append_manual_records.py",
                "reports/CUP_REFERENCE_SESSION_EXPERIMENT_20261013.md",
                "reports/CUP_REFERENCE_SESSION_ISSUES_20261013.md",
                "reports/CUP_RECONNECT_TEST_EXPERIMENT_20261013.md",
                "reports/CUP_RECONNECT_TEST_ISSUES_20261013.md")
    planned_targets = {plan["relative"] for plan in plans}
    for name in required:
        if name not in planned_targets and not safe_path(root, root / name).is_file():
            raise ValueError("Required append helper or session note is missing: {}".format(name))
    return plans


def publish_bytes(source, target, root, batch_id, expected_sha256, transformed=None, replace=False):
    safe_path(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, target.parent)
    temporary = safe_path(root, target.parent / ("." + target.name + ".import-" + batch_id + ".tmp"))
    digest = hashlib.sha256()
    with temporary.open("xb") as output:
        if transformed is not None:
            output.write(transformed)
            digest.update(transformed)
        else:
            with source.open("rb") as input_file:
                while True:
                    block = input_file.read(CHUNK_BYTES)
                    if not block:
                        break
                    output.write(block)
                    digest.update(block)
        output.flush()
        os.fsync(output.fileno())
    if digest.hexdigest() != expected_sha256:
        raise RuntimeError("Copy checksum mismatch; temporary file retained: {}".format(temporary))
    temporary.chmod(0o755 if target.suffix == ".sh" else 0o644)
    safe_path(root, target)
    if replace:
        os.replace(str(temporary), str(target))
    else:
        # A hard-link publish is atomic and refuses a newly appeared destination.
        os.link(str(temporary), str(target))
        temporary.unlink()
    if sha256_file(target) != expected_sha256:
        raise RuntimeError("Published file checksum mismatch: {}".format(target))


def apply_plans(root, plans, batch_id, report):
    backup_root = safe_path(root, root / "foundationpose_data/import_backups" / batch_id)
    if os.path.lexists(str(backup_root)):
        raise ValueError("Backup batch already exists; use a new batch-id")
    report["backup_root"] = str(backup_root)
    for index, plan in enumerate(plans, 1):
        source, target, entry = plan["source"], plan["target"], plan["entry"]
        report["current_target_relative"] = plan["relative"]
        safe_path(root, target)
        if sha256_file(source) != entry["source_sha256"]:
            raise RuntimeError("Staged source changed before import: {}".format(entry["archive_path"]))
        replacing = plan["existing_fingerprint"] is not None
        if replacing:
            if (not target.exists() or file_fingerprint(target) != plan["existing_fingerprint"]
                    or sha256_file(target) != entry["existing_sha256"]):
                raise RuntimeError("Existing target changed since preflight: {}".format(plan["relative"]))
            backup = safe_path(root, backup_root / plan["relative"])
            publish_bytes(target, backup, root, batch_id, entry["existing_sha256"])
            entry.update(backup_relative=backup.relative_to(root).as_posix(),
                         backup_sha256=sha256_file(backup))
            if file_fingerprint(target) != plan["existing_fingerprint"]:
                raise RuntimeError("Existing target changed after backup: {}".format(plan["relative"]))
        elif os.path.lexists(str(target)):
            raise RuntimeError("New target appeared since preflight: {}".format(plan["relative"]))
        publish_bytes(source, target, root, batch_id, entry["planned_output_sha256"],
                      transformed=plan["transformed"], replace=replacing)
        entry.update(action="updated_with_backup" if replacing else "new_file_imported",
                     output_sha256=sha256_file(target), output_bytes=target.stat().st_size)
        report["applied_files"] = index
        if index % 200 == 0 or index == len(plans):
            print(json.dumps({"stage": "imported", "files": index, "total": len(plans)}), flush=True)
    report.pop("current_target_relative", None)


def append_indexes(root, report):
    commands = (
        [sys.executable, str(root / "setup/import_windows_run_records.py")],
        [sys.executable, str(root / "setup/append_manual_records.py"),
         "--event-id", "CUP-REFERENCE-MASK-DEPTH-20261013",
         "--experiment", str(root / "reports/CUP_REFERENCE_SESSION_EXPERIMENT_20261013.md"),
         "--issues", str(root / "reports/CUP_REFERENCE_SESSION_ISSUES_20261013.md")],
        [sys.executable, str(root / "setup/append_manual_records.py"),
         "--event-id", "CUP-RECONNECT-TEST-QA-20261013",
         "--experiment", str(root / "reports/CUP_RECONNECT_TEST_EXPERIMENT_20261013.md"),
         "--issues", str(root / "reports/CUP_RECONNECT_TEST_ISSUES_20261013.md")],
    )
    report["append_commands"] = []
    for command in commands:
        completed = subprocess.run(command, cwd=str(root), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        output = completed.stdout.decode("utf-8", errors="replace")
        report["append_commands"].append({"argv": command, "exit_code": completed.returncode,
                                          "output": output})
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
        if completed.returncode != 0:
            raise RuntimeError("Journal append helper failed: {}".format(Path(command[1]).name))


def verify_imported_outputs(root, payload, report):
    for entry in report["files"]:
        target_relative = entry.get("target_relative")
        target = (safe_path(root, root / target_relative) if target_relative is not None
                  else safe_path(payload, payload / entry["archive_path"]))
        actual = sha256_file(target)
        if actual != entry.get("output_sha256"):
            raise RuntimeError("Imported output changed before completion: {}".format(entry["archive_path"]))
    report["imported_output_sha256_verified"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--incoming", required=True, type=Path)
    parser.add_argument("--archive", type=Path, help="Defaults to incoming/cup_offline_snapshot.zip")
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    report_path = None
    report = {"schema_version": 1, "batch_id": args.batch_id, "start_utc": utc_now(),
              "passed": False, "status": "validating", "conflicts": [], "files": [],
              "network_or_ssh_used": False, "server_journals_replaced": False,
              "root_note_snapshots_location": "incoming/verified_payload/windows_notes",
              "rollback_on_failure": False, "partial_evidence_preserved": True}
    try:
        if not args.root.is_absolute():
            raise ValueError("--root must be an absolute Ubuntu project path")
        root = args.root.resolve(strict=True)
        if os.name != "posix" or root != PROJECT_ROOT.resolve(strict=True) or not root.is_dir():
            raise ValueError("Import requires the Ubuntu project /data/ZJC/foundationPos")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", args.batch_id):
            raise ValueError("batch-id must be a safe single directory name")
        incoming = safe_path(root, args.incoming if args.incoming.is_absolute() else Path.cwd() / args.incoming)
        incoming_base = root / "foundationpose_data/incoming"
        relative_incoming = relative_to(incoming, incoming_base)
        if relative_incoming is None or not relative_incoming.parts or not incoming.is_dir():
            raise ValueError("--incoming must be an existing child stage inside foundationpose_data/incoming")
        candidate_report = safe_path(root, incoming / "import_report.json")
        if os.path.lexists(str(candidate_report)):
            raise ValueError("import_report.json already exists; use a new incoming stage")
        report_path = candidate_report
        archive_path = args.archive or (incoming / "cup_offline_snapshot.zip")
        if not archive_path.is_absolute():
            archive_path = Path.cwd() / archive_path
        archive_path = safe_path(incoming, archive_path)
        if not archive_path.is_file() or archive_path.suffix.casefold() != ".zip":
            raise ValueError("Archive must be a regular ZIP file inside the incoming stage")
        report.update(project_root=str(root), incoming=str(incoming), archive=str(archive_path))
        expected, manifest_raw, fingerprint = verify_archive(archive_path, incoming, report)
        report["status"] = "extracting_verified_payload"
        payload = extract_verified(archive_path, incoming, expected, manifest_raw, fingerprint, report)
        report["status"] = "preflight"
        plans = preflight(root, payload, expected, report)
        report["status"] = "importing"
        apply_plans(root, plans, args.batch_id, report)
        report["status"] = "appending_indexes"
        append_indexes(root, report)
        report["status"] = "verifying_imported_outputs"
        verify_imported_outputs(root, payload, report)
        report.update(status="passed", passed=True, end_utc=utc_now(),
                      journal_append_helpers_passed=True,
                      inference_or_reconstruction_executed=False)
        with report_path.open("xb") as output:
            output.write(json_bytes(report))
        print(json.dumps({"passed": True, "batch_id": args.batch_id,
                          "report": str(report_path), "applied_files": len(plans),
                          "verified_archive_files": len(expected)}, ensure_ascii=False), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        report.update(status="interrupted" if interrupted else "failed", passed=False,
                      end_utc=utc_now(), error_type=type(error).__name__, error=str(error))
        if report_path is not None:
            try:
                with report_path.open("xb") as output:
                    output.write(json_bytes(report))
            except OSError as report_error:
                print("Could not save import report: {}".format(report_error), file=sys.stderr)
        print(json.dumps({"passed": False, "status": report["status"],
                          "error_type": report["error_type"], "error": report["error"],
                          "report": str(report_path) if report_path is not None else None,
                          "conflicts": len(report["conflicts"])}, ensure_ascii=False),
              file=sys.stderr, flush=True)
        return 130 if interrupted else 1


if __name__ == "__main__":
    sys.exit(main())
