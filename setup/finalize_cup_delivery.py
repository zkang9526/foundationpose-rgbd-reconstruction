#!/usr/bin/env python3
"""Preserve a completed packaging run beside its immutable ZIP and verify copy."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    package, run = args.package.resolve(), args.run.resolve()
    if (root / "foundationpose_data/exports") not in package.parents:
        parser.error("Package must be within project exports")
    if (root / "foundationpose_data/runs") not in run.parents:
        parser.error("Run must be within project run archives")
    package_report = json.loads((package / "package_report.json").read_text(encoding="utf-8"))
    run_report = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if not package_report["passed"] or run_report["exit_code"] != 0 or run_report.get("end") is None:
        parser.error("Packaging result is not complete/passed")
    if sha(package / package_report["archive"]) != package_report["archive_sha256"]:
        parser.error("Package SHA changed")
    destination = package / "packaging_run"
    if destination.exists():
        parser.error("Refusing to overwrite external packaging evidence")
    shutil.copytree(run, destination)
    verified = []
    for path in sorted(run.rglob("*")):
        if path.is_file():
            if root not in path.resolve().parents:
                raise ValueError("Run source resolves outside project")
            relative = path.relative_to(run)
            digest = sha(path)
            if sha(destination / relative) != digest:
                raise ValueError("Copied record mismatch " + str(relative))
            verified.append({"path": relative.as_posix(), "sha256": digest})
    with (package / "delivery_record_report.json").open("x", encoding="utf-8") as stream:
        json.dump({"passed": True, "source_run_id": run_report["run_id"],
                   "copied_record_files": verified, "archive_sha256_reverified": True,
                   "archive_sha256": package_report["archive_sha256"],
                   "copied_run_status": run_report["status"],
                   "network_used": False}, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "verified_record_files": len(verified),
                      "archive_sha256_reverified": True, "output": str(destination)}))


if __name__ == "__main__":
    main()
