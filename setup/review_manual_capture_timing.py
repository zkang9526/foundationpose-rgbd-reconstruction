#!/usr/bin/env python3
"""Read existing manual RGB-D photo timing records without accessing a camera."""
import argparse
import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def describe(values):
    values = list(values)
    if not values:
        return None
    return {"count": len(values), "min": min(values), "median": statistics.median(values),
            "mean": statistics.mean(values), "max": max(values)}


def source_record(path, root):
    path = path.resolve()
    try:
        recorded_path = path.relative_to(root).as_posix()
        scope = 'project'
    except ValueError:
        recorded_path = str(path)
        scope = 'external_capture_volume'
    return {"path": recorded_path, "path_scope": scope,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def summarize_run(run_dir, root):
    path = run_dir.resolve() / "run.json"
    run = load_json(path)
    keys = ("run_id", "label", "status", "start", "end", "exit_code", "child_exitcode", "warnings", "note")
    return {"source": source_record(path, root), **{key: run.get(key) for key in keys}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-run", type=Path, required=True)
    parser.add_argument("--format-run", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    scene = args.scene.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Use a new output path to preserve previous review evidence: " + str(output))
    metadata = load_json(scene / "metadata.json")
    capture_report = load_json(scene / "report.json")
    frames = metadata["frames"]
    if not frames or metadata["capture_mode"] != "manual_stationary_rgbd_photos":
        raise ValueError("An existing manual photo capture with saved frames is required")
    with (scene / "timestamps.csv").open(encoding="utf-8", newline="") as handle:
        csv_frames = list(csv.DictReader(handle))
    json_frames = load_json(scene / "timestamps.json")
    independent = {}
    for stream in ("color", "depth"):
        numbers = [int(frame[stream + "_frame_number"]) for frame in frames]
        timestamps = [float(frame[stream + "_timestamp_ms"]) for frame in frames]
        independent[stream] = {
            "unique_frame_numbers": len(set(numbers)),
            "duplicate_frame_numbers": len(numbers) - len(set(numbers)),
            "strictly_increasing_frame_numbers": all(b > a for a, b in zip(numbers, numbers[1:])),
            "strictly_increasing_timestamps": all(b > a for a, b in zip(timestamps, timestamps[1:])),
            "first_frame_number": numbers[0], "last_frame_number": numbers[-1],
            "timestamp_domains": sorted({frame[stream + "_timestamp_domain"] for frame in frames}),
        }
    waits = [frame["host_elapsed_seconds"] - frame["request_host_elapsed_seconds"] for frame in frames]
    intervals = [b["host_elapsed_seconds"] - a["host_elapsed_seconds"] for a, b in zip(frames, frames[1:])]
    timestamp_gaps = [abs(frame["depth_timestamp_ms"] - frame["color_timestamp_ms"]) for frame in frames]
    requested_settle = float(metadata["requested"]["settle_seconds"])
    expected_count = int(metadata["requested"]["views"])
    consistency = {
        "metadata_frames": len(frames), "csv_frames": len(csv_frames), "timestamp_json_frames": len(json_frames),
        "requested_views": expected_count,
        "saved_count_matches_requested": len(frames) == expected_count == metadata["saved_frames"] == capture_report["saved_frames"],
        "metadata_and_timestamp_json_equal": frames == json_frames,
        "csv_order_matches_metadata": len(csv_frames) == len(frames) and all(
            int(row["index"]) == frame["index"] and row["rgb"] == frame["rgb"] and row["depth"] == frame["depth"]
            for row, frame in zip(csv_frames, frames)),
        "sequential_indices_and_relative_names": all(
            frame["index"] == index and frame["rgb"] == "rgb/{:06d}.png".format(index)
            and frame["depth"] == "depth/{:06d}.png".format(index)
            for index, frame in enumerate(frames)),
    }
    capture_run = summarize_run(args.capture_run, root)
    format_run = summarize_run(args.format_run, root)
    checks = {
        "counts_and_order": all(consistency[key] for key in (
            "saved_count_matches_requested", "metadata_and_timestamp_json_equal", "csv_order_matches_metadata",
            "sequential_indices_and_relative_names")),
        "distinct_ordered_sensor_frames": all(
            item["duplicate_frame_numbers"] == 0 and item["strictly_increasing_frame_numbers"]
            and item["strictly_increasing_timestamps"] for item in independent.values()),
        "all_post_request_waits_meet_requested_settle": all(wait + 1e-8 >= requested_settle for wait in waits),
        "all_pair_offsets_within_requested_limit": all(
            gap <= metadata["requested"]["max_timestamp_gap_ms"] for gap in timestamp_gaps),
        "capture_completed_and_pipeline_stopped": metadata.get("passed") is True
            and metadata.get("status") == "complete" and metadata.get("pipeline_stopped") is True,
        "capture_and_existing_format_runs_exit_zero": all(
            run.get("status") == "passed" and run.get("exit_code") == 0 and run.get("child_exitcode") == 0
            for run in (capture_run, format_run)),
    }
    source_names = ("metadata.json", "report.json", "timestamps.csv", "timestamps.json", "K.txt", "cam_K.txt", "depth_scale.txt")
    report = {
        "schema_version": 1, "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Read-only timing and completion review of existing manual photo records; no camera access or repeated file-format validation",
        "passed": all(checks.values()), "scene": str(scene),
        "source_files": [source_record(scene / name, root) for name in source_names],
        "review_script": source_record(Path(__file__), root), "checks": checks, "record_consistency": consistency,
        "independent_frames": independent, "post_request_wait_seconds": describe(waits),
        "requested_settle_seconds": requested_settle, "inter_photo_interval_seconds": describe(intervals),
        "absolute_rgb_depth_timestamp_gap_ms": describe(timestamp_gaps),
        "whole_image_depth_nonzero_ratio": describe(frame["saved_valid_pixel_ratio"] for frame in frames),
        "conversion_rejected_pixels_total": sum(frame["conversion_rejected_pixels"] for frame in frames),
        "saved_depth": metadata["saved_depth"],
        "depth_scale_meters_per_saved_unit_file": float((scene / "depth_scale.txt").read_text().strip()),
        "requested_image_width_height": [metadata["requested"]["width"], metadata["requested"]["height"]],
        "depth_aligned_to": metadata["requested"]["align_to"],
        "planned_angle_degrees": [frame["planned_angle_degrees"] for frame in frames],
        "planned_angles_are_measured": metadata.get("planned_angles_are_measured"),
        "planned_angles_are_ground_truth_poses": metadata.get("planned_angles_are_ground_truth_poses"),
        "capture_completion": {key: metadata.get(key) for key in (
            "passed", "status", "pipeline_started", "pipeline_stopped", "warnings", "stop_error", "rejected_pairs",
            "started_at_utc", "capture_started_at_utc", "finished_at_utc", "elapsed_seconds", "capture_seconds")},
        "capture_run": capture_run, "existing_format_run": format_run,
        "limitations": [
            "Manual photographs have variable intervals; a fixed image saving rate is not required or assessed.",
            "The one-second post-keypress wait is recorded software behavior; physical stillness and hand removal require visual review.",
            "Distinct sensor frames do not prove distinct viewpoints, measured rotation or complete object coverage.",
            "Planned angles are order labels, not measured angles, extrinsics or 6D ground truth poses.",
            "Whole-image nonzero depth ratios include the background and do not measure cup ROI depth completeness.",
            "This review uses stored metadata and existing format results; it does not rerun format validation or assess image quality.",
            "No masks, reconstruction, pose inference or pose accuracy validation is performed.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "saved_frames": len(frames),
                      "min_post_request_wait_seconds": min(waits), "max_rgb_depth_timestamp_gap_ms": max(timestamp_gaps),
                      "pipeline_stopped": metadata.get("pipeline_stopped"), "output": str(output)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
