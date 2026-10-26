#!/usr/bin/env python3
"""Create a new manual geometry version from retained visual-QA suggestions."""
import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def frames(value):
    source = value["frames"]
    if isinstance(source, dict):
        return source
    result = {}
    for item in source:
        key = item.get("frame", "{:06d}".format(item.get("index", -1)))
        if key in result:
            raise ValueError("Duplicate frame " + key)
        result[key] = item
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--qa", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite " + str(args.output))
    value = copy.deepcopy(read(args.source))
    target = frames(value)
    sources = [args.source] + args.qa
    changes = []
    for path in args.qa:
        for key, item in frames(read(path)).items():
            if key not in target:
                raise ValueError("QA frame absent from source: " + key)
            if "corrections" in item:
                item = item["corrections"]
                if item is None:
                    continue
            changed = []
            for name in ("body_left_x", "body_right_x_exclusive", "top_y",
                         "bottom_y_exclusive", "body_polygon_xy"):
                if name in item:
                    target[key][name] = item[name]
                    changed.append(name)
            for name, alternative in (("foreground_polygons", "manualforegroundpolygons"),
                                      ("background_polygons", "manualbackgroundpolygons")):
                proposed = item.get(name, item.get(alternative, []))
                if proposed:
                    target[key].setdefault(name, []).extend(proposed)
                    changed.append(name)
            if changed:
                changes.append({"frame": key, "qa_source": str(path), "fields": changed})
    value["frames"] = target
    value["geometry_version_record"] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "Apply manually reviewed image-space QA corrections; not pose or mask ground truth",
        "sources": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in sources],
        "changes": changes,
        "masks_accepted": False,
        "requires_new_overlay_qa": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "frames": len(target), "changes": len(changes),
                      "output": str(args.output), "masks_accepted": False}))


if __name__ == "__main__":
    main()
