#!/usr/bin/env python3
"""Safely run the pinned BundleSDF entry on one verified reference photo ring.

The official destructive output initialization is replaced only in memory.
This full-ring pilot retains official global refinement; there is no smoke,
frame truncation, training-label creation or held-out test ingestion here.
CLI output is a new wrapper evidence folder, with algorithm output in pipeline/.
"""

import argparse
import ast
import copy
import datetime
import difflib
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import traceback


EXPECTED_PIN = "cf0610e3636bc42535c996f129161f44beeadc56"
DATA_ROOT = Path("/data")


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
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino) or size != before.st_size:
        raise RuntimeError("Source changed during hashing: {}".format(path))
    sha256 = digest.hexdigest()
    if expected is not None and sha256 != expected:
        raise ValueError("Source SHA256 differs from preparation report: {}".format(path))
    return {"path": str(path), "bytes": size, "sha256": sha256}


def require_hash(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Preparation report lacks a valid SHA256 for " + label)
    return value


def within(path, root):
    return path == root or root in path.parents


def no_links(path, root):
    lexical = Path(os.path.abspath(str(path)))
    if not within(lexical, root):
        raise ValueError("Path is outside allowed root: {}".format(path))
    current = root
    for part in lexical.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink is refused: {}".format(current))
        if not within(current.resolve(strict=False), root):
            raise ValueError("Path resolves outside allowed root: {}".format(current))
    return lexical


def write_report(report, path):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("/workspace/BundleSDF"))
    parser.add_argument("--video-dir", type=Path, required=True,
                        help="One prepared complete reference ring; parent/report.json is required")
    parser.add_argument("--output", type=Path, required=True,
                        help="New /data/derived/cup_reconstruction_* folder; official output uses pipeline/")
    parser.add_argument("--debug-level", type=int, choices=(0, 1, 2, 3), default=2)
    parser.add_argument("--expected-frames", type=int, choices=(36, 72), default=36,
                        help="validated complete ring size; keeps existing 36-frame commands unchanged")
    return parser.parse_args()


def validate_paths(args):
    if os.name != "posix":
        raise ValueError("This wrapper runs only in the Ubuntu BundleSDF container")
    data = DATA_ROOT.resolve(strict=True)
    # Check lexical paths before resolution so an existing link cannot be hidden.
    video = no_links(args.video_dir, data)
    output = no_links(args.output, data)
    if not video.is_dir():
        raise ValueError("Prepared video directory does not exist")
    if video.parent.parent != data / "derived":
        raise ValueError("Input must be one scene directly inside a prepared /data/derived/<batch> directory")
    if output.parent != data / "derived" or not re.fullmatch(r"cup_reconstruction_[A-Za-z0-9._-]+", output.name):
        raise ValueError("Output must be a new /data/derived/cup_reconstruction_* directory")
    if os.path.lexists(str(output)):
        raise ValueError("Output already exists; choose a new directory")
    if within(video, output) or within(output, video) or output == video.parent:
        raise ValueError("Input/output containment is refused")
    repo = args.repo.resolve(strict=True)
    if not repo.is_dir():
        raise ValueError("BundleSDF checkout does not exist")
    args.repo, args.video_dir, args.output = repo, video.resolve(), output


