#!/usr/bin/env python3
"""Measure manually selected cup interior rectangles in a saved RGB-D check.

This is a snapshot assessment, not segmentation or object/pose detection.
The rectangles below were selected by inspecting cup_check_20261013_152557.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = args.input.resolve()
    capture = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    rgb = np.array(Image.open(folder / "rgb.png").convert("RGB"))
    depth = np.load(folder / "depth_meters.npy", allow_pickle=False)
    if rgb.shape[:2] != (480, 640) or depth.shape != (480, 640):
        raise ValueError("Rectangles apply only to the inspected 640x480 snapshot")
    rectangles = {
        "cup_body_interior": (315, 230, 397, 390),
        "green_upper_body_interior": (315, 230, 397, 292),
        "dark_lower_body_interior": (315, 314, 397, 390),
    }
    statistics = {}
    for name, (x0, y0, x1, y1) in rectangles.items():
        area = depth[y0:y1, x0:x1]
        valid = area[np.isfinite(area) & (area > 0)]
        luminance = rgb[y0:y1, x0:x1].astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])
        row = {
            "rectangle_xyxy_exclusive": [x0, y0, x1, y1],
            "pixels": int(area.size),
            "nonzero_finite_depth_pixels": int(valid.size),
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
        "scope": "Manual visual identification and rectangular interior statistics; no mask, mesh, reconstruction or pose inference",
        "input": str(folder),
        "source_sha256": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                          for name in ("rgb.png", "depth.png", "depth_meters.npy", "report.json")},
        "device_check_passed": capture["passed"],
        "acquired_aligned_pairs": capture["acquired_frames"],
        "unique_color_frames": capture["unique_color_frames"],
        "unique_depth_frames": capture["unique_depth_frames"],
        "aligned_pair_arrival_fps": capture["actual_fps"],
        "timestamp_gap_ms": {"first": gaps[0], "last": gaps[-1], "median": float(np.median(gaps)), "max": max(gaps)},
        "warnings_from_capture": capture["warnings"],
        "whole_image_last_frame_nonzero_depth_ratio": capture["last_frame_depth"]["valid_pixel_ratio"],
        "visual_observations": [
            "Cup near center; green upper body, dark lower body, handle on left.",
            "Bright window behind cup; cup body appears dark in RGB.",
            "Cup body appears very dark blue in the whole-scene depth preview; raw data show most manually selected cup interior pixels have positive depth.",
        ],
        "rectangles": statistics,
        "limitations": [
            "Rectangles manually selected from this specific RGB snapshot; they are not object masks.",
            "Positive depth values alone do not establish accuracy or cup distance.",
            "Dark blue in this preview is valid near-range depth, while exact black is zero depth; appearance alone was initially misread and corrected using raw depth.",
            "Backlight is visually evident; reflectivity/material effects and full cup/handle depth coverage have not been isolated by this test.",
            "Only the final RGB-D pair was saved; earlier frame per-pixel data are unavailable.",
        ],
        "ready_for_formal_multiview_capture": False,
        "readiness_reason": "RGB body texture and lower outline are very dark; improve lighting and inspect again. Interior depth is mostly present, not a major missing-depth failure.",
        "next_step": "Improve front/side illumination, avoid the bright window background, slightly tilt down to show cup top and recheck stationary RGB-D before multiview capture.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
