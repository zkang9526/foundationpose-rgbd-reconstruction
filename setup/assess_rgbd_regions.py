#!/usr/bin/env python3
"""Read-only assessment of explicit manually selected rectangular RGB-D regions."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = args.input.resolve()
    capture = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    selection = json.loads(args.regions.read_text(encoding="utf-8"))
    rgb = np.array(Image.open(folder / "rgb.png").convert("RGB"))
    depth = np.load(folder / "depth_meters.npy", allow_pickle=False)
    native = np.array(Image.open(folder / "depth.png"))
    scale = float((folder / "depth_scale.txt").read_text())
    if rgb.shape[:2] != depth.shape or native.shape != depth.shape:
        raise ValueError("RGB/depth image sizes differ")
    if not np.allclose(depth, native.astype(np.float32) * np.float32(scale), rtol=1e-6, atol=1e-7):
        raise ValueError("Saved depth meters do not match raw PNG and scale")
    statistics = {}
    for name, rectangle in selection["rectangles_xyxy_exclusive"].items():
        x0, y0, x1, y1 = rectangle
        if not (0 <= x0 < x1 <= depth.shape[1] and 0 <= y0 < y1 <= depth.shape[0]):
            raise ValueError("Region is outside the saved image: " + name)
        area = depth[y0:y1, x0:x1]
        valid = area[np.isfinite(area) & (area > 0)]
        luminance = rgb[y0:y1, x0:x1].astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])
        row = {
            "rectangle_xyxy_exclusive": rectangle,
            "pixels": int(area.size),
            "nonzero_finite_depth_pixels": int(valid.size),
            "zero_depth_pixels": int(np.count_nonzero(area == 0)),
            "nonzero_finite_depth_ratio": float(valid.size / area.size),
            "mean_rgb_luminance_0_255": float(luminance.mean()),
            "median_rgb_luminance_0_255": float(np.median(luminance)),
        }
        if valid.size:
            row["nonzero_depth_meters_percentiles_5_50_95"] = [float(v) for v in np.percentile(valid, [5, 50, 95])]
        statistics[name] = row
    frames = capture["frames"]
    gaps = [abs(f["color_timestamp_ms"] - f["depth_timestamp_ms"]) for f in frames]
    report = {
        "scope": "Final saved snapshot and manual rectangles; not object segmentation, reconstruction or pose inference",
        "input": str(folder), "manual_selection": selection,
        "source_sha256": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                          for name in ("rgb.png", "depth.png", "depth_meters.npy", "report.json")},
        "capture_passed": capture["passed"],
        "warmup_pairs": capture["warmup_frames"],
        "acquired_aligned_pairs": capture["acquired_frames"],
        "unique_color_frames": capture["unique_color_frames"],
        "unique_depth_frames": capture["unique_depth_frames"],
        "aligned_pair_arrival_fps": capture["actual_fps"],
        "timestamp_gap_ms": {"first": gaps[0], "last": gaps[-1], "median": float(np.median(gaps)), "max": max(gaps)},
        "warnings_from_capture": capture["warnings"],
        "whole_image_last_frame_nonzero_depth_ratio": capture["last_frame_depth"]["valid_pixel_ratio"],
        "regions": statistics,
        "limitations": [
            "Rectangles are selected by manual viewing, not full object masks; coverage does not represent the entire cup/handle.",
            "Positive depth alone is not proof of metric accuracy.",
            "Only final RGB-D pixel data were saved; target per-pixel stability over all frames is not measured.",
            "RGB brightness cannot alone diagnose the cause of zero depth.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
