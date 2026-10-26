#!/usr/bin/env python3
"""Create and verify a Windows cup-data snapshot without contacting Ubuntu.

Python 3.8+, standard library only. Run through setup/run_logged.py. This is a
portable evidence snapshot, not evidence that reconstruction or inference ran.
Existing output directories, outside-project links, and changing inputs fail
closed; partial output is retained for investigation.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile


CHUNK_BYTES = 1024 * 1024
EXCLUDED_DIR_NAMES = {
    ".git", ".ssh", ".aws", ".azure", ".kube", ".gnupg",
    ".venv", "venv", "env", ".env", ".windows-camera-venv",
    "__pycache__", "node_modules", ".conda", "site-packages",
    "weights", "checkpoints", "foundationpose", "foundationpose-conda",
}
EXCLUDED_FILE_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_dsa",
    "id_ecdsa", "id_ed25519", "credentials", "credentials.json",
    "known_hosts", "authorized_keys", "environment.txt", "environ.txt",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo", ".pem", ".key", ".pfx", ".p12",
    ".pt", ".pth", ".ckpt", ".onnx", ".safetensors",
}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def relative_to(path, parent):
    try:
        return path.relative_to(parent)
    except ValueError:
        return None


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json_new(path, value):
    """All outputs live in a new directory; do not replace existing evidence."""
    with path.open("xb") as handle:
        handle.write(json_bytes(value))


def fingerprint(path):
    details = path.stat()
    return (details.st_dev, details.st_ino, details.st_size,
            details.st_mtime_ns, details.st_ctime_ns)


def fingerprint_stat(details):
    return (details.st_dev, details.st_ino, details.st_size,
            details.st_mtime_ns, details.st_ctime_ns)


def disallowed(relative_path):
    parts = [part.casefold() for part in relative_path.parts]
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return "excluded_directory"
    if parts and parts[-1] in EXCLUDED_DIR_NAMES:
        return "excluded_directory"
    name = parts[-1] if parts else ""
    if name in EXCLUDED_FILE_NAMES or name.startswith(".env."):
        return "excluded_private_or_environment_file"
    if relative_path.suffix.casefold() in EXCLUDED_SUFFIXES:
        return "excluded_private_compiled_or_model_file"
    return None


def validate_source(path, root):
    """Check both the lexical path and its resolved target on every access."""
    lexical = Path(os.path.abspath(str(path)))
    lexical_relative = relative_to(lexical, root)
    if lexical_relative is None:
        raise ValueError("Source is outside project: {}".format(path))
    # Check a dangling outside-project link before strict resolution raises.
    preliminary_target = lexical.resolve(strict=False)
    if relative_to(preliminary_target, root) is None:
        raise ValueError("Source link resolves outside project: {}".format(lexical_relative))
    resolved = lexical.resolve(strict=True)
    resolved_relative = relative_to(resolved, root)
    if resolved_relative is None:
        raise ValueError("Source link resolves outside project: {}".format(lexical_relative))
    reason = disallowed(lexical_relative) or disallowed(resolved_relative)
    return lexical, resolved, lexical_relative, reason


def sha256_source(path, root, expected_fingerprint=None, expected_target=None):
    lexical, resolved, relative, reason = validate_source(path, root)
    if reason:
        raise ValueError("Excluded source was selected: {} ({})".format(relative, reason))
    before = fingerprint(lexical)
    if expected_fingerprint is not None and before != expected_fingerprint:
        raise RuntimeError("Source changed during snapshot: {}".format(relative))
    if expected_target is not None and resolved != expected_target:
        raise RuntimeError("Source link changed during snapshot: {}".format(relative))
    digest = hashlib.sha256()
    size = 0
    with lexical.open("rb") as handle:
        if fingerprint_stat(os.fstat(handle.fileno())) != before:
            raise RuntimeError("Source changed before read: {}".format(relative))
        while True:
            block = handle.read(CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
            size += len(block)
        if fingerprint_stat(os.fstat(handle.fileno())) != before:
            raise RuntimeError("Source changed while reading: {}".format(relative))
    after_target = lexical.resolve(strict=True)
    if after_target != resolved or fingerprint(lexical) != before:
        raise RuntimeError("Source changed after read: {}".format(relative))
    return digest.hexdigest(), size


def collect_sources(root, readiness):
    entries = {}
    skipped = []
    skipped_running_runs = []
    skipped_incomplete_runs = []
    completed_runs = []

    def add_file(path, archive_path=None):
        lexical, resolved, relative, reason = validate_source(path, root)
        if reason:
            skipped.append({"source_path": relative.as_posix(), "reason": reason})
            return
        if not lexical.is_file():
            raise ValueError("Selected source is not a regular file: {}".format(relative))
        archive_path = archive_path or relative.as_posix()
        if archive_path.casefold() == "manifest.json":
            raise ValueError("Archive root manifest.json is reserved for the package manifest")
        archive_parts = Path(archive_path).parts
        if (archive_path.startswith(("/", "\\")) or ".." in archive_parts
                or "\x00" in archive_path or "\\" in archive_path):
            raise ValueError("Unsafe archive path: {}".format(archive_path))
        key = archive_path.casefold()
        if key in entries:
            if entries[key]["source"] == lexical:
                return
            raise ValueError("Duplicate portable archive path: {}".format(archive_path))
        entries[key] = {
            "source": lexical, "resolved": resolved, "path": archive_path,
            "source_path": relative.as_posix(), "fingerprint": fingerprint(lexical),
            "mode": stat.S_IMODE(lexical.stat().st_mode),
        }

    def walk(directory, ancestors=None):
        ancestors = ancestors or set()
        lexical, resolved, relative, reason = validate_source(directory, root)
        if reason:
            skipped.append({"source_path": relative.as_posix(), "reason": reason})
            return
        if not lexical.is_dir():
            raise ValueError("Selected directory is not a directory: {}".format(relative))
        if resolved in ancestors:
            raise ValueError("Directory link cycle: {}".format(relative))
        next_ancestors = ancestors | {resolved}
        for child in sorted(lexical.iterdir(), key=lambda item: item.name.casefold()):
            child_lexical, _, child_relative, child_reason = validate_source(child, root)
            if child_reason:
                skipped.append({"source_path": child_relative.as_posix(), "reason": child_reason})
            elif child_lexical.is_dir():
                walk(child_lexical, next_ancestors)
            else:
                add_file(child_lexical)

    for name in ("foundationpose_data/windows_captures", "foundationpose_data/derived",
                 "reports", "setup"):
        directory = root / name
        if directory.exists():
            walk(directory)
        else:
            skipped.append({"source_path": name, "reason": "source_directory_missing"})

    runs = root / "foundationpose_data/runs"
    if runs.exists():
        validate_source(runs, root)
        for directory in sorted(runs.iterdir(), key=lambda item: item.name.casefold()):
            lexical, _, relative, reason = validate_source(directory, root)
            if reason:
                skipped.append({"source_path": relative.as_posix(), "reason": reason})
                continue
            if not lexical.is_dir():
                skipped.append({"source_path": relative.as_posix(),
                                "reason": "not_a_per_run_directory"})
                continue
            metadata_path = lexical / "run.json"
            try:
                _, metadata_target, _, metadata_excluded = validate_source(metadata_path, root)
                if metadata_excluded:
                    raise ValueError("run.json points to an excluded source")
                metadata_fingerprint = fingerprint(metadata_path)
                metadata_raw = metadata_path.read_bytes()
                if (fingerprint(metadata_path) != metadata_fingerprint
                        or metadata_path.resolve(strict=True) != metadata_target):
                    raise RuntimeError("run.json changed during classification: {}".format(relative))
                metadata = json.loads(metadata_raw.decode("utf-8-sig"))
                if not isinstance(metadata, dict):
                    raise ValueError("run.json is not an object")
            except (OSError, ValueError) as error:
                # Outside-project links must not be silently skipped.
                if metadata_path.exists():
                    validate_source(metadata_path, root)
                skipped_incomplete_runs.append({"run_directory": relative.as_posix(),
                                                "reason": "missing_or_invalid_run_json",
                                                "error_type": type(error).__name__})
                continue
            if metadata.get("status") == "running":
                skipped_running_runs.append({"run_id": metadata.get("run_id", directory.name),
                                             "run_directory": relative.as_posix(),
                                             "reason": "status_running", "end": metadata.get("end")})
            elif metadata.get("end") is None:
                skipped_incomplete_runs.append({"run_id": metadata.get("run_id", directory.name),
                                                "run_directory": relative.as_posix(),
                                                "reason": "end_is_null_or_missing",
                                                "status": metadata.get("status")})
            else:
                walk(lexical)
                if fingerprint(metadata_path) != metadata_fingerprint:
                    raise RuntimeError("run.json changed after classification: {}".format(relative))
                completed_runs.append({"run_id": metadata.get("run_id", directory.name),
                                       "run_directory": relative.as_posix(),
                                       "status": metadata.get("status"), "end": metadata["end"],
                                       "run_json_sha256": hashlib.sha256(metadata_raw).hexdigest()})
    else:
        skipped.append({"source_path": "foundationpose_data/runs",
                        "reason": "source_directory_missing"})

    for document in sorted(root.glob("*.md"), key=lambda item: item.name.casefold()):
        add_file(document, "windows_notes/" + document.name)
    add_file(readiness)
    selected = sorted(entries.values(), key=lambda entry: entry["path"])
    return selected, skipped, skipped_running_runs, skipped_incomplete_runs, completed_runs


def zip_entry_info(entry):
    modified = datetime.datetime.fromtimestamp(entry["fingerprint"][3] / 1000000000.0)
    modified_year = min(2107, max(1980, modified.year))
    info = zipfile.ZipInfo(entry["path"],
                           (modified_year, modified.month, modified.day,
                            modified.hour, modified.minute, modified.second))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | entry["mode"]) << 16
    return info


def copy_entry(archive, entry, root):
    lexical, resolved, relative, reason = validate_source(entry["source"], root)
    if reason or resolved != entry["resolved"] or fingerprint(lexical) != entry["fingerprint"]:
        raise RuntimeError("Source changed or became excluded: {}".format(relative))
    digest = hashlib.sha256()
    size = 0
    with lexical.open("rb") as source:
        if fingerprint_stat(os.fstat(source.fileno())) != entry["fingerprint"]:
            raise RuntimeError("Source changed before copying: {}".format(relative))
        with archive.open(zip_entry_info(entry), "w", force_zip64=True) as target:
            while True:
                block = source.read(CHUNK_BYTES)
                if not block:
                    break
                target.write(block)
                digest.update(block)
                size += len(block)
        if fingerprint_stat(os.fstat(source.fileno())) != entry["fingerprint"]:
            raise RuntimeError("Source changed while copying: {}".format(relative))
    if lexical.resolve(strict=True) != resolved or fingerprint(lexical) != entry["fingerprint"]:
        raise RuntimeError("Source changed after copying: {}".format(relative))
    if size != entry["fingerprint"][2]:
        raise RuntimeError("Source size changed: {}".format(relative))
    return {"path": entry["path"], "source_path": entry["source_path"],
            "bytes": size, "sha256": digest.hexdigest(), "source_mode": entry["mode"]}


def verify_zip(path, manifest):
    expected = {item["path"]: item for item in manifest["files"]}
    expected_names = set(expected) | {"manifest.json"}
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise RuntimeError("Archive member list differs from manifest")
        if archive.read("manifest.json") != json_bytes(manifest):
            raise RuntimeError("Embedded manifest differs from snapshot manifest")
        for name in sorted(expected):
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
                raise RuntimeError("Archive entry checksum mismatch: {}".format(name))
    return len(expected)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            block = source.read(CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Project root")
    parser.add_argument("--readiness", required=True, type=Path,
                        help="Existing readiness JSON within the project; preserved verbatim")
    parser.add_argument("--output", required=True, type=Path,
                        help="New directory beneath project/foundationpose_data/exports")
    args = parser.parse_args()
    output = None
    report = {"schema_version": 1, "started_utc": utc_now(), "passed": False,
              "status": "validating_inputs", "network_or_ssh_used": False,
              "automatic_upload": False, "purpose": "portable_windows_evidence_snapshot",
              "reconstruction_or_inference_proved_by_package": False}
    try:
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Project root is not a directory")
        readiness = (args.readiness if args.readiness.is_absolute()
                     else Path.cwd() / args.readiness)
        readiness, readiness_target, readiness_relative, readiness_excluded = validate_source(readiness, root)
        if readiness_excluded or readiness.suffix.casefold() != ".json" or not readiness.is_file():
            raise ValueError("Readiness must be an allowed JSON file within the project")
        readiness_fingerprint = fingerprint(readiness)
        readiness_raw = readiness.read_bytes()
        if fingerprint(readiness) != readiness_fingerprint or readiness.resolve(strict=True) != readiness_target:
            raise RuntimeError("Readiness changed while loading")
        readiness_document = json.loads(readiness_raw.decode("utf-8-sig"))
        if not isinstance(readiness_document, dict):
            raise ValueError("Readiness JSON must be an object")
        readiness_sha256 = hashlib.sha256(readiness_raw).hexdigest()
        proposed_output = (args.output if args.output.is_absolute() else Path.cwd() / args.output)
        # lexists catches an existing dangling link as well as existing directories.
        if os.path.lexists(str(proposed_output)):
            raise ValueError("Output already exists; use a new directory")
        proposed_output = proposed_output.resolve(strict=False)
        exports_relative = relative_to(proposed_output, root / "foundationpose_data/exports")
        if exports_relative is None or not exports_relative.parts:
            raise ValueError("Output must be a new child directory of project/foundationpose_data/exports")
        if relative_to(proposed_output, root) is None:
            raise ValueError("Output resolves outside project")
        sources, skipped, running, incomplete, completed = collect_sources(root, readiness)
        if not sources:
            raise ValueError("No source files selected")
        report.update(project_root=str(root), output_directory=str(proposed_output),
                      readiness_source_path=readiness_relative.as_posix(),
                      readiness_sha256=readiness_sha256, readiness=readiness_document,
                      skipped_running_runs=running, skipped_incomplete_runs=incomplete,
                      skipped_sources=skipped, completed_runs=completed,
                      selected_source_files=len(sources),
                      limitations=[
                          "Readiness scope is preserved as supplied; packaging does not advance it.",
                          "Independent tests, reconstruction, poses and inference require their own evidence.",
                          "Root Markdown is stored under windows_notes; do not overwrite Ubuntu journals.",
                          "Run currently creating this package is omitted while status is running; import its completed record later.",
                          "Only the explicit source trees are included; virtual environments, model weights and repositories are excluded.",
                      ])
        proposed_output.mkdir(parents=True, exist_ok=False)
        output = proposed_output
        archive_path = output / "cup_offline_snapshot.zip"
        manifest = {"schema_version": 1, "created_utc": utc_now(),
                    "purpose": "portable_windows_evidence_snapshot",
                    "archive_paths": "project-relative, except root Markdown under windows_notes/",
                    "manifest_self_hash": "excluded; embedded bytes are verified and whole ZIP SHA256 is reported",
                    "readiness_source_path": readiness_relative.as_posix(),
                    "readiness_sha256": readiness_sha256,
                    "readiness": readiness_document,
                    "completed_runs": completed, "skipped_running_runs": running,
                    "skipped_incomplete_runs": incomplete, "skipped_sources": skipped,
                    "files": []}
        report["status"] = "copying"
        completed_metadata_hashes = {
            item["run_directory"] + "/run.json": item["run_json_sha256"]
            for item in completed
        }
        with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            for index, entry in enumerate(sources, 1):
                report["current_source_path"] = entry["source_path"]
                copied = copy_entry(archive, entry, root)
                expected_metadata_hash = completed_metadata_hashes.get(entry["source_path"])
                if expected_metadata_hash is not None and copied["sha256"] != expected_metadata_hash:
                    raise RuntimeError("Completed run metadata changed: {}".format(entry["source_path"]))
                manifest["files"].append(copied)
                report["copied_source_files"] = index
                if index % 100 == 0 or index == len(sources):
                    print(json.dumps({"stage": "copied", "files": index,
                                      "total": len(sources)}), flush=True)
            archive.writestr("manifest.json", json_bytes(manifest))
        # A final source reread detects inputs changed after their earlier copy.
        report["status"] = "verifying_source_snapshot"
        for entry, copied in zip(sources, manifest["files"]):
            report["current_source_path"] = entry["source_path"]
            digest, size = sha256_source(entry["source"], root, entry["fingerprint"], entry["resolved"])
            if digest != copied["sha256"] or size != copied["bytes"]:
                raise RuntimeError("Source content changed during snapshot: {}".format(entry["source_path"]))
        readiness_entry = next(item for item in manifest["files"]
                               if item["source_path"] == readiness_relative.as_posix())
        if readiness_entry["sha256"] != readiness_sha256:
            raise RuntimeError("Packaged readiness differs from loaded readiness")
        report["status"] = "verifying_zip"
        verified_count = verify_zip(archive_path, manifest)
        archive_sha256 = file_sha256(archive_path)
        write_json_new(output / "manifest.json", manifest)
        with (output / "SHA256SUMS.txt").open("x", encoding="ascii", newline="\n") as handle:
            handle.write(archive_sha256 + "  " + archive_path.name + "\n")
        report.update(status="passed", passed=True, finished_utc=utc_now(),
                      archive=archive_path.name, archive_bytes=archive_path.stat().st_size,
                      archive_sha256=archive_sha256, verified_zip_entries=verified_count,
                      source_content_verified_unchanged=True,
                      total_source_bytes=sum(item["bytes"] for item in manifest["files"]),
                      manifest_sha256=file_sha256(output / "manifest.json"))
        report.pop("current_source_path", None)
        write_json_new(output / "package_report.json", report)
        print(json.dumps({"passed": True, "output": str(output),
                          "archive_sha256": archive_sha256,
                          "verified_files": verified_count,
                          "skipped_running_runs": len(running),
                          "automatic_upload": False}, ensure_ascii=False), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        report.update(status="interrupted" if interrupted else "failed", passed=False,
                      finished_utc=utc_now(), error_type=type(error).__name__, error=str(error),
                      partial_output_preserved=output is not None)
        if output is not None:
            try:
                write_json_new(output / "package_report.json", report)
            except OSError as report_error:
                print("Could not save failure report: {}".format(report_error), file=sys.stderr)
        print(json.dumps({"passed": False, "status": report["status"],
                          "error_type": report["error_type"], "error": report["error"],
                          "partial_output": str(output) if output is not None else None},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return 130 if interrupted else 1


if __name__ == "__main__":
    sys.exit(main())
