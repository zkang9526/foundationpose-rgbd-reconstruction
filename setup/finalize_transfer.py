#!/usr/bin/env python3
"""Verify the copied Windows workspace against a SHA256 manifest."""
import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / "transfer_manifest.json"
    if args.write_manifest:
        entries = []
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if not path.is_file() or path == manifest_path:
                continue
            if any(part in (".git", "__pycache__", ".windows-camera-venv", ".camera-venv", ".venv") for part in relative.parts):
                continue
            if path.name == ".records.lock":
                continue
            entries.append({"path": relative.as_posix(), "bytes": path.stat().st_size,
                            "sha256": sha256(path)})
        manifest_path.write_text(json.dumps({"files": entries}, indent=2) + "\n", encoding="utf-8")
        print("Wrote {} files, {} bytes".format(len(entries), sum(e["bytes"] for e in entries)))
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.is_file():
            failures.append("Missing: " + entry["path"])
        elif path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            failures.append("Different: " + entry["path"])
    for message in failures:
        print(message)
    print("Verified {} files; {} mismatches".format(len(manifest["files"]), len(failures)))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
