#!/usr/bin/env python3
"""Register a reconstructed cup independently in each QA-accepted RGB-D photo.

Run inside the existing FoundationPose environment through run_logged. This
entry does no tracking, reconstruction, training, GT comparison or ADD scoring.
The mesh must already exist; its physical unit must be declared explicitly.
"""

import argparse
import datetime
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import traceback

from verify_demo import (file_info, inspect_pose, loaded_weight_info, positive_int,
                         write_report)


EXPECTED_PIN = "a1b694b83e633c2cb6115b9063d940a687759392"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_json(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: {}".format(path))
    return value


def checked_info(path, expected_sha256=None):
    information = file_info(path)
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
                or information["sha256"] != expected_sha256.lower()):
            raise ValueError("Source SHA256 differs from QA/provenance: {}".format(path))
    return information


def portable_suffix(path, expected_parts):
    parts = PurePosixPath(str(path).replace("\\", "/")).parts
    return tuple(parts[-len(expected_parts):]) == tuple(expected_parts)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True,
                        help="Existing FoundationPose checkout at the validated pin")
    parser.add_argument("--scene", type=Path, required=True,
                        help="Original held-out capture with rgb/, depth/, cam_K.txt and metadata.json")
    parser.add_argument("--mask-dir", type=Path, required=True,
                        help="Reviewed generation directory containing masks/ and report.json")
    parser.add_argument("--qa", type=Path, required=True,
                        help="Visual-QA JSON with accepted frame IDs and source SHA256 values")
    parser.add_argument("--mesh", type=Path, required=True,
                        help="Existing reconstructed triangle mesh")
    parser.add_argument("--mesh-units", choices=("m", "mm"), required=True,
                        help="Physical unit of source vertices; explicit, never inferred")
    parser.add_argument("--output", type=Path, required=True,
                        help="New result directory; existing paths are refused")
    parser.add_argument("--register-iterations", type=positive_int, default=5)
    return parser.parse_args()


