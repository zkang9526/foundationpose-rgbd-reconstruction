#!/usr/bin/env python3
"""Verify selected reference masks and record limited readiness for a pilot."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def project_path(root, value, label):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(label + " must be a project-relative path")
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError(label + " escapes the project root")
    return path


def test_frame_id(value):
    if not isinstance(value, str) or len(value) != 6 or not value.isascii() or not value.isdecimal():
        raise ValueError("Test frame must be a six-digit image stem")
    return value


def verify_test_qa(root, qa_path, reference_records):
    """Verify held-out test evidence without treating masks or labels as GT."""
    qa_path = qa_path.resolve()
    qa_path.relative_to(root)
    qa = read(qa_path)
    scene = project_path(root, qa.get("source_scene"), "Test source_scene")
    masks = project_path(root, qa.get("mask_directory"), "Test mask_directory")
    generation_path = project_path(root, qa.get("generation_report_path"),
                                   "Test generation_report_path")
    if scene.relative_to(root).as_posix() in {item["scene"] for item in reference_records}:
        raise ValueError("Independent tests cannot reuse a reference scene")
    if generation_path != (masks / "report.json").resolve():
        raise ValueError("Test generation report does not belong to the selected mask directory")
    if sha(generation_path) != qa.get("source_report_sha256"):
        raise ValueError("Test generation report changed after visual QA")
    rgb_frames = {path.stem for path in (scene / "rgb").glob("*.png")}
    depth_frames = {path.stem for path in (scene / "depth").glob("*.png")}
    if rgb_frames != depth_frames or len(rgb_frames) != 6:
        raise ValueError("Expected exactly six paired raw test photographs")
    for frame in rgb_frames:
        test_frame_id(frame)
    metadata = read(scene / "metadata.json")
    if (metadata.get("passed") is not True or metadata.get("status") != "complete"
            or metadata.get("saved_frames") != 6 or metadata.get("pipeline_stopped") is not True):
        raise ValueError("Independent test capture did not complete with six saved frames")
    accepted = qa.get("frames")
    excluded = qa.get("excluded_frames")
    if not isinstance(accepted, list) or len(accepted) != 5 or not isinstance(excluded, list):
        raise ValueError("Expected five individually accepted tests and an explicit excluded-frame list")
    accepted_ids = [test_frame_id(item.get("frame")) for item in accepted]
    excluded_ids = [test_frame_id(item.get("frame")) for item in excluded]
    if len(set(accepted_ids)) != len(accepted_ids) or len(set(excluded_ids)) != len(excluded_ids):
        raise ValueError("Duplicate accepted or excluded test frame")
    if set(accepted_ids) & set(excluded_ids):
        raise ValueError("Accepted and excluded test frames overlap")
    if set(accepted_ids) | set(excluded_ids) != rgb_frames:
        raise ValueError("Accepted and excluded tests do not fully cover the six raw pairs")
    generation = read(generation_path)
    generated = {Path(item["frame"]).stem: item for item in generation["frames"]}
    if (generation.get("passed") is not True or generation.get("processed_frames") != 5
            or len(generation["frames"]) != 5 or set(generated) != set(accepted_ids)):
        raise ValueError("Test mask generation does not match the five accepted tests")
    verified_frames = []
    for item in accepted:
        frame = item["frame"]
        if item.get("accepted_for_initial_inference") is not True:
            raise ValueError("Test frame not accepted for initial inference: " + frame)
        filename = frame + ".png"
        file_checks = ((scene / "rgb" / filename, "source_rgb_sha256"),
                       (scene / "depth" / filename, "source_depth_sha256"),
                       (masks / "masks" / filename, "mask_sha256"),
                       (masks / "overlays" / filename, "overlay_sha256"))
        verified = {"frame": frame, "accepted_for_initial_inference": True}
        for path, key in file_checks:
            actual = sha(path)
            if actual != item.get(key) or actual != generated[frame].get(key):
                raise ValueError("Test source or output changed: " + str(path))
            verified[key] = actual
        verified_frames.append(verified)
    excluded_details = []
    for item in excluded:
        frame = item["frame"]
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError("Excluded test frame lacks a reason: " + frame)
        excluded_details.append({"frame": frame, "reason": item["reason"],
                                 "source_rgb_sha256": sha(scene / "rgb" / (frame + ".png")),
                                 "source_depth_sha256": sha(scene / "depth" / (frame + ".png")),
                                 "raw_pair_preserved": True})
    return {
        "independent_test_capture_confirmed": True, "usable_test_frames": 5,
        "excluded_tests": excluded_details,
        "independent_test_evidence": {
            "qa_path": qa_path.relative_to(root).as_posix(), "qa_sha256": sha(qa_path),
            "source_scene": scene.relative_to(root).as_posix(),
            "mask_directory": masks.relative_to(root).as_posix(),
            "generation_report_path": generation_path.relative_to(root).as_posix(),
            "generation_report_sha256": sha(generation_path),
            "source_metadata_sha256": sha(scene / "metadata.json"),
            "raw_paired_frames": 6, "accepted_frames": verified_frames,
            "accepted_and_excluded_disjoint": True, "all_raw_pairs_accounted_for": True,
            "verified_against_actual_file_hashes_and_generation_report": True,
            "dataset_role": "Held-out initial pose inference tests only, not reference reconstruction",
            "pose_ground_truth_available": False, "planned_angles_are_measured": False,
            "planned_angles_are_pose_ground_truth": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prepared-inputs", type=Path, help="Completed range-filtered pilot report")
    parser.add_argument("--depth-review", type=Path, help="Completed raw depth distribution audit")
    parser.add_argument("--test-qa", type=Path, help="Accepted held-out test QA with actual file hashes")
    parser.add_argument("--ubuntu-contacted-this-phase", action="store_true",
                        help="Record that SSH contact occurred in this phase; does not confirm upload or dependencies")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.output.exists():
        parser.error("Refusing to replace readiness evidence")
    selected = (
        ("side", "cup_photos_20261013_165803_194", "cup_masks_side_165803_v4",
         "cup_masks_side_165803_v4_final_visual_qa.json"),
        ("oblique_top", "cup_photos_20261013_185306_528", "cup_masks_top_185306_v5",
         "cup_masks_top_185306_v5_final_visual_qa.json"),
    )
    records = []
    for role, name, version, qa_name in selected:
        scene = root / "foundationpose_data/windows_captures" / name
        masks = root / "foundationpose_data/derived" / version
        qa_path = root / "reports" / qa_name
        qa = read(qa_path)
        qframes = qa["frames"]
        if isinstance(qframes, dict):
            qframes = [dict(item, frame=key) for key, item in qframes.items()]
        reviewed = {item["frame"].replace(".png", ""): item for item in qframes}
        report = read(masks / "report.json")
        expected = {"{:06d}".format(i) for i in range(36)}
        if set(reviewed) != expected or report["processed_frames"] != 36 or not report["passed"]:
            raise ValueError("Incomplete full reference QA " + version)
        stats = []
        for item in report["frames"]:
            stem = item["frame"].replace(".png", "")
            if reviewed[stem].get("accepted_for_initial_reconstruction") is not True:
                raise ValueError("Unaccepted frame " + version + ":" + stem)
            checks = ((masks / "masks" / item["frame"], item["mask_sha256"]),
                      (masks / "overlays" / item["frame"], item["overlay_sha256"]),
                      (scene / "rgb" / item["frame"], item["source_rgb_sha256"]),
                      (scene / "depth" / item["frame"], item["source_depth_sha256"]))
            for path, expected_sha in checks:
                if sha(path) != expected_sha:
                    raise ValueError("Source or output changed: " + str(path))
            stats.append(item["mask_depth_valid_percent"])
        records.append({"role": role, "scene": scene.relative_to(root).as_posix(),
                        "mask_directory": masks.relative_to(root).as_posix(),
                        "qa": qa_path.relative_to(root).as_posix(), "qa_sha256": sha(qa_path),
                        "generation_report_sha256": sha(masks / "report.json"),
                        "paired_frames": 36, "accepted_for_initial_reconstruction": True,
                        "mean_mask_depth_nonzero_percent": sum(stats) / len(stats),
                        "nonzero_is_not_correct_depth": True})
    result = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": True, "reference_masks_ready_for_initial_pilot": True,
        "paired_reference_frames": 72, "sequences": records,
        "independent_test_capture_confirmed": False, "object_dimensions_confirmed": False,
        "cup_mesh_created": False, "estimated_reference_poses_created": False,
        "foundationpose_cup_inference_completed": False, "pose_ground_truth_available": False,
        "ubuntu_contacted_this_phase": args.ubuntu_contacted_this_phase,
        "limitations": [
            "Manual visual mask acceptance for an initial reconstruction attempt, not pixel or pose ground truth.",
            "Cup is inverted; cup interior and support-contact surface were not completely observed.",
            "Mask boundary uncertainty is about 1-3 pixels and contact edges about 2-4 pixels.",
            "Nonzero raw depth includes distant/outlier readings; review/filter separately before reconstruction.",
            "Separate camera heights/sequences require object registration; no known cross-sequence poses.",
            "Planned rotation labels are not measured rotations or 6D poses.",
            ("Ubuntu contacted in this phase; this flag does not confirm upload, import or reconstruction dependency readiness."
             if args.ubuntu_contacted_this_phase else
             "Ubuntu intentionally offline; package preparation does not confirm upload or reconstruction readiness of dependencies."),
        ],
    }
    if args.test_qa:
        result.update(verify_test_qa(root, args.test_qa, records))
    if args.prepared_inputs:
        inputs = read(args.prepared_inputs)
        if inputs.get("passed") is not True or inputs.get("paired_frames") != 72:
            raise ValueError("Incomplete prepared depth inputs")
        for sequence in inputs["sequences"]:
            prepared_scene = root / sequence["output_scene"]
            for frame in sequence["frames"]:
                for folder, key in (("rgb", "rgb_sha256"), ("masks", "mask_sha256"),
                                    ("depth", "filtered_depth_sha256")):
                    if sha(prepared_scene / folder / frame["frame"]) != frame[key]:
                        raise ValueError("Prepared input changed")
        result["prepared_pilot_inputs"] = {
            "report_path": args.prepared_inputs.resolve().relative_to(root).as_posix(),
            "report_sha256": sha(args.prepared_inputs),
            "depth_range_mm_inclusive": inputs["depth_range_mm_inclusive"],
            "sequences": [{"role": sequence["role"], "output_scene": sequence["output_scene"],
                           "mean_retained_target_percent": sequence["mean_retained_target_percent"]}
                          for sequence in inputs["sequences"]],
            "verified_against_saved_file_hashes": True,
            "depth_is_exploratory_not_validated_sensor_accuracy": True,
        }
    if args.depth_review:
        depth_review = read(args.depth_review)
        if depth_review.get("passed") is not True:
            raise ValueError("Incomplete depth review")
        result["raw_depth_review"] = {
            "path": args.depth_review.resolve().relative_to(root).as_posix(),
            "sha256": sha(args.depth_review),
            "depth_accuracy_validated": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "paired_reference_frames": 72,
                      "reference_masks_ready_for_initial_pilot": True,
                      "independent_test_capture_confirmed": result["independent_test_capture_confirmed"],
                      "ubuntu_contacted_this_phase": result["ubuntu_contacted_this_phase"],
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