def validate_inputs(args, report):
    preparation_path = no_links(args.video_dir.parent / "report.json", DATA_ROOT)
    preparation = read_json(preparation_path)
    report["preparation_report"] = file_info(preparation_path)
    if preparation.get("passed") is not True or preparation.get("status") != "complete":
        raise ValueError("Preparation report has not completed successfully")
    suffix = tuple(args.video_dir.parts[-3:])
    candidates = [item for item in preparation.get("sequences", [])
                  if tuple(PurePosixPath(str(item.get("output_scene", "")).replace("\\", "/")).parts[-3:]) == suffix]
    if len(candidates) != 1:
        raise ValueError("Preparation report does not uniquely identify the single input scene")
    sequence = candidates[0]
    role = str(sequence.get("role", ""))
    if "test" in role.casefold() or "held" in role.casefold():
        raise ValueError("Held-out tests must not enter reconstruction")
    frames = sequence.get("frames", [])
    if len(frames) != args.expected_frames:
        raise ValueError("Full pilot requires exactly {} prepared reference frames".format(args.expected_frames))
    names = [item.get("frame") for item in frames]
    expected_names = ["{:06d}.png".format(index) for index in range(args.expected_frames)]
    if names != expected_names:
        raise ValueError("Reference ring must contain the recorded ordered complete PNG sequence")
    report.update(input_role=role, source_scene=sequence.get("source_scene"),
                  source_masks=sequence.get("source_masks"), frame_count=args.expected_frames,
                  preparation_depth_range_mm=preparation.get("depth_range_mm_inclusive"),
                  input_frames=[])
    for folder, hash_key in (("rgb", "rgb_sha256"), ("depth", "filtered_depth_sha256"),
                             ("masks", "mask_sha256")):
        directory = no_links(args.video_dir / folder, DATA_ROOT)
        if sorted(path.name for path in directory.iterdir()) != expected_names:
            raise ValueError("Input {} directory differs from preparation frame list".format(folder))
        for item in frames:
            path = no_links(directory / item["frame"], DATA_ROOT)
            require_hash(item.get(hash_key), folder + "/" + item["frame"])
            information = file_info(path, item[hash_key])
            report["input_frames"].append({"kind": folder, "frame": item["frame"], **information})
    report["input_metadata"] = {}
    for filename in ("cam_K.txt", "K.txt", "depth_scale.txt", "source_capture_metadata.json"):
        path = no_links(args.video_dir / filename, DATA_ROOT)
        report["input_metadata"][filename] = file_info(path)
    metadata = read_json(args.video_dir / "source_capture_metadata.json")
    saved = metadata.get("saved_depth", {})
    saved_scale = float(saved.get("scale_meters_per_saved_unit", -1))
    scale = float((args.video_dir / "depth_scale.txt").read_text(encoding="utf-8"))
    if (metadata.get("passed") is not True or metadata.get("status") != "complete"
            or metadata.get("requested", {}).get("align_to") != "color"
            or saved.get("unit") != "millimeter" or saved.get("dtype") != "uint16"
            or saved.get("invalid_value") != 0 or not math.isfinite(saved_scale)
            or abs(saved_scale - 0.001) > 1e-12 or not math.isfinite(scale)
            or abs(scale - 0.001) > 1e-12):
        raise ValueError("Prepared input must retain aligned uint16 millimeter depth semantics")
    report["depth_scale_meters_per_saved_unit"] = scale
    return metadata


def patched_entry(source, filename, report):
    tree = ast.parse(source, filename=str(filename))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "run_one_video"]
    if len(functions) != 1:
        raise ValueError("Expected exactly one official run_one_video function")
    function = copy.deepcopy(functions[0])
    expected = ast.parse("os.system(f'rm -rf {out_folder} && mkdir -p {out_folder}')").body[0]
    matches = [index for index, node in enumerate(function.body)
               if ast.dump(node, include_attributes=False) == ast.dump(expected, include_attributes=False)]
    if matches != [1]:
        raise ValueError("Official destructive output statement differs from the audited second statement")
    original_node = function.body[1]
    before_ast = ast.dump(function, include_attributes=False)
    replacement = ast.parse("_cup_safe_create_pipeline_output(out_folder)").body[0]
    ast.copy_location(replacement, original_node)
    function.body[1] = replacement
    for node in ast.walk(function):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "os"
                and node.func.attr == "system"):
            raise ValueError("Unexpected remaining os.system call in run_one_video")
    final = function.body[-1]
    if (not isinstance(final, ast.Expr) or not isinstance(final.value, ast.Call)
            or not isinstance(final.value.func, ast.Name)
            or final.value.func.id != "run_one_video_global_nerf"):
        raise ValueError("Official full-run global refinement call differs from audited entry")
    after_ast = ast.dump(function, include_attributes=False)
    lines_before = source.splitlines(keepends=True)
    lines_after = list(lines_before)
    indent = lines_before[original_node.lineno - 1][:original_node.col_offset]
    if original_node.end_lineno != original_node.lineno:
        raise ValueError("Expected a single-line audited destructive initialization")
    lines_after[original_node.lineno - 1] = indent + "_cup_safe_create_pipeline_output(out_folder)\n"
    patch = {"function": "run_one_video", "removed_statement": ast.get_source_segment(source, original_node),
             "replacement_statement": "_cup_safe_create_pipeline_output(out_folder)",
             "line": original_node.lineno, "upstream_file_modified": False,
             "original_function_ast_sha256": hashlib.sha256(before_ast.encode("utf-8")).hexdigest(),
             "patched_function_ast_sha256": hashlib.sha256(after_ast.encode("utf-8")).hexdigest(),
             "only_destructive_initialization_replaced": True,
             "global_refinement_preserved": True,
             "source_diff": "".join(difflib.unified_diff(lines_before, lines_after,
                                                           fromfile="official/run_custom.py",
                                                           tofile="in_memory/run_custom.py"))}
    report["in_memory_ast_patch"] = patch
    args_output = Path(report["output"])
    (args_output / "entry_initialization_patch.diff").write_text(patch["source_diff"], encoding="utf-8")
    module_ast = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module_ast)
    return compile(module_ast, str(filename) + "::cup_safe_entry", "exec")


