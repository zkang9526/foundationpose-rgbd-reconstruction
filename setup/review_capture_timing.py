#!/usr/bin/env python3
"""Review an existing RGB-D capture's timing and run records without opening a camera."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def describe(values):
    values = np.asarray(values, dtype=float)
    if not values.size:
        return None
    labels = ("min", "p50", "p90", "p95", "p99", "max")
    return dict(zip(labels, np.percentile(values, [0, 50, 90, 95, 99, 100]).tolist()))


def source_record(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def summarize_run(path):
    run = load_json(path)
    fields = ("run_id", "label", "status", "start", "end", "exit_code", "child_exitcode", "warnings", "note")
    return {"source": source_record(path), **{key: run.get(key) for key in fields}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-run", type=Path, required=True)
    parser.add_argument("--format-run", type=Path, required=True)
    parser.add_argument("--interrupted-run", type=Path)
    parser.add_argument("--interrupted-scene", type=Path)
    args = parser.parse_args()
    scene = args.scene.resolve()
    metadata_path = scene / "metadata.json"
    metadata = load_json(metadata_path)
    frames = metadata["frames"]
    if len(frames) < 2:
        raise ValueError("At least two saved frames are needed to assess timing")
    slots = np.asarray([frame["sample_slot"] for frame in frames], dtype=int)
    elapsed = np.asarray([frame["host_elapsed_seconds"] for frame in frames], dtype=float)
    differences = np.diff(elapsed)
    requested = metadata["requested"]
    expected_slots = int(np.ceil(requested["seconds"] * requested["save_fps"]))
    missing_slots = sorted(set(range(expected_slots)) - set(slots.tolist()))
    independent = {}
    for stream in ("color", "depth"):
        numbers = np.asarray([frame[stream + "_frame_number"] for frame in frames], dtype=int)
        timestamps = np.asarray([frame[stream + "_timestamp_ms"] for frame in frames], dtype=float)
        independent[stream] = {
            "unique_frame_numbers": int(np.unique(numbers).size),
            "duplicate_frame_numbers": int(numbers.size - np.unique(numbers).size),
            "strictly_increasing_frame_numbers": bool(np.all(np.diff(numbers) > 0)),
            "strictly_increasing_timestamps": bool(np.all(np.diff(timestamps) > 0)),
            "first_frame_number": int(numbers[0]),
            "last_frame_number": int(numbers[-1]),
            "estimated_sensor_frame_number_rate_hz": float((numbers[-1] - numbers[0]) / ((timestamps[-1] - timestamps[0]) / 1000)),
            "timestamp_domains": sorted(set(frame[stream + "_timestamp_domain"] for frame in frames)),
        }
    time_difference = [frame["depth_timestamp_ms"] - frame["color_timestamp_ms"] for frame in frames]
    valid_ratios = [frame["saved_valid_pixel_ratio"] for frame in frames]
    report = {
        "schema_version": 1,
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Read-only review of existing capture metadata and run records; no camera access, masks, reconstruction or inference",
        "scene": str(scene),
        "source_files": [source_record(scene / name) for name in ("metadata.json", "report.json", "timestamps.csv", "timestamps.json")],
        "saved_frames": len(frames),
        "requested_seconds": requested["seconds"],
        "saved_span_seconds": float(elapsed[-1] - elapsed[0]),
        "saved_mean_fps": float((len(frames) - 1) / (elapsed[-1] - elapsed[0])),
        "sampling": {
            "requested_save_fps": requested["save_fps"],
            "expected_slots": expected_slots,
            "missing_slot_count": len(missing_slots),
            "missing_slots": missing_slots,
            "missing_fraction": len(missing_slots) / expected_slots,
            "interframe_host_ms": describe(differences * 1000),
            "gaps_above_150_ms": [{"ending_frame_index": int(frames[index + 1]["index"]), "gap_ms": float(gap * 1000)} for index, gap in enumerate(differences) if gap > 0.15],
        },
        "independent_frames": independent,
        "depth_minus_color_timestamp_ms": describe(time_difference),
        "whole_image_depth_nonzero_ratio": {"statistics": describe(valid_ratios), "mean": float(np.mean(valid_ratios))},
        "conversion_rejected_pixels_total": sum(frame["conversion_rejected_pixels"] for frame in frames),
        "capture_report_status": {key: metadata.get(key) for key in ("passed", "warnings", "pipeline_started", "pipeline_stopped", "stop_error", "actual_acquisition_fps")},
        "capture_run": summarize_run(args.capture_run.resolve() / "run.json"),
        "format_run": summarize_run(args.format_run.resolve() / "run.json"),
        "limitations": [
            "Whole-image nonzero depth statistics include the background and are not the cup's ROI depth completeness.",
            "Unique frame numbers prove distinct sensor frames, not distinct viewpoints or complete object coverage.",
            "The reported actual_acquisition_fps measures script-loop processing; sensor frame-number rate is a separate estimate.",
            "RGB and depth have a measured timestamp offset; quick movement can still affect alignment.",
            "No image-quality, object-geometry, mask, reconstruction or pose-accuracy acceptance is implied by this timing review.",
            "The interrupted run records an interruption, without establishing why the interruption occurred.",
        ],
    }
    if args.interrupted_run:
        report["earlier_interrupted_run"] = summarize_run(args.interrupted_run.resolve() / "run.json")
    if args.interrupted_scene:
        earlier_path = args.interrupted_scene.resolve() / "metadata.json"
        earlier = load_json(earlier_path)
        report["earlier_interrupted_capture"] = {"source": source_record(earlier_path), **{key: earlier.get(key) for key in ("passed", "saved_frames", "pipeline_stopped", "stop_error", "warnings", "error")}}
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("Review output already exists; use a new output path to retain evidence: " + str(output))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"review_completed": True, "saved_frames": len(frames), "saved_mean_fps": report["saved_mean_fps"], "missing_slots": len(missing_slots), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