def validate_provenance(args, report):
    repo, scene, maskdir = args.repo, args.scene, args.mask_dir
    for filename in ("estimater.py", "datareader.py", "Utils.py"):
        report.setdefault("upstream_sources", {})[filename] = checked_info(repo / filename)
    revision = subprocess.run(["git", "-c", "safe.directory=" + str(repo),
                              "-C", str(repo), "rev-parse", "HEAD"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False)
    if revision.returncode != 0:
        raise RuntimeError("Cannot verify FoundationPose checkout commit")
    commit = revision.stdout.decode("ascii", errors="strict").strip()
    report["repo_commit"] = commit
    if commit != EXPECTED_PIN:
        raise ValueError("FoundationPose commit differs from the validated API pin")
    qa = load_json(args.qa)
    report["qa"] = checked_info(args.qa)
    if qa.get("all_selected_frames_accepted_for_initial_inference") is not True:
        raise ValueError("QA has not accepted all selected frames for initial inference")
    if qa.get("is_pose_ground_truth") is not False:
        raise ValueError("QA must explicitly distinguish estimated input from pose GT")
    if not portable_suffix(qa.get("source_scene", ""), (scene.parent.name, scene.name)):
        raise ValueError("QA source scene does not match --scene")
    if not portable_suffix(qa.get("mask_directory", ""), (maskdir.parent.name, maskdir.name)):
        raise ValueError("QA mask directory does not match --mask-dir")
    generation_path = maskdir / "report.json"
    if not portable_suffix(qa.get("generation_report_path", ""), (maskdir.name, "report.json")):
        raise ValueError("QA generation report path does not match --mask-dir")
    if not qa.get("source_report_sha256"):
        raise ValueError("QA lacks the generation report SHA256")
    report["mask_generation_report"] = checked_info(generation_path, qa["source_report_sha256"])
    generation = load_json(generation_path)
    if generation.get("passed") is not True or generation.get("status") != "complete":
        raise ValueError("Mask generation did not complete")
    source_hashes = generation.get("source_hashes", {})
    report["capture_sources"] = {}
    for filename in ("cam_K.txt", "K.txt", "depth_scale.txt", "metadata.json", "report.json"):
        expected = source_hashes.get(filename, {}).get("sha256")
        if expected is None:
            raise ValueError("Mask provenance lacks source hash for " + filename)
        report["capture_sources"][filename] = checked_info(scene / filename, expected)
    metadata = load_json(scene / "metadata.json")
    capture_report = load_json(scene / "report.json")
    for value in (metadata, capture_report):
        saved = value.get("saved_depth", {})
        saved_scale = float(saved.get("scale_meters_per_saved_unit", -1))
        if (value.get("passed") is not True or value.get("status") != "complete"
                or value.get("requested", {}).get("align_to") != "color"
                or saved.get("unit") != "millimeter" or saved.get("dtype") != "uint16"
                or saved.get("invalid_value") != 0
                or not math.isfinite(saved_scale) or abs(saved_scale - 0.001) > 1e-12):
            raise ValueError("Capture metadata does not confirm aligned uint16 millimeter depth")
    if metadata.get("requested", {}).get("color_format") != "RGB8":
        raise ValueError("Capture color format must be RGB8")
    generation_frames = {}
    for frame in generation.get("frames", []):
        name = str(frame.get("frame", ""))
        if not re.fullmatch(r"[0-9]{6}\.png", name) or name in generation_frames:
            raise ValueError("Invalid or duplicate frame in generation report")
        generation_frames[name] = frame
    frames = []
    seen = set()
    for item in qa.get("frames", []):
        identifier = str(item.get("frame", ""))
        if not re.fullmatch(r"[0-9]{6}", identifier) or identifier in seen:
            raise ValueError("Invalid or duplicate QA frame ID")
        seen.add(identifier)
        if item.get("accepted_for_initial_inference") is not True:
            raise ValueError("QA contains a selected frame that was not accepted")
        filename = identifier + ".png"
        generated = generation_frames.get(filename)
        if generated is None:
            raise ValueError("QA frame is absent from generation report")
        info = {"id": identifier, "operation": "independent_register", "inputs": {}}
        pairs = ((scene / "rgb" / filename, "source_rgb_sha256", "source_rgb_path", "rgb"),
                 (scene / "depth" / filename, "source_depth_sha256", "source_depth_path", "depth"),
                 (maskdir / "masks" / filename, "mask_sha256", "mask_path", "mask"))
        for path, hash_key, path_key, label in pairs:
            expected = item.get(hash_key)
            if expected is None or generated.get(hash_key) != expected:
                raise ValueError("QA and generation SHA disagree for {} {}".format(identifier, label))
            if not portable_suffix(item.get(path_key, ""), (path.parent.parent.name, path.parent.name, filename)):
                raise ValueError("QA input path differs from selected {}".format(path))
            info["inputs"][label] = checked_info(path, expected)
        frames.append(info)
    if not frames or len(frames) != qa.get("accepted_frame_count"):
        raise ValueError("QA accepted frame count does not match its frame list")
    excluded = {str(item.get("frame")) for item in qa.get("excluded_frames", [])}
    if excluded & seen:
        raise ValueError("An excluded QA frame was also selected")
    report.update(selected_frame_ids=[frame["id"] for frame in frames],
                  accepted_frame_count=len(frames), excluded_frames=qa.get("excluded_frames", []),
                  qa_limitations=qa.get("remaining_limitations", []),
                  dataset_role=qa.get("dataset_role"),
                  source_mesh=checked_info(args.mesh))
    return metadata, frames


def load_inputs(scene, maskdir, metadata, frame, np, cv2):
    filename = frame["id"] + ".png"
    for value in frame["inputs"].values():
        checked_info(Path(value["path"]), value["sha256"])
    color_bgr = cv2.imread(str(scene / "rgb" / filename), cv2.IMREAD_UNCHANGED)
    depth_raw = cv2.imread(str(scene / "depth" / filename), cv2.IMREAD_UNCHANGED)
    mask_raw = cv2.imread(str(maskdir / "masks" / filename), cv2.IMREAD_UNCHANGED)
    width = int(metadata["color_intrinsics"]["width"])
    height = int(metadata["color_intrinsics"]["height"])
    if color_bgr is None or color_bgr.dtype != np.uint8 or color_bgr.shape != (height, width, 3):
        raise ValueError("Unexpected RGB PNG type or dimensions")
    if depth_raw is None or depth_raw.dtype != np.uint16 or depth_raw.shape != (height, width):
        raise ValueError("Expected native uint16 aligned depth PNG")
    if (mask_raw is None or mask_raw.dtype != np.uint8 or mask_raw.shape != depth_raw.shape
            or not set(np.unique(mask_raw).tolist()).issubset({0, 255})):
        raise ValueError("Expected binary uint8 mask at native image dimensions")
    color = np.ascontiguousarray(cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB))
    depth = np.ascontiguousarray(depth_raw.astype(np.float32) * 0.001)
    mask = np.ascontiguousarray(mask_raw > 0)
    valid = mask & (depth_raw > 0)
    if int(valid.sum()) < 4:
        raise ValueError("Insufficient original masked depth for registration")
    frame.update(image_shape=[height, width], mask_pixels=int(mask.sum()),
                 raw_mask_nonzero_depth_pixels=int(valid.sum()),
                 raw_mask_nonzero_depth_percent=100.0 * int(valid.sum()) / int(mask.sum()),
                 raw_mask_positive_depth_median_m=float(np.median(depth[valid])))
    return color, depth, mask


