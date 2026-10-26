#!/usr/bin/env python3
"""Read-only depth range audit for the accepted cup pilot masks.

Raw RGB/depth, masks and their generation reports are never modified. This is
an image/range consistency audit, not sensor accuracy or ground-truth analysis.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def percentile(values):
    if not values.size:
        return None
    p = np.percentile(values, [5, 50, 95])
    return {"p05": float(p[0]), "p50": float(p[1]), "p95": float(p[2])}


def distribution(values, center=None, half_span=100):
    v = np.asarray(values)
    n = int(v.size)
    bins = {
        "zero": int(np.count_nonzero(v == 0)),
        "positive_under_100_mm": int(np.count_nonzero((v > 0) & (v < 100))),
        "100_to_under_300_mm": int(np.count_nonzero((v >= 100) & (v < 300))),
        "300_to_under_800_mm": int(np.count_nonzero((v >= 300) & (v < 800))),
        "800_to_1500_mm_inclusive": int(np.count_nonzero((v >= 800) & (v <= 1500))),
        "over_1500_mm": int(np.count_nonzero(v > 1500)),
    }
    positive = int(np.count_nonzero(v))
    result = {"pixels": n, "nonzero_pixels": positive,
              "nonzero_percent": 100.0 * positive / n if n else None,
              "bins": {k: {"pixels": count,
                           "percent_of_region": 100.0 * count / n if n else None,
                           "percent_of_nonzero": 100.0 * count / positive if positive else None}
                       for k, count in bins.items()},
              "nonzero_depth_mm_percentiles": percentile(v[v > 0]),
              "near_300_800_mm_percentiles": percentile(v[(v >= 300) & (v < 800)])}
    if center is not None:
        lo, hi = center - half_span, center + half_span
        near = (v > 0) & (v >= lo) & (v <= hi)
        count = int(np.count_nonzero(near))
        result["exploratory_object_window"] = {
            "lower_mm_inclusive": float(lo), "upper_mm_inclusive": float(hi),
            "pixels": count, "percent_of_region": 100.0 * count / n if n else None,
            "percent_of_nonzero": 100.0 * count / positive if positive else None,
            "outside_window_nonzero_pixels": int(np.count_nonzero((v > 0) & ~near)),
        }
    return result


def rectangle(bounds, shape):
    x0, y0, x1, y1 = bounds
    result = np.zeros(shape, bool)
    result[y0:y1, x0:x1] = True
    return result


def body_masks(generation_frame, shape):
    geometry = generation_frame["manual_body_geometry"]
    bounds = rectangle(geometry["body_bounds_xyxy"], shape)
    points = geometry.get("body_polygon_xy")
    if points is None:
        body = bounds
    else:
        body = np.zeros(shape, np.uint8)
        cv2.fillPoly(body, [np.asarray(points, np.int32)], 1)
        body = body.astype(bool)
    core = rectangle(geometry["body_core_bounds_xyxy"], shape) & body
    return body, core, bounds


def analyze(root, derived_name, half_span):
    derived = root / "foundationpose_data" / "derived" / derived_name
    generation_path = derived / "report.json"
    generation = json.loads(generation_path.read_text(encoding="utf-8"))
    scene = Path(generation["source_scene"])
    if generation["processed_frames"] != 36 or generation["status"] != "complete":
        raise ValueError("Expected a complete 36-frame candidate generation")
    geometry_info = generation["source_hashes"]["geometry"]
    if sha256(geometry_info["path"]) != geometry_info["sha256"]:
        raise ValueError("Geometry changed since mask generation")
    frames = []
    pooled = {k: [] for k in ("object_mask", "body_core_independent_of_mask",
                              "masked_body_polygon", "masked_external_handle_outside_body_bounds",
                              "masked_external_to_body_polygon")}
    centers, window_rates = [], {k: [] for k in pooled}
    for gf in generation["frames"]:
        filename = gf["frame"]
        frame = Path(filename).stem
        mask_path, depth_path = derived / "masks" / filename, scene / "depth" / filename
        mask_hash, depth_hash = sha256(mask_path), sha256(depth_path)
        if mask_hash != gf["mask_sha256"] or depth_hash != gf["source_depth_sha256"]:
            raise ValueError("Input changed for frame " + frame)
        mask_image = np.asarray(Image.open(mask_path))
        depth = np.asarray(Image.open(depth_path))
        if mask_image.ndim != 2 or depth.shape != mask_image.shape:
            raise ValueError("Unexpected input format")
        mask = mask_image > 0
        body, core, bounds = body_masks(gf, mask.shape)
        core_near = depth[core & (depth >= 300) & (depth < 800)]
        center = float(np.median(core_near)) if core_near.size else None
        if center is not None:
            centers.append(center)
        regions = {"object_mask": mask,
                   "body_core_independent_of_mask": core,
                   "masked_body_polygon": mask & body,
                   "masked_external_handle_outside_body_bounds": mask & ~bounds,
                   "masked_external_to_body_polygon": mask & ~body}
        stats = {}
        for name, pixels in regions.items():
            values = depth[pixels]
            stats[name] = distribution(values, center, half_span)
            pooled[name].append(values)
            if center is not None:
                window_rates[name].append(stats[name]["exploratory_object_window"]["percent_of_region"])
        core_rate = stats["body_core_independent_of_mask"].get("exploratory_object_window", {}).get("percent_of_region")
        flags = []
        if core_rate is None or core_rate < 50:
            flags.append("severe_body_core_near_depth_loss_exploratory_threshold_under_50_percent")
        elif core_rate < 70:
            flags.append("moderate_body_core_near_depth_loss_exploratory_threshold_under_70_percent")
        if stats["object_mask"]["bins"]["over_1500_mm"]["pixels"]:
            flags.append("far_depth_inside_RGB_target_mask")
        frames.append({"frame": frame, "mask_sha256": mask_hash, "raw_depth_sha256": depth_hash,
                       "input_hashes_match_generation_report": True,
                       "body_near_depth_median_mm": center,
                       "regions": stats, "flags": flags})
    pooled_stats = {k: distribution(np.concatenate(v)) for k, v in pooled.items()}
    summary = {"pooled_regions": pooled_stats,
               "mean_per_frame_exploratory_window_percent_of_region": {
                   k: float(np.mean([x for x in v if x is not None])) if any(x is not None for x in v) else None
                   for k, v in window_rates.items()},
               "body_median_min_max_mm": [min(centers), max(centers)] if centers else None,
               "severe_body_core_frames": [f["frame"] for f in frames if any(x.startswith("severe_") for x in f["flags"])],
               "moderate_body_core_frames": [f["frame"] for f in frames if any(x.startswith("moderate_") for x in f["flags"])],
               "far_depth_frames": [f["frame"] for f in frames if "far_depth_inside_RGB_target_mask" in f["flags"]]}
    fixed = ([float(np.floor((min(centers) - half_span) / 10) * 10),
              float(np.ceil((max(centers) + half_span) / 10) * 10)] if centers else None)
    return {"scene": scene.name, "mask_version": derived_name,
            "generation_report_path": str(generation_path), "generation_report_sha256": sha256(generation_path),
            "geometry_source": geometry_info, "frames": frames, "summary": summary,
            "exploratory_fixed_window_mm_inclusive": fixed,
            "pilot_assessment": "Near-depth support may allow a cautious reconstruction pilot after explicit range-filtered derived input; inspect body/handle distribution and resulting mesh. Raw nonzero coverage alone does not establish usable object depth or sensor accuracy."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path, default=Path("reports/cup_mask_depth_outlier_review.json"))
    parser.add_argument("--exploratory-axial-half-span-mm", type=float, default=100.0)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise ValueError("Refusing to overwrite existing review report")
    if not (0 < args.exploratory_axial_half_span_mm < 300):
        raise ValueError("Half-span must be positive and below 300 mm")
    scenes = [analyze(root, name, args.exploratory_axial_half_span_mm) for name in
              ("cup_masks_side_165803_v4", "cup_masks_top_185306_v5")]
    report = {"schema_version": 1, "status": "complete", "passed": True,
              "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "script_path": str(Path(__file__).resolve()), "script_sha256": sha256(__file__),
              "operation": "Read-only numeric audit; no raw depth, RGB, masks or environment modified",
              "mask_zero_pixels_excluded": True,
              "body_core_exception": "Independent manual body-core depth is analyzed even if mask excludes a pixel; this is explicitly separate from target-mask statistics.",
              "not_depth_accuracy_or_ground_truth": True, "not_pose_ground_truth": True,
              "range_units": "Stored raw positive depth integers are millimeters; zero is missing measurement.",
              "window_method": {"center": "Per-frame median of positive manually bounded body-core depths in broad observed cup range [300,800) mm; not median of all masked values.",
                                "axial_half_span_mm": args.exploratory_axial_half_span_mm,
                                "physical_span_is_measured": False,
                                "span_caution": "100 mm half-span is a conservative exploratory 200 mm axial envelope, not a measured object dimension. Measure cup physical size/diagonal and add calibration/edge tolerance before declaring a final reliable range filter.",
                                "filter_recommendation": "For derived reconstruction input only: keep depth where RGB object mask is positive and body-center +/- measured/conservatively bounded object axial half-span applies; set other derived depth pixels to zero. Preserve raw source separately, record filter bounds and zero counts. This audit does not apply that filter.",
                                "limits": "Range filtering rejects obvious multi-meter background-like depths but cannot fix alignment, recover missing depth, or exclude same-range support pixels. RGB silhouette remains separate from depth validity."},
              "scenes": scenes}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    brief = [{"scene": s["scene"], "summary": s["summary"]["mean_per_frame_exploratory_window_percent_of_region"],
              "core_median_mm": s["summary"]["body_median_min_max_mm"],
              "severe_core_frames": s["summary"]["severe_body_core_frames"],
              "moderate_core_frames": s["summary"]["moderate_body_core_frames"],
              "fixed_window_mm": s["exploratory_fixed_window_mm_inclusive"]} for s in scenes]
    print(json.dumps({"passed": True, "output": str(output), "frames": 72, "scenes": brief}, ensure_ascii=False))


if __name__ == "__main__":
    main()