def validate_arrays(args, metadata, report, np, cv2):
    K = np.loadtxt(str(args.video_dir / "cam_K.txt")).reshape(3, 3)
    alternate = np.loadtxt(str(args.video_dir / "K.txt")).reshape(3, 3)
    intrinsics = metadata["color_intrinsics"]
    aligned = metadata["aligned_depth_intrinsics"]
    width, height = int(intrinsics["width"]), int(intrinsics["height"])
    if min(width, height) != 480:
        raise ValueError("Official shorter_side=480 must leave native dimensions unchanged")
    for value in (intrinsics, aligned):
        matrix = np.array([[value["fx"], 0, value["cx"]],
                           [0, value["fy"], value["cy"]], [0, 0, 1]], dtype=np.float64)
        coefficients = np.asarray(value.get("distortion_coefficients", []), dtype=np.float64)
        if (not np.isfinite(K).all() or not np.allclose(K, matrix, rtol=0, atol=1e-6)
                or int(value["width"]) != width or int(value["height"]) != height
                or coefficients.size != 5 or not np.isfinite(coefficients).all()
                or np.any(np.abs(coefficients) > 1e-12)):
            raise ValueError("Intrinsics/aligned dimensions or pinhole distortion are inconsistent")
    if K[0, 0] <= 0 or K[1, 1] <= 0 or not np.allclose(K, alternate, rtol=0, atol=1e-7):
        raise ValueError("Invalid or disagreeing camera matrices")
    for index in range(args.expected_frames):
        filename = "{:06d}.png".format(index)
        color = cv2.imread(str(args.video_dir / "rgb" / filename), cv2.IMREAD_UNCHANGED)
        depth = cv2.imread(str(args.video_dir / "depth" / filename), cv2.IMREAD_UNCHANGED)
        mask = cv2.imread(str(args.video_dir / "masks" / filename), cv2.IMREAD_UNCHANGED)
        if color is None or color.dtype != np.uint8 or color.shape != (height, width, 3):
            raise ValueError("Unexpected RGB format in " + filename)
        if depth is None or depth.dtype != np.uint16 or depth.shape != (height, width):
            raise ValueError("Unexpected uint16 millimeter depth format in " + filename)
        if (mask is None or mask.dtype != np.uint8 or mask.shape != depth.shape
                or not set(np.unique(mask).tolist()).issubset({0, 255})
                or np.count_nonzero((mask > 0) & (depth > 0)) < 4):
            raise ValueError("Invalid binary mask or insufficient prepared object depth in " + filename)
    report.update(camera_matrix=K.tolist(), native_image_shape=[height, width],
                  native_intrinsics_preserved=True, official_color_order="OpenCV BGR",
                  all_input_arrays_validated=True, validated_input_arrays=args.expected_frames)


