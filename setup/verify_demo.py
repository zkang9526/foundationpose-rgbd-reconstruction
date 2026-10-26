#!/usr/bin/env python3
"""Run FoundationPose's real model-based demo for a few frames without a GUI."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="FoundationPose checkout (default: current directory)")
    parser.add_argument("--scene", type=Path,
                        help="Ycbineoat scene (default: REPO/demo_data/mustard0)")
    parser.add_argument("--output", type=Path, default=Path("/data/demo_smoke"),
                        help="report, poses and PNG output (default: /data/demo_smoke)")
    parser.add_argument("--frames", type=positive_int, default=3,
                        help="number of consecutive frames to verify (default: 3)")
    return parser.parse_args()


def file_info(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def loaded_weight_info(predictor, repo):
    """Called only after the upstream constructor has loaded its state dict."""
    checkpoint = Path(str(predictor.cfg["ckpt_dir"])).resolve(strict=True)
    expected = (repo / "weights" / predictor.run_name / "model_best.pth").resolve()
    if checkpoint != expected:
        raise RuntimeError("predictor loaded a checkpoint outside the expected checkout")
    parameter = next(predictor.model.parameters())
    if not parameter.is_cuda or predictor.model.training:
        raise RuntimeError("loaded predictor must be in CUDA evaluation mode")
    return {
        "loaded": True,
        "run_name": predictor.run_name,
        "model_class": type(predictor.model).__name__,
        "device": str(parameter.device),
        "parameter_count": sum(p.numel() for p in predictor.model.parameters()),
        "checkpoint": file_info(checkpoint),
        "config": file_info(checkpoint.parent / "config.yml"),
    }


def inspect_pose(pose, np):
    pose = np.asarray(pose, dtype=np.float64)
    result = {"shape": list(pose.shape), "finite": bool(np.isfinite(pose).all())}
    if pose.shape != (4, 4) or not result["finite"]:
        result["passed"] = False
        return pose, result
    rotation = pose[:3, :3]
    with np.errstate(over="ignore", invalid="ignore"):
        orthogonality = float(np.linalg.norm(rotation.T @ rotation - np.eye(3)))
        determinant = float(np.linalg.det(rotation))
        homogeneous_row = float(np.linalg.norm(pose[3] - [0, 0, 0, 1]))
    result.update({
        "rotation_orthogonality_error": orthogonality if np.isfinite(orthogonality) else None,
        "rotation_determinant": determinant if np.isfinite(determinant) else None,
        "homogeneous_row_error": homogeneous_row if np.isfinite(homogeneous_row) else None,
        "translation": pose[:3, 3].tolist(),
    })
    result["passed"] = bool(
        np.isfinite([orthogonality, determinant, homogeneous_row]).all()
        and orthogonality < 1e-3
        and abs(determinant - 1.0) < 1e-3
        and homogeneous_row < 1e-5
    )
    return pose, result


def write_report(report, path):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(args, report):
    repo = Path(report["repo"])
    scene = Path(report["scene"])
    output = Path(report["output"])
    for filename in ("estimater.py", "datareader.py", "Utils.py"):
        if not (repo / filename).is_file():
            raise FileNotFoundError("missing FoundationPose source: " + str(repo / filename))
    mesh_file = scene / "mesh" / "textured_simple.obj"
    for path in (mesh_file, scene / "cam_K.txt"):
        if not path.is_file():
            raise FileNotFoundError(str(path))
    color_files = sorted((scene / "rgb").glob("*.png"))
    if len(color_files) < args.frames:
        raise RuntimeError(f"requested {args.frames} frames but scene has {len(color_files)}")
    for index, color_file in enumerate(color_files[:args.frames]):
        required = [scene / "depth" / color_file.name]
        if index == 0:
            required.append(scene / "masks" / color_file.name)
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(str(path))

    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    import imageio.v2 as imageio
    import numpy as np
    import torch
    import trimesh
    import nvdiffrast.torch as dr
    import estimater
    from estimater import FoundationPose, PoseRefinePredictor, ScorePredictor
    from datareader import YcbineoatReader
    from Utils import draw_posed_3d_box, draw_xyz_axis, set_logging_format, set_seed

    if Path(estimater.__file__).resolve().parent != repo:
        raise RuntimeError("imported estimater from a different checkout")
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch CUDA is unavailable")
    set_logging_format()
    set_seed(0)
    report["gpu"] = torch.cuda.get_device_name(0)
    report["torch"] = torch.__version__
    report["torch_cuda"] = torch.version.cuda
    report["mesh"] = file_info(mesh_file)
    report["weights"] = {}
    scorer = ScorePredictor()
    report["weights"]["scorer"] = loaded_weight_info(scorer, repo)
    refiner = PoseRefinePredictor()
    report["weights"]["refiner"] = loaded_weight_info(refiner, repo)
    write_report(report, output / "report.json")

    mesh = trimesh.load(str(mesh_file))
    to_origin, extents = trimesh.bounds.oriented_bounds(mesh)
    bbox = np.stack([-extents / 2, extents / 2]).reshape(2, 3)
    context = dr.RasterizeCudaContext()
    estimator = FoundationPose(model_pts=mesh.vertices, model_normals=mesh.vertex_normals,
                               mesh=mesh, scorer=scorer, refiner=refiner, glctx=context,
                               debug=0, debug_dir=str(output / "internal"))
    reader = YcbineoatReader(video_dir=str(scene), shorter_side=None, zfar=np.inf)
    if not np.isfinite(reader.K).all() or abs(np.linalg.det(reader.K)) < 1e-12:
        raise RuntimeError("invalid camera intrinsics")
    report["available_frames"] = len(reader.color_files)
    for index in range(args.frames):
        started = time.monotonic()
        color = reader.get_color(index)
        depth = reader.get_depth(index)
        if not np.isfinite(depth).all() or not (depth >= 0.001).any():
            raise RuntimeError(f"frame {index} has invalid depth")
        if index == 0:
            mask = reader.get_mask(index).astype(bool)
            if np.count_nonzero(mask & (depth >= 0.001)) < 4:
                raise RuntimeError("first frame has insufficient masked depth for registration")
            pose = estimator.register(K=reader.K, rgb=color, depth=depth, ob_mask=mask,
                                      iteration=5)
            if estimator.pose_last is None:
                raise RuntimeError("registration returned without running model inference")
        else:
            pose = estimator.track_one(rgb=color, depth=depth, K=reader.K, iteration=2)
        torch.cuda.synchronize()
        pose, validation = inspect_pose(pose, np)
        frame_id = Path(reader.id_strs[index]).name
        frame = {"index": index, "id": frame_id,
                 "operation": "register" if index == 0 else "track",
                 "inference_seconds": time.monotonic() - started,
                 "validation": validation}
        report["frames"].append(frame)
        write_report(report, output / "report.json")
        if not validation["passed"]:
            raise RuntimeError(f"invalid pose for frame {frame_id}: {validation}")
        pose_file = output / "poses" / (frame_id + ".txt")
        np.savetxt(pose_file, pose)
        center_pose = pose @ np.linalg.inv(to_origin)
        visualization = draw_posed_3d_box(reader.K, img=color, ob_in_cam=center_pose, bbox=bbox)
        visualization = draw_xyz_axis(visualization, ob_in_cam=center_pose, K=reader.K,
                                      scale=0.1, thickness=3, transparency=0, is_input_rgb=True)
        image_file = output / "visualizations" / (frame_id + ".png")
        imageio.imwrite(image_file, visualization)
        frame["pose_file"] = str(pose_file)
        frame["visualization_file"] = str(image_file)
        write_report(report, output / "report.json")
        print(f"Verified frame {index + 1}/{args.frames}: {frame_id}", flush=True)
    report["passed"] = len(report["frames"]) == args.frames


def main():
    args = parse_args()
    repo = args.repo.expanduser().resolve()
    scene = args.scene.expanduser().resolve() if args.scene else repo / "demo_data" / "mustard0"
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "poses").mkdir(exist_ok=True)
    (output / "visualizations").mkdir(exist_ok=True)
    report = {"passed": False, "repo": str(repo), "scene": str(scene),
              "output": str(output), "requested_frames": args.frames, "frames": [],
              "checks": {"rotation_tolerance": 1e-3, "homogeneous_row_tolerance": 1e-5},
              "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    started = time.monotonic()
    try:
        run(args, report)
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error),
                           "traceback": traceback.format_exc()}
        traceback.print_exc()
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        write_report(report, output / "report.json")
    print(json.dumps({"passed": report["passed"], "frames": len(report["frames"]),
                      "report": str(output / "report.json")}, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