def run(args, report):
    metadata, frames = validate_provenance(args, report)
    output = args.output
    write_report(report, output / "report.json")
    # Dependency imports happen only after CLI/provenance checks, never for --help.
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, str(args.repo))
    os.chdir(str(args.repo))
    import cv2
    import imageio.v2 as imageio
    import numpy as np
    import torch
    import trimesh
    import nvdiffrast.torch as dr
    import estimater
    from estimater import FoundationPose, PoseRefinePredictor, ScorePredictor
    from Utils import draw_posed_3d_box, draw_xyz_axis, set_logging_format, set_seed

    if Path(estimater.__file__).resolve().parent != args.repo:
        raise RuntimeError("Imported estimater from a different checkout")
    K = np.loadtxt(str(args.scene / "cam_K.txt"), dtype=np.float64).reshape(3, 3)
    duplicate_K = np.loadtxt(str(args.scene / "K.txt"), dtype=np.float64).reshape(3, 3)
    scale = float((args.scene / "depth_scale.txt").read_text(encoding="utf-8").strip())
    intrinsics = metadata["color_intrinsics"]
    aligned = metadata["aligned_depth_intrinsics"]
    expected_K = np.array([[intrinsics["fx"], 0, intrinsics["cx"]],
                           [0, intrinsics["fy"], intrinsics["cy"]], [0, 0, 1]], dtype=np.float64)
    aligned_K = np.array([[aligned["fx"], 0, aligned["cx"]],
                          [0, aligned["fy"], aligned["cy"]], [0, 0, 1]], dtype=np.float64)
    if (not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0
            or not np.allclose(K, duplicate_K, rtol=0, atol=1e-7)
            or not np.allclose(K, expected_K, rtol=0, atol=1e-6)
            or not np.allclose(K, aligned_K, rtol=0, atol=1e-6)
            or not math.isfinite(scale) or abs(scale - 0.001) > 1e-12):
        raise ValueError("Intrinsics or saved depth unit differ from capture metadata")
    if (int(aligned["width"]) != int(intrinsics["width"])
            or int(aligned["height"]) != int(intrinsics["height"])):
        raise ValueError("Aligned depth and color dimensions differ")
    for values in (intrinsics, aligned):
        distortion = np.asarray(values.get("distortion_coefficients", []), dtype=np.float64)
        if distortion.size != 5 or not np.isfinite(distortion).all() or np.any(np.abs(distortion) > 1e-12):
            raise ValueError("This native pinhole input entry requires zero distortion coefficients")
    report.update(camera_matrix=K.tolist(), depth_scale_m_per_saved_unit=scale,
                  image_resized=False, depth_range_filtered=False, input_depth_interpolated=False)
    mesh = trimesh.load(str(args.mesh), force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.vertices) < 4 or len(mesh.faces) < 4:
        raise ValueError("Expected an existing triangle mesh with nonempty faces")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("Mesh has nonfinite coordinates")
    mesh = mesh.copy()
    mesh_scale = 1.0 if args.mesh_units == "m" else 0.001
    mesh.apply_scale(mesh_scale)
    extents_axis = np.asarray(mesh.extents, dtype=np.float64)
    if not np.isfinite(extents_axis).all() or np.any(extents_axis <= 1e-6):
        raise ValueError("Metric mesh is degenerate")
    to_origin, extents = trimesh.bounds.oriented_bounds(mesh)
    bbox = np.stack([-extents / 2, extents / 2]).reshape(2, 3)
    np.savetxt(str(output / "mesh_metric_to_obb.txt"), to_origin, fmt="%.12g")
    report["mesh_coordinates"] = {
        "declared_source_unit": args.mesh_units, "source_vertex_to_meter_scale": mesh_scale,
        "metric_axis_aligned_extents_m": extents_axis.tolist(),
        "metric_obb_extents_m": np.asarray(extents).tolist(),
        "vertices": len(mesh.vertices), "faces": len(mesh.faces),
        "pose_definition": "T_camera_from_original_mesh_metric; source axes/origin retained, mesh coordinates expressed in meters",
        "point_equation": "p_camera_m = R @ (source_vertex * source_vertex_to_meter_scale) + t_m",
        "obb_pose_definition": "T_camera_from_obb = T_camera_from_original_mesh_metric @ inverse(T_obb_from_mesh_metric)",
        "obb_frame_is_for_display_only": True,
        "physical_dimensions_measured_by_this_script": False,
        "mesh_metric_to_obb_file": file_info(output / "mesh_metric_to_obb.txt"),
    }
    # Validate all five source images before any model/GPU constructor runs.
    for frame in frames:
        load_inputs(args.scene, args.mask_dir, metadata, frame, np, cv2)
    report["frames"] = frames
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch CUDA is unavailable")
    set_logging_format()
    set_seed(0)
    report.update(gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
                  torch_cuda=torch.version.cuda)
    scorer = ScorePredictor()
    refiner = PoseRefinePredictor()
    report["weights"] = {"scorer": loaded_weight_info(scorer, args.repo),
                         "refiner": loaded_weight_info(refiner, args.repo)}
    context = dr.RasterizeCudaContext()
    estimator = FoundationPose(model_pts=mesh.vertices, model_normals=mesh.vertex_normals,
                               mesh=mesh, scorer=scorer, refiner=refiner, glctx=context,
                               debug=0, debug_dir=str(output / "internal"))
    write_report(report, output / "report.json")
    failures = []
    for frame in frames:
        started = time.monotonic()
        try:
            color, depth, mask = load_inputs(args.scene, args.mask_dir, metadata, frame, np, cv2)
            # register() normally overwrites state; clearing it also detects its
            # insufficient-filtered-depth early return instead of reusing a past pose.
            estimator.pose_last = None
            pose = estimator.register(K=K, rgb=color, depth=depth, ob_mask=mask,
                                      iteration=args.register_iterations)
            torch.cuda.synchronize()
            if estimator.pose_last is None:
                raise RuntimeError("register exited before neural inference; filtered masked depth may be insufficient")
            pose, validation = inspect_pose(pose, np)
            frame["validation"] = validation
            if not validation["passed"] or pose[2, 3] <= 0:
                raise RuntimeError("Returned pose is not a valid object-to-camera rigid transform in front of camera")
            pose_path = output / "poses" / (frame["id"] + ".txt")
            np.savetxt(str(pose_path), pose, fmt="%.12g")
            obb_pose = pose @ np.linalg.inv(to_origin)
            obb_path = output / "obb_display_poses" / (frame["id"] + ".txt")
            np.savetxt(str(obb_path), obb_pose, fmt="%.12g")
            visualization = draw_posed_3d_box(K, img=color.copy(), ob_in_cam=obb_pose, bbox=bbox)
            axis_length = float(max(0.005, min(0.1, np.max(extents) * 0.5)))
            visualization = draw_xyz_axis(visualization, ob_in_cam=obb_pose, K=K,
                                          scale=axis_length, thickness=2, transparency=0,
                                          is_input_rgb=True)
            visual_path = output / "visualizations" / (frame["id"] + ".png")
            imageio.imwrite(str(visual_path), visualization)
            frame.update(status="inference_completed_requires_visual_review", passed=True,
                         pose=file_info(pose_path), obb_display_pose=file_info(obb_path),
                         visualization=file_info(visual_path), display_axis_length_m=axis_length,
                         neural_registration_executed=True, previous_frame_pose_used=False,
                         pose_is_ground_truth=False, accuracy_validated=False)
        except Exception as error:
            frame.update(status="failed", passed=False,
                         error={"type": type(error).__name__, "message": str(error),
                                "traceback": traceback.format_exc()})
            failures.append(frame["id"])
            traceback.print_exc()
        finally:
            frame["inference_seconds_including_output"] = time.monotonic() - started
            write_report(report, output / "report.json")
        print(json.dumps({"frame": frame["id"], "passed": frame.get("passed", False),
                          "operation": "independent_register"}), flush=True)
    # Detect source/model replacements occurring during this run.
    for information in (report["source_mesh"], report["qa"], report["mask_generation_report"]):
        checked_info(Path(information["path"]), information["sha256"])
    for information in report["capture_sources"].values():
        checked_info(Path(information["path"]), information["sha256"])
    for information in report["upstream_sources"].values():
        checked_info(Path(information["path"]), information["sha256"])
    for predictor in report["weights"].values():
        for name in ("checkpoint", "config"):
            information = predictor[name]
            checked_info(Path(information["path"]), information["sha256"])
    for frame in frames:
        for information in frame["inputs"].values():
            checked_info(Path(information["path"]), information["sha256"])
    report.update(completed_frames=sum(frame.get("passed", False) for frame in frames),
                  failed_frame_ids=failures, passed=not failures and len(frames) > 0,
                  status="inference_completed_requires_visual_review" if not failures else "failed")