def run(args, report):
    metadata = validate_inputs(args, report)
    upstream = ("run_custom.py", "BundleTrack/scripts/data_reader.py",
                "BundleTrack/config_ho3d.yml", "config.yml", "bundlesdf.py",
                "BundleTrack/LoFTR/weights/outdoor_ds.ckpt")
    report["upstream_sources_and_assets"] = {name: file_info(args.repo / name) for name in upstream}
    revision = subprocess.run(["git", "-c", "safe.directory=" + str(args.repo),
                              "-C", str(args.repo), "rev-parse", "HEAD"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, check=False)
    report["git_identity_check"] = {"exit_code": revision.returncode,
                                    "stdout": revision.stdout.decode("utf-8", errors="replace"),
                                    "stderr": revision.stderr.decode("utf-8", errors="replace"),
                                    "safe_directory_scope": str(args.repo),
                                    "global_git_configuration_modified": False}
    if revision.returncode != 0 or revision.stdout.decode("ascii").strip() != EXPECTED_PIN:
        raise ValueError("BundleSDF checkout differs from the audited official commit")
    report["repo_commit"] = EXPECTED_PIN
    entry_path = args.repo / "run_custom.py"
    source = entry_path.read_text(encoding="utf-8")
    patched_code = patched_entry(source, entry_path, report)
    write_report(report, args.output / "report.json")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, str(args.repo))
    os.chdir(str(args.repo))
    import cv2
    import numpy as np
    validate_arrays(args, metadata, report, np, cv2)
    specification = importlib.util.spec_from_file_location("cup_bundlesdf_official_entry", str(entry_path))
    if specification is None or specification.loader is None:
        raise RuntimeError("Cannot load the official BundleSDF entry module")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    if Path(module.__file__).resolve() != entry_path.resolve():
        raise RuntimeError("Loaded a different BundleSDF entry")
    pipeline = args.output / "pipeline"

    def safe_create_pipeline_output(requested):
        target = no_links(Path(requested), DATA_ROOT)
        if target != pipeline or target.parent != args.output:
            raise ValueError("Official entry requested an unauthorized output directory")
        if os.path.lexists(str(target)):
            raise ValueError("Official pipeline output already exists")
        target.mkdir(parents=False, exist_ok=False)
        report["pipeline_output_created_safely"] = True
        write_report(report, args.output / "report.json")

    module._cup_safe_create_pipeline_output = safe_create_pipeline_output
    module.args = argparse.Namespace(mode="run_video", video_dir=str(args.video_dir),
                                     out_folder=str(pipeline), use_segmenter=0, use_gui=0,
                                     stride=1, debug_level=args.debug_level)
    exec(patched_code, module.__dict__)
    report["official_parameters"] = vars(module.args).copy()
    reader_module = sys.modules.get(module.YcbineoatReader.__module__)
    if reader_module is None or not getattr(reader_module, "__file__", None):
        raise RuntimeError("Cannot establish official RGB-D reader source")
    actual_reader = Path(reader_module.__file__).resolve()
    expected_reader = (args.repo / "BundleTrack/scripts/data_reader.py").resolve()
    if actual_reader != expected_reader:
        raise RuntimeError("Official entry imported an unexpected RGB-D reader: {}".format(actual_reader))
    report["actual_reader_source"] = file_info(actual_reader)
    reader = module.YcbineoatReader(video_dir=str(args.video_dir), shorter_side=480)
    if (len(reader.color_files) != args.expected_frames or list(reader.id_strs) != ["{:06d}".format(i) for i in range(args.expected_frames)]
            or not np.allclose(reader.K, np.asarray(report["camera_matrix"]), rtol=0, atol=1e-6)):
        raise ValueError("Official reader changed the frame list or native camera matrix")
    first_raw = cv2.imread(str(args.video_dir / "depth/000000.png"), cv2.IMREAD_UNCHANGED)
    first_metric = reader.get_depth(0)
    positive = first_metric > 0
    if (first_metric.shape != first_raw.shape or not np.any(positive)
            or not np.allclose(first_metric[positive], first_raw[positive] / 1000.0, rtol=0, atol=1e-7)):
        raise ValueError("Official reader depth does not match saved millimeters converted to meters")
    for information in report["upstream_sources_and_assets"].values():
        file_info(Path(information["path"]), information["sha256"])
    report["status"] = "running_official_full_ring_and_global_refinement"
    report["official_entry_invoked"] = True
    write_report(report, args.output / "report.json")
    module.run_one_video(video_dir=str(args.video_dir), out_folder=str(pipeline),
                         use_segmenter=False, use_gui=False)
    report["official_entry_returned"] = True
    for information in report["input_frames"] + list(report["input_metadata"].values()):
        file_info(Path(information["path"]), information["sha256"])
    for information in report["upstream_sources_and_assets"].values():
        file_info(Path(information["path"]), information["sha256"])
    report["output_artifacts"] = []
    for path in sorted(pipeline.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".obj", ".ply", ".yml", ".yaml"):
            no_links(path, DATA_ROOT)
            report["output_artifacts"].append(file_info(path))
    pose_dir = pipeline / "ob_in_cam"
    poses = sorted(pose_dir.glob("*.txt")) if pose_dir.is_dir() else []
    report["estimated_pose_files"] = [file_info(path) for path in poses]
    report["metric_textured_mesh_candidates"] = [
        information for information in report["output_artifacts"]
        if Path(information["path"]).name == "textured_mesh.obj"
    ]
    report["normalized_meshes_are_not_metric_inference_inputs"] = True
    if not report["metric_textured_mesh_candidates"]:
        raise RuntimeError("Official entry returned without an exported textured_mesh.obj; inspect retained artifacts")
    report.update(passed=True, status="official_entry_completed_requires_reconstruction_review",
                  mesh_quality_validated=False, estimated_poses_are_ground_truth=False)


