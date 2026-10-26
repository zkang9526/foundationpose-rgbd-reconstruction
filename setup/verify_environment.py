#!/usr/bin/env python3
"""Exercise FoundationPose's GPU dependencies without weights or demo data.

Run from the FoundationPose checkout, or pass --repo /path/to/FoundationPose.
Compatible with Python 3.8 and the original torch 2.0 / NumPy 1.x image.
"""

from __future__ import annotations

import argparse
import datetime
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command_metadata(argv, cwd):
    if not shutil.which(argv[0]):
        return {"available": False}
    try:
        result = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=15, check=False,
        )
        return {
            "available": True,
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[-8000:],
            "stderr": result.stderr.strip()[-2000:],
        }
    except Exception as exc:
        return {"available": True, "error": "{}: {}".format(type(exc).__name__, exc)}


def package_versions():
    versions = {}
    for name in (
        "numpy", "torch", "torchvision", "torchaudio", "pytorch3d",
        "nvdiffrast", "warp-lang", "open3d", "trimesh", "opencv-python",
        "opencv-contrib-python", "scipy", "kornia", "omegaconf", "kaolin",
        "pybind11", "h5py",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, help="Write the complete JSON report here.")
    args = parser.parse_args()
    repo = args.repo.expanduser().resolve()
    output = args.output.expanduser().resolve() if args.output else None

    report = {
        "schema_version": 1,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "model-based environment; no model inference or reconstruction",
        "inference_validated": False,
        "runtime": {
            "repository": str(repo),
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "packages": package_versions(),
            "environment": {
                key: os.environ.get(key)
                for key in (
                    "CONDA_PREFIX", "CUDA_HOME", "CUDA_VISIBLE_DEVICES",
                    "TORCH_CUDA_ARCH_LIST", "NVIDIA_VISIBLE_DEVICES",
                    "NVIDIA_DRIVER_CAPABILITIES",
                )
            },
        },
        "checks": [],
        "warnings": [],
    }

    def check(name, operation, prerequisite=None):
        start = time.monotonic()
        entry = {"name": name}
        if prerequisite is not None and prerequisite.get("status") != "passed":
            entry.update(status="skipped", reason="Prerequisite failed: " + prerequisite["name"])
        else:
            try:
                details = operation()
                entry.update(status="passed", details=details or {})
            except Exception as exc:
                entry.update(
                    status="failed",
                    error="{}: {}".format(type(exc).__name__, exc),
                    traceback=traceback.format_exc(),
                )
        entry["elapsed_seconds"] = round(time.monotonic() - start, 3)
        report["checks"].append(entry)
        print("[{}] {}".format(entry["status"].upper(), name), flush=True)
        if "error" in entry:
            print("  " + entry["error"], flush=True)
        return entry

    def repository_check():
        require(repo.is_dir(), "Repository directory does not exist: " + str(repo))
        require((repo / "estimater.py").is_file(), "Missing estimater.py; pass --repo to the official checkout.")
        os.chdir(str(repo))
        sys.path.insert(0, str(repo))
        sys.path.insert(0, str(repo / "mycpp" / "build"))
        return {"mycpp_files": [p.name for p in (repo / "mycpp" / "build").glob("mycpp*.so")]}

    repository = check("repository", repository_check)
    if repo.is_dir():
        report["runtime"]["git_commit"] = command_metadata(["git", "rev-parse", "HEAD"], repo)
        report["runtime"]["nvcc"] = command_metadata(["nvcc", "--version"], repo)
        report["runtime"]["nvidia_smi"] = command_metadata(
            ["nvidia-smi", "--query-gpu=index,name,driver_version,memory.total", "--format=csv,noheader"], repo,
        )

    def torch_cuda_check():
        import torch
        require(torch.cuda.is_available(), "torch.cuda.is_available() is False")
        torch.cuda.set_device(0)
        props = torch.cuda.get_device_properties(0)
        report["runtime"]["torch_cuda"] = {
            "torch": str(torch.__version__),
            "cuda_build": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "device_count": torch.cuda.device_count(),
            "device_name": props.name,
            "compute_capability": [props.major, props.minor],
            "total_memory_bytes": props.total_memory,
        }
        identity = torch.eye(8, device="cuda", dtype=torch.float32)
        require(torch.equal(identity @ identity, identity), "CUDA matrix multiplication returned an unexpected result")
        torch.cuda.synchronize()
        return report["runtime"]["torch_cuda"]

    cuda = check("torch_cuda_execution", torch_cuda_check)

    def numpy_bridge_check():
        import numpy as np
        import torch
        source = np.arange(12, dtype=np.float32).reshape(3, 4)
        result = torch.from_numpy(source).cuda().cpu().numpy()
        require(np.array_equal(source, result), "NumPy / PyTorch conversion changed data")
        return {"numpy": str(np.__version__), "roundtrip": "numpy -> torch -> CUDA -> numpy"}

    check("numpy_torch_cuda_roundtrip", numpy_bridge_check, cuda)

    def nvdiffrast_check():
        import torch
        import nvdiffrast.torch as dr
        context = dr.RasterizeCudaContext()
        vertices = torch.tensor(
            [[[-0.8, -0.8, 0.0, 1.0], [0.8, -0.8, 0.0, 1.0], [0.0, 0.8, 0.0, 1.0]]],
            device="cuda", dtype=torch.float32,
        )
        faces = torch.tensor([[0, 1, 2]], device="cuda", dtype=torch.int32)
        raster, _ = dr.rasterize(context, vertices, faces, resolution=[32, 32])
        colors = torch.tensor([[[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]], device="cuda", dtype=torch.float32)
        image, _ = dr.interpolate(colors, raster, faces)
        torch.cuda.synchronize()
        pixels = int((raster[..., 3] > 0).sum().item())
        require(tuple(raster.shape) == (1, 32, 32, 4), "Unexpected raster shape")
        require(pixels > 0, "CUDA rasterizer produced no triangle pixels")
        require(bool(torch.isfinite(image).all().item()), "Interpolation returned non-finite colors")
        require(float(image.sum().item()) > 0, "Interpolation produced an empty image")
        return {"covered_pixels": pixels, "raster_shape": list(raster.shape), "backend": "CUDA"}

    check("nvdiffrast_cuda_rasterize_interpolate", nvdiffrast_check, cuda)

    def pytorch3d_check():
        import torch
        from pytorch3d.ops import knn_points
        points = torch.tensor([[[0., 0., 0.], [1., 0., 0.], [0., 2., 0.]]], device="cuda", dtype=torch.float32)
        result = knn_points(points, points, K=1)
        torch.cuda.synchronize()
        require(result.dists.is_cuda, "PyTorch3D KNN did not return CUDA tensors")
        require(bool(torch.isfinite(result.dists).all().item()), "KNN returned non-finite distances")
        require(torch.allclose(result.dists, torch.zeros_like(result.dists)), "Self-nearest-neighbor distances are not zero")
        require(torch.equal(result.idx[0, :, 0], torch.arange(3, device="cuda")), "Unexpected self-nearest-neighbor indices")
        return {"distance_shape": list(result.dists.shape), "backend": "CUDA"}

    check("pytorch3d_cuda_knn", pytorch3d_check, cuda)

    def mycpp_check():
        import numpy as np
        import mycpp
        identity = np.eye(4, dtype=np.float32)
        candidates = np.stack([identity, identity])
        clusters = np.asarray(mycpp.cluster_poses(30.0, 99999.0, candidates, identity[None]))
        require(clusters.shape == (1, 4, 4), "Duplicate identity poses did not form one cluster")
        require(np.allclose(clusters[0], identity), "mycpp changed the identity pose")
        return {"module": str(mycpp.__file__), "cluster_count": int(len(clusters))}

    check("mycpp_cluster_poses", mycpp_check, repository)

    def estimater_check():
        module = importlib.import_module("estimater")
        require(callable(getattr(module, "FoundationPose", None)), "Missing FoundationPose class")
        require(callable(getattr(module, "ScorePredictor", None)), "Missing ScorePredictor class")
        require(callable(getattr(module, "PoseRefinePredictor", None)), "Missing PoseRefinePredictor class")
        return {"module": str(module.__file__)}

    check("estimater_import", estimater_check, repository)

    def warp_depth_check():
        import numpy as np
        import torch
        import Utils
        require(getattr(Utils, "wp", None) is not None, "Utils could not initialize Warp")
        require(callable(getattr(Utils, "erode_depth", None)), "Missing Utils.erode_depth")
        require(callable(getattr(Utils, "bilateral_filter_depth", None)), "Missing Utils.bilateral_filter_depth")
        depth = np.ones((32, 32), dtype=np.float32)
        eroded = Utils.erode_depth(depth, radius=2, device="cuda")
        filtered = Utils.bilateral_filter_depth(eroded, radius=2, device="cuda")
        torch.cuda.synchronize()
        for label, result in (("erode_depth", eroded), ("bilateral_filter_depth", filtered)):
            require(isinstance(result, np.ndarray), label + " did not preserve the NumPy input interface")
            require(result.shape == depth.shape, label + " changed the depth shape")
            require(np.isfinite(result).all(), label + " returned non-finite depth")
            require(np.allclose(result, depth, atol=1e-5), label + " changed a constant 1-meter depth plane")
        return {"input_depth_m": 1.0, "shape": list(depth.shape), "backend": "Warp CUDA"}

    check("warp_depth_kernels", warp_depth_check, cuda)

    report["assets"] = {}
    for label, stamp in (("scorer", "2024-01-11-20-02-45"), ("refiner", "2023-10-28-18-33-37")):
        paths = [repo / "weights" / stamp / name for name in ("model_best.pth", "config.yml")]
        missing = [str(path) for path in paths if not path.is_file()]
        report["assets"][label] = {"present": not missing, "missing": missing}
        if missing:
            report["warnings"].append("{} weights are incomplete; inference was not tested.".format(label))
    demo_mesh = repo / "demo_data" / "mustard0" / "mesh" / "textured_simple.obj"
    report["assets"]["default_demo_mesh"] = {"path": str(demo_mesh), "present": demo_mesh.is_file()}
    if not demo_mesh.is_file():
        report["warnings"].append("Default demo data are absent; environment checks do not require them.")

    report["passed"] = all(entry["status"] == "passed" for entry in report["checks"])
    report["summary"] = {
        status: sum(entry["status"] == status for entry in report["checks"])
        for status in ("passed", "failed", "skipped")
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("JSON report: " + str(output), flush=True)
    for warning in report["warnings"]:
        print("[WARNING] " + warning, flush=True)
    print("Environment verification: " + ("PASSED" if report["passed"] else "FAILED"), flush=True)
    print(json.dumps(report["summary"], sort_keys=True), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