def main():
    args = parse_args()
    for name in ("repo", "scene", "mask_dir", "qa", "mesh", "output"):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    report = {"schema_version": 1, "started_at_utc": utc_now(), "passed": False,
              "status": "validating_inputs", "repo": str(args.repo), "scene": str(args.scene),
              "mask_directory": str(args.mask_dir), "output": str(args.output),
              "register_iterations": args.register_iterations, "frames": [],
              "mode": "independent_registration_per_accepted_held_out_photo",
              "tracking_executed": False, "reconstruction_executed": False,
              "pose_network_training_executed": False, "ground_truth_available": False,
              "pose_accuracy_evaluated": False, "gt_metrics_computed": False,
              "manual_projection_review_required": True,
              "upstream_add_error_prints_are_metrics": False,
              "limitations": [
                  "passed means neural inference returned numerically valid poses, not accurate poses.",
                  "Masks guide each initial pose; this does not test automatic object detection/segmentation.",
                  "Five accepted images do not establish broad orientation or upright generalization.",
                  "Mesh dimensions and unit declaration require independent reconstruction/physical verification.",
                  "Raw nonzero depth may be wrong; upstream register performs erosion and bilateral filtering.",
                  "Upstream add_errs=-1 output is a placeholder, not ADD or a GT comparison.",
              ]}
    output_created = False
    started = time.monotonic()
    try:
        if os.path.lexists(str(args.output)):
            raise ValueError("Output already exists; choose a new directory")
        for source in (args.repo, args.scene, args.mask_dir):
            if args.output == source or source in args.output.parents or args.output in source.parents:
                raise ValueError("Output must not contain or be inside a source directory")
        for source in (args.qa, args.mesh):
            if args.output == source or args.output in source.parents:
                raise ValueError("Output would contain an input file")
        args.output.mkdir(parents=True, exist_ok=False)
        output_created = True
        for folder in ("poses", "obb_display_poses", "visualizations"):
            (args.output / folder).mkdir()
        report["script"] = file_info(Path(__file__))
        report["shared_verification_helpers"] = file_info(Path(__file__).parent / "verify_demo.py")
        run(args, report)
    except (Exception, KeyboardInterrupt) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        report.update(status="interrupted" if interrupted else "failed", passed=False,
                      error={"type": type(error).__name__, "message": str(error),
                             "traceback": traceback.format_exc()})
        traceback.print_exc()
    finally:
        report.update(ended_at_utc=utc_now(), elapsed_seconds=time.monotonic() - started)
        if output_created:
            write_report(report, args.output / "report.json")
    print(json.dumps({"passed": report["passed"], "status": report["status"],
                      "completed_frames": report.get("completed_frames", 0),
                      "report": str(args.output / "report.json") if output_created else None,
                      "pose_accuracy_validated": False}), flush=True)
    return 0 if report["passed"] else (130 if report["status"] == "interrupted" else 1)


if __name__ == "__main__":
    sys.exit(main())