def main():
    args = parse_args()
    report = {"schema_version": 1, "passed": False, "status": "validating",
              "started_at_utc": utc_now(), "output": str(args.output),
              "mode": "full_{}_frame_single_reference_ring_with_global_refinement".format(args.expected_frames),
              "frame_truncation": False, "global_refinement_skipped": False,
              "planned_angles_used": False, "known_camera_extrinsics_used": False,
              "pose_ground_truth_available": False, "held_out_tests_used": False,
              "official_source_modified": False, "network_or_ssh_used": False,
              "limitations": [
                  "This pilot estimates reference poses and geometry; it does not provide GT labels.",
                  "Single-side reference ring only; top ring is not merged using assumed angles.",
                  "Passing means the official entry returned, not that its mesh or tracking is correct.",
                  "Original RGB-D and failed attempts are preserved; algorithms use derived range-filtered depth.",
                  "Inspect handle geometry, support contamination, physical scale and all pose projections before inference.",
              ]}
    output_created = False
    started = time.monotonic()
    try:
        validate_paths(args)
        args.output.mkdir(parents=False, exist_ok=False)
        output_created = True
        report.update(output=str(args.output), repo=str(args.repo), video_dir=str(args.video_dir),
                      pipeline_output=str(args.output / "pipeline"), script=file_info(Path(__file__)),
                      ffi_preload=os.environ.get("LD_PRELOAD"))
        write_report(report, args.output / "report.json")
        run(args, report)
    except (Exception, KeyboardInterrupt) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        report.update(passed=False, status="interrupted" if interrupted else "failed",
                      error={"type": type(error).__name__, "message": str(error),
                             "traceback": traceback.format_exc()})
        traceback.print_exc()
    finally:
        report.update(ended_at_utc=utc_now(), elapsed_seconds=time.monotonic() - started)
        if output_created:
            write_report(report, args.output / "report.json")
    print(json.dumps({"passed": report["passed"], "status": report["status"],
                      "report": str(args.output / "report.json") if output_created else None,
                      "pipeline_output": report.get("pipeline_output"),
                      "mesh_quality_validated": False}), flush=True)
    return 0 if report["passed"] else (130 if report["status"] == "interrupted" else 1)


if __name__ == "__main__":
    sys.exit(main())
