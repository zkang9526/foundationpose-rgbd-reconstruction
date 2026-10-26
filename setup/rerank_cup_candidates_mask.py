#!/usr/bin/env python3
"""CPU manual-mask silhouette reranking of exported official pose candidates.

This custom diagnostic does not replace the official scorer-top baseline,
train a model, use pose GT, validate true 6D accuracy or change any input.
Selection policy is fixed in advance: coarse IoU top four plus official rank
zero, then highest full-resolution IoU; exact ties favor higher official rank.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback


COARSE_WIDTH = 160
COARSE_HEIGHT = 120
FULL_SHORTLIST = 4


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: {}".format(path))
    return value


def file_info(path, expected=None):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError("Input changed while hashing: {}".format(path))
    information = {"path": str(path), "bytes": after.st_size, "sha256": digest.hexdigest()}
    if expected is not None:
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Missing/invalid expected source SHA256 for " + str(path))
        if information["sha256"] != expected:
            raise ValueError("Source SHA256 differs from inference report: {}".format(path))
    return information


def write_report(report, path):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def triangle_obj(path, scale, np):
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            if len(parts) < 4:
                raise ValueError("Malformed OBJ vertex")
            vertices.append([float(value) for value in parts[1:4]])
        elif parts[0] == "f":
            indices = [int(value.split("/")[0]) - 1 for value in parts[1:]]
            if len(indices) < 3 or any(value < 0 for value in indices):
                raise ValueError("This metric OBJ reader requires positive face indices")
            faces.extend([[indices[0], indices[index], indices[index + 1]]
                          for index in range(1, len(indices) - 1)])
    vertices = np.asarray(vertices, dtype=np.float64) * scale
    faces = np.asarray(faces, dtype=np.int64)
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 4
            or faces.ndim != 2 or faces.shape[1] != 3 or len(faces) < 4
            or not np.isfinite(vertices).all() or np.any(faces < 0) or np.any(faces >= len(vertices))):
        raise ValueError("Metric triangle mesh has invalid geometry")
    return vertices, faces


def pose_valid(pose, np):
    if pose.shape != (4, 4) or not np.isfinite(pose).all():
        return False
    with np.errstate(over="ignore", invalid="ignore"):
        rotation = pose[:3, :3]
        determinant = np.linalg.det(rotation)
        orthogonality = np.linalg.norm(rotation.T @ rotation - np.eye(3))
        row_error = np.linalg.norm(pose[3] - [0, 0, 0, 1])
    return bool(np.isfinite([determinant, orthogonality, row_error]).all()
                and abs(determinant - 1) < 1e-3 and orthogonality < 1e-3
                and row_error < 1e-5 and pose[2, 3] > 0)


def silhouette(vertices, faces, pose, K, width, height, np, cv2):
    points = vertices @ pose[:3, :3].T + pose[:3, 3]
    if not np.isfinite(points).all() or np.min(points[:, 2]) <= 0.001:
        return None, {"renderable": False, "reason": "mesh_not_wholly_in_front_of_camera"}
    projected = points @ K.T
    projected = projected[:, :2] / projected[:, 2:3]
    if not np.isfinite(projected).all():
        return None, {"renderable": False, "reason": "nonfinite_mesh_projection"}
    integer = np.rint(np.clip(projected, -1000000, 1000000)).astype(np.int32)
    rendered = np.zeros((height, width), dtype=np.uint8)
    triangles = integer[faces]
    # Only off-image bounding boxes are culled; all in-view triangles remain.
    minimum, maximum = triangles.min(axis=1), triangles.max(axis=1)
    in_view = ((maximum[:, 0] >= 0) & (minimum[:, 0] < width)
               & (maximum[:, 1] >= 0) & (minimum[:, 1] < height))
    for triangle in triangles[in_view]:
        cv2.fillConvexPoly(rendered, triangle, 255)
    return rendered, {"renderable": True, "triangles_total": len(faces),
                       "triangles_bbox_intersect_image": int(in_view.sum()),
                       "mesh_vertex_z_range_m": [float(points[:, 2].min()), float(points[:, 2].max())],
                       "hidden_surface_removal": False}


def overlap(rendered, target, np):
    predicted = rendered > 0
    intersection = int(np.count_nonzero(predicted & target))
    union = int(np.count_nonzero(predicted | target))
    return {"manual_silhouette_overlap_iou": intersection / union if union else 0.0,
            "intersection_pixels": intersection, "union_pixels": union,
            "projected_pixels": int(predicted.sum()), "manual_mask_pixels": int(target.sum()),
            "mesh_outside_manual_mask_pixels": int(np.count_nonzero(predicted & ~target)),
            "manual_mask_uncovered_pixels": int(np.count_nonzero(target & ~predicted)),
            "is_ground_truth_accuracy": False}


def annotate(image, target, rendered, vertices, pose, K, label, rank, iou, np, cv2):
    colored = image.copy()
    predicted = rendered > 0
    colored[predicted] = (0.7 * colored[predicted] + 0.3 * np.array([255, 0, 255])).astype(np.uint8)
    for binary, color in ((rendered, (255, 0, 255)), (target.astype(np.uint8) * 255, (0, 255, 255))):
        contours = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
        cv2.drawContours(colored, contours, -1, color, 1)
    minimum, maximum = vertices.min(axis=0), vertices.max(axis=0)
    corners = np.array([[x, y, z] for x in (minimum[0], maximum[0])
                        for y in (minimum[1], maximum[1]) for z in (minimum[2], maximum[2])])
    length = float(np.max(maximum - minimum) * 0.25)
    axes = np.vstack([np.zeros(3), np.eye(3) * length])

    def project(values):
        transformed = values @ pose[:3, :3].T + pose[:3, 3]
        if np.min(transformed[:, 2]) <= 0.001:
            return None
        uv = transformed @ K.T
        uv = uv[:, :2] / uv[:, 2:3]
        if not np.isfinite(uv).all() or np.abs(uv).max() > 1000000:
            return None
        return np.rint(uv).astype(np.int32)

    projected_box = project(corners)
    if projected_box is not None:
        for first in range(8):
            for second in range(first + 1, 8):
                if np.count_nonzero(corners[first] != corners[second]) == 1:
                    cv2.line(colored, tuple(projected_box[first]), tuple(projected_box[second]), (180, 160, 80), 1, cv2.LINE_AA)
    projected_axes = project(axes)
    if projected_axes is not None:
        for index, color in enumerate(((0, 0, 255), (0, 230, 0), (255, 0, 0)), 1):
            cv2.line(colored, tuple(projected_axes[0]), tuple(projected_axes[index]), color, 2, cv2.LINE_AA)
    cv2.putText(colored, "{} | official rank {} | mask IoU {:.3f}".format(label, rank, iou),
                (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(colored, "Manual mask guide only; NOT pose GT / true 6D accuracy", (8, 39),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(colored, "Yellow: manual mask | Magenta: projected mesh", (8, image.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)
    return colored


def validate_source(args, report, np):
    source_path = args.inference / "report.json"
    source = read_json(source_path)
    report["inference_report"] = file_info(source_path)
    if (source.get("passed") is not True or source.get("completed_frames") != 5
            or source.get("mode") != "independent_registration_and_official_scorer_candidate_export"
            or source.get("candidate_reranking_performed") is not False):
        raise ValueError("Need a completed five-frame official candidate export, without prior reranking")
    source_ids = [str(item.get("id", "")) for item in source.get("frames", [])]
    if len(source_ids) != 5 or len(set(source_ids)) != 5:
        raise ValueError("Candidate source report must contain five distinct selected frames")
    if source.get("candidate_coordinates", {}).get("pose_definition") != "T_camera_from_original_mesh_metric":
        raise ValueError("Candidate source does not establish original metric mesh coordinates")
    report["mesh"] = file_info(args.mesh, source["source_mesh"]["sha256"])
    report["mask_generation_report"] = file_info(args.mask_dir / "report.json",
                                                 source["mask_generation_report"]["sha256"])
    report["capture_sources"] = {name: file_info(args.scene / name, entry["sha256"])
                                  for name, entry in source["capture_sources"].items()}
    scale = float(source["mesh_coordinates"]["source_vertex_to_meter_scale"])
    if not math.isfinite(scale) or scale not in (1.0, 0.001):
        raise ValueError("Inference did not declare supported source mesh units")
    K = np.asarray(source["camera_matrix"], dtype=np.float64)
    camera = np.loadtxt(str(args.scene / "cam_K.txt"), dtype=np.float64).reshape(3, 3)
    if (K.shape != (3, 3) or not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0
            or not np.allclose(K, camera, rtol=0, atol=1e-7)):
        raise ValueError("Camera matrix differs from candidate inference")
    report.update(camera_matrix=K.tolist(), mesh_source_vertex_to_meter_scale=scale,
                  candidate_gauge_formula=source["candidate_coordinates"]["candidate_gauge_formula"])
    return source, K, scale


def process_frame(item, source, vertices, faces, K, args, report, np, cv2):
    identifier = str(item.get("id", ""))
    if not re.fullmatch(r"[0-9]{6}", identifier) or item.get("passed") is not True:
        raise ValueError("Invalid or failed selected inference frame")
    frame = {"frame_id": identifier, "status": "validating", "pose_is_ground_truth": False,
             "pose_accuracy_validated": False, "official_baseline_modified": False, "candidates": []}
    report["frames"].append(frame)
    filename = identifier + ".png"
    inputs = {}
    for label, path in (("rgb", args.scene / "rgb" / filename),
                        ("depth", args.scene / "depth" / filename),
                        ("mask", args.mask_dir / "masks" / filename)):
        inputs[label] = file_info(path, item["inputs"][label]["sha256"])
    pose_path = args.inference / "poses" / (identifier + ".txt")
    inputs["baseline_pose"] = file_info(pose_path, item["pose"]["sha256"])
    candidate_path = args.inference / "candidates" / (identifier + "_poses_original_metric.npy")
    scores_path = args.inference / "candidates" / (identifier + "_scores.json")
    inputs["candidate_poses"] = file_info(candidate_path, item["candidate_export"]["poses"]["sha256"])
    inputs["candidate_scores"] = file_info(scores_path, item["candidate_export"]["scores"]["sha256"])
    frame["inputs"] = inputs
    baseline = np.loadtxt(str(pose_path), dtype=np.float64).reshape(4, 4)
    candidates = np.load(str(candidate_path), allow_pickle=False)
    score_record = read_json(scores_path)
    if (candidates.dtype != np.float64 or candidates.ndim != 3 or candidates.shape[1:] != (4, 4)
            or not 1 <= len(candidates) <= 252 or not np.isfinite(candidates).all()
            or score_record.get("exported_candidates") != len(candidates)
            or score_record.get("frame_id") != identifier
            or score_record.get("pose_definition") != "T_camera_from_original_mesh_metric"
            or score_record.get("reranking_performed") is not False
            or score_record.get("rank_zero_matches_register_baseline") is not True
            or score_record["poses_npy"]["sha256"] != inputs["candidate_poses"]["sha256"]
            or not np.allclose(candidates[0], baseline, rtol=0, atol=1e-6)):
        raise ValueError("Candidate export format or original-mesh coordinate provenance is inconsistent")
    scores = score_record.get("candidates", [])
    if len(scores) != len(candidates):
        raise ValueError("Candidate scores count differs from pose tensor")
    if any(float(scores[index]["official_scorer_value"]) < float(scores[index + 1]["official_scorer_value"])
           for index in range(len(scores) - 1)):
        raise ValueError("Official candidate score rank order was changed")
    image = cv2.imread(str(args.scene / "rgb" / filename), cv2.IMREAD_COLOR)
    raw_mask = cv2.imread(str(args.mask_dir / "masks" / filename), cv2.IMREAD_UNCHANGED)
    if (image is None or image.dtype != np.uint8 or image.shape != (480, 640, 3)
            or raw_mask is None or raw_mask.dtype != np.uint8 or raw_mask.shape != (480, 640)
            or not set(np.unique(raw_mask).tolist()).issubset({0, 255}) or not np.any(raw_mask)):
        raise ValueError("Expected native 640x480 RGB and nonempty binary manual mask")
    target = raw_mask > 0
    coarse_target = cv2.resize(raw_mask, (COARSE_WIDTH, COARSE_HEIGHT), interpolation=cv2.INTER_NEAREST) > 0
    coarse_K = K.copy()
    coarse_K[0] *= COARSE_WIDTH / 640.0
    coarse_K[1] *= COARSE_HEIGHT / 480.0
    order = []
    for rank, pose in enumerate(candidates):
        score = scores[rank]
        raw_score = float(score["official_scorer_value"])
        if score.get("rank_zero_based") != rank or not math.isfinite(raw_score):
            raise ValueError("Invalid official rank or nonfinite raw scorer value")
        if not pose_valid(pose, np):
            raise ValueError("Candidate is not a valid original-mesh object-to-camera rigid pose")
        rendered, rendering = silhouette(vertices, faces, pose, coarse_K, COARSE_WIDTH, COARSE_HEIGHT, np, cv2)
        candidate = {"official_rank_zero_based": rank, "official_scorer_raw_value": raw_score,
                     "raw_score_is_probability": False, "coarse_rendering": rendering,
                     "coarse_manual_mask_overlap": overlap(rendered, coarse_target, np) if rendered is not None else None,
                     "full_resolution_evaluated": False}
        frame["candidates"].append(candidate)
        if rendered is not None:
            order.append((candidate["coarse_manual_mask_overlap"]["manual_silhouette_overlap_iou"], rank))
    order.sort(key=lambda pair: (-pair[0], pair[1]))
    if not order or not frame["candidates"][0]["coarse_rendering"]["renderable"]:
        raise ValueError("No renderable candidates or baseline mesh is behind the camera")
    shortlist = sorted({rank for _, rank in order[:FULL_SHORTLIST]} | {0})
    frame["full_resolution_shortlist_official_ranks"] = shortlist
    full_silhouettes = {}
    full_order = []
    for rank in shortlist:
        rendered, rendering = silhouette(vertices, faces, candidates[rank], K, 640, 480, np, cv2)
        if rendered is None:
            raise ValueError("A coarse-renderable candidate became invalid at full resolution")
        diagnostic = overlap(rendered, target, np)
        frame["candidates"][rank].update(full_resolution_evaluated=True,
                                          full_rendering=rendering, full_manual_mask_overlap=diagnostic)
        full_silhouettes[rank] = rendered
        full_order.append((diagnostic["manual_silhouette_overlap_iou"], rank))
    full_order.sort(key=lambda pair: (-pair[0], pair[1]))
    selected_rank = full_order[0][1]
    selected = candidates[selected_rank]
    relative_rotation = selected[:3, :3] @ baseline[:3, :3].T
    angle = float(np.degrees(np.arccos(np.clip((np.trace(relative_rotation) - 1) / 2, -1, 1))))
    difference = selected[:3, 3] - baseline[:3, 3]
    if selected_rank == 0:
        # Rank zero is the same returned pose; ignore txt-rounding/SO(3)
        # floating-point deviations when describing its change from itself.
        angle = 0.0
        difference = np.zeros(3)
    output_files = {}
    for label, rank, pose in (("official_baseline", 0, baseline), ("custom_mask_selected", selected_rank, selected)):
        output_pose = args.output / label / "poses" / (identifier + ".txt")
        np.savetxt(str(output_pose), pose, fmt="%.12g")
        silhouette_path = args.output / label / "silhouettes" / filename
        overlay_path = args.output / label / "overlays" / filename
        diagnostic = frame["candidates"][rank]["full_manual_mask_overlap"]
        overlay = annotate(image, target, full_silhouettes[rank], vertices, pose, K, label, rank,
                           diagnostic["manual_silhouette_overlap_iou"], np, cv2)
        if not cv2.imwrite(str(silhouette_path), full_silhouettes[rank]) or not cv2.imwrite(str(overlay_path), overlay):
            raise RuntimeError("Could not save silhouette/overlay diagnostics")
        output_files[label] = {"pose": file_info(output_pose), "silhouette": file_info(silhouette_path),
                               "overlay": file_info(overlay_path), "manual_mask_overlap": diagnostic}
    baseline_iou = frame["candidates"][0]["full_manual_mask_overlap"]["manual_silhouette_overlap_iou"]
    selected_iou = frame["candidates"][selected_rank]["full_manual_mask_overlap"]["manual_silhouette_overlap_iou"]
    frame.update(status="custom_mask_selection_completed_requires_visual_review", passed=True,
                 official_baseline_rank=0, selected_official_rank=selected_rank,
                 official_raw_score_selected=float(scores[selected_rank]["official_scorer_value"]),
                 manual_mask_overlap_change=selected_iou - baseline_iou,
                 relative_to_baseline_rotation_degrees=angle,
                 relative_to_baseline_translation_vector_m=difference.tolist(),
                 relative_to_baseline_translation_norm_m=float(np.linalg.norm(difference)),
                 relative_transform_is_not_pose_error=True, outputs=output_files)
    for entry in inputs.values():
        file_info(Path(entry["path"]), entry["sha256"])
    return frame


def run(args, report):
    import cv2
    import numpy as np
    source, K, scale = validate_source(args, report, np)
    vertices, faces = triangle_obj(args.mesh, scale, np)
    report["mesh_geometry"] = {"vertices": len(vertices), "triangles": len(faces),
                                "all_triangles_used_for_in_view_silhouette": True, "units": "meters"}
    for item in source["frames"]:
        started = time.monotonic()
        frame = process_frame(item, source, vertices, faces, K, args, report, np, cv2)
        frame["elapsed_seconds"] = time.monotonic() - started
        write_report(report, args.output / "report.json")
        print(json.dumps({"frame": frame["frame_id"], "selected_official_rank": frame["selected_official_rank"],
                          "mask_overlap_change": frame["manual_mask_overlap_change"],
                          "pose_accuracy_validated": False}), flush=True)
    for entry in (report["inference_report"], report["mesh"], report["mask_generation_report"]):
        file_info(Path(entry["path"]), entry["sha256"])
    for entry in report["capture_sources"].values():
        file_info(Path(entry["path"]), entry["sha256"])
    report.update(passed=True, completed_frames=len(report["frames"]),
                  status="custom_mask_diagnostic_completed_requires_visual_review",
                  number_of_changed_official_ranks=sum(frame["selected_official_rank"] != 0 for frame in report["frames"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inference", type=Path, required=True)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--mask-dir", type=Path, required=True)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name in ("inference", "scene", "mask_dir", "mesh", "output"):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    report = {"schema_version": 1, "passed": False, "status": "validating_inputs", "frames": [],
              "started_at_utc": utc_now(), "output": str(args.output),
              "method": "Custom manual-mask silhouette guide on official scorer-ranked pose candidates",
              "selection_policy_fixed_before_processing": {
                  "coarse_image_size_wh": [COARSE_WIDTH, COARSE_HEIGHT],
                  "coarse_mask_resize": "nearest-neighbor", "coarse_K": "native K first two rows scaled by 0.25",
                  "coarse_order": "descending manual silhouette IoU, exact ties by smaller official rank",
                  "full_resolution_shortlist": "coarse top four plus official rank zero",
                  "full_image_size_wh": [640, 480],
                  "final_order": "highest full-resolution manual silhouette IoU; exact ties favor smaller official rank",
                  "mesh_projection": "CPU union of every image-intersecting projected triangle; no mesh decimation",
                  "manual_frame_specific_selection": False,
              },
              "official_baseline_is_preserved": True, "original_inference_pose_files_modified": False,
              "source_mesh_modified": False, "inputs_modified": False,
              "official_scorer_algorithm_modified": False, "custom_selection_is_official_baseline": False,
              "network_inference_reexecuted": False, "training_executed": False,
              "planned_angles_used": False, "gt_available": False, "gt_or_add_metrics_computed": False,
              "manual_mask_overlap_is_true_6d_accuracy": False, "pose_accuracy_validated": False,
              "cpu_only": True, "gpu_used": False, "network_or_ssh_used": False,
              "limitations": [
                  "A manual silhouette can favor coarse orientation consistency without establishing correct true 6D pose.",
                  "Mask boundaries and reconstructed mesh contain uncertainty; overlap can reward those errors.",
                  "Only coarse top four plus official rank zero are checked at native resolution; this is not exhaustive native-resolution search.",
                  "No depth fitting, hidden-surface validation, calibrated physical size or pose GT comparison is performed.",
                  "Official scorer raw values are not probabilities or accuracy metrics.",
                  "Relative rotation/translation are changes from the baseline, not errors to GT.",
              ]}
    created = False
    started = time.monotonic()
    try:
        if os.path.lexists(str(args.output)):
            raise ValueError("Output already exists; use a new directory")
        for source in (args.inference, args.scene, args.mask_dir):
            if args.output == source or source in args.output.parents or args.output in source.parents:
                raise ValueError("Input/output containment is refused")
        if args.output in args.mesh.parents or args.output == args.mesh:
            raise ValueError("Output would contain the source mesh")
        args.output.mkdir(parents=True, exist_ok=False)
        created = True
        for label in ("official_baseline", "custom_mask_selected"):
            for folder in ("poses", "silhouettes", "overlays"):
                (args.output / label / folder).mkdir(parents=True, exist_ok=False)
        report["script"] = file_info(Path(__file__))
        write_report(report, args.output / "report.json")
        run(args, report)
    except (Exception, KeyboardInterrupt) as error:
        report.update(passed=False, status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                      error={"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
        traceback.print_exc()
    finally:
        report.update(ended_at_utc=utc_now(), elapsed_seconds=time.monotonic() - started)
        if created:
            write_report(report, args.output / "report.json")
    print(json.dumps({"passed": report["passed"], "status": report["status"],
                      "completed_frames": report.get("completed_frames", 0),
                      "report": str(args.output / "report.json") if created else None,
                      "pose_accuracy_validated": False}), flush=True)
    return 0 if report["passed"] else (130 if report["status"] == "interrupted" else 1)


if __name__ == "__main__":
    sys.exit(main())
