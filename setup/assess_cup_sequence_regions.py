#!/usr/bin/env python3
"""Read raw saved RGB-D sequence at explicitly reviewed manual regions."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scene = args.scene.resolve()
    metadata = json.loads((scene / "metadata.json").read_text(encoding="utf-8"))
    selection = json.loads(args.regions.read_text(encoding="utf-8"))
    scale = float((scene / "depth_scale.txt").read_text())
    frames = {Path(row["rgb"]).stem: row for row in metadata["frames"]}
    report = {
        "scope": "Manual sampled view and region assessment, not full object masks or reconstruction validation",
        "scene": str(scene), "metadata_passed": metadata["passed"],
        "saved_pairs": metadata["saved_frames"], "selection_method": selection["selection_method"],
        "selection_sha256": hashlib.sha256(args.regions.read_bytes()).hexdigest(),
        "saved_depth_scale_meters": scale, "frames": {},
        "limitations": [
            "Manual rectangles are subsets of the visible cup, not full masks or whole-cup depth coverage.",
            "Only selected frames/regions are measured; no exact camera angle or full 360-degree coverage is established.",
            "Nonzero depth does not by itself validate metric accuracy, motion registration, or mesh quality.",
        ],
    }
    for name, item in selection["frames"].items():
        rgb_path = scene / "rgb" / (name + ".png")
        depth_path = scene / "depth" / (name + ".png")
        rgb = np.array(Image.open(rgb_path).convert("RGB"))
        native = np.array(Image.open(depth_path))
        depth = native.astype(np.float64) * scale
        measured = {}
        for region, rectangle in item["regions"].items():
            x0, y0, x1, y1 = rectangle
            if not (0 <= x0 < x1 <= depth.shape[1] and 0 <= y0 < y1 <= depth.shape[0]):
                raise ValueError("Invalid rectangle: " + name + "/" + region)
            area = depth[y0:y1, x0:x1]
            valid = area[area > 0]
            luminance = rgb[y0:y1, x0:x1].astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])
            row = {"xyxy_exclusive": rectangle, "pixels": int(area.size),
                   "nonzero_depth_pixels": int(valid.size), "zero_depth_pixels": int(area.size-valid.size),
                   "nonzero_depth_ratio": float(valid.size/area.size),
                   "mean_rgb_luminance_0_255": float(luminance.mean())}
            if valid.size:
                row["nonzero_depth_meters_percentiles_5_50_95"] = [float(v) for v in np.percentile(valid, [5, 50, 95])]
            measured[region] = row
        report["frames"][name] = {
            "observations": item["observations"], "host_elapsed_seconds": frames[name]["host_elapsed_seconds"],
            "rgb_sha256": hashlib.sha256(rgb_path.read_bytes()).hexdigest(),
            "depth_sha256": hashlib.sha256(depth_path.read_bytes()).hexdigest(), "regions": measured,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "reviewed_frames": len(report["frames"]),
                      "regions": {frame: {name: round(row["nonzero_depth_ratio"], 4) for name, row in item["regions"].items()}
                                  for frame, item in report["frames"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
