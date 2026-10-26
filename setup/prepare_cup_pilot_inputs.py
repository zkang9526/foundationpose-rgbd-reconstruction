#!/usr/bin/env python3
"""Prepare separately traceable, range-filtered RGB-D inputs for a cup pilot."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def imread(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-depth-mm", type=int, default=300)
    parser.add_argument("--max-depth-mm", type=int, default=800)
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    derived = (root / "foundationpose_data/derived").resolve()
    if output == derived or derived not in output.parents or output.exists():
        parser.error("Output must be a new child of foundationpose_data/derived")
    if not (1 <= args.min_depth_mm < args.max_depth_mm <= 65535):
        parser.error("Invalid inclusive millimeter range")
    readiness = read(args.readiness)
    if not readiness.get("reference_masks_ready_for_initial_pilot"):
        parser.error("Reference visual QA is incomplete")
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": 1, "passed": False, "status": "running",
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "method": "Copy accepted RGB silhouettes; raw mask-positive depth within explicit inclusive millimeter bounds retained unchanged, all other derived depth set to zero",
              "depth_range_mm_inclusive": [args.min_depth_mm, args.max_depth_mm],
              "scope": "Exploratory reconstruction input, not calibrated depth correction, validated mesh or ground truth",
              "range_basis": "Observed manually bounded cup body median 468-501 mm; broad 300-800 mm guard removes multi-meter readings without applying unmeasured narrow physical-size assumptions",
              "source_readiness": {"path": str(args.readiness), "sha256": sha(args.readiness)},
              "script_sha256": sha(Path(__file__)),
              "raw_sources_modified": False, "depth_interpolated": False,
              "rgb_masks_remove_depth_holes": False,
              "sequences_require_separate_tracking_or_cross_sequence_registration": True,
              "estimated_poses_available": False,
              "limitations": ["A nonzero value within this window is not proof of correct surface depth.",
                              "Range filtering does not recover missing depth or repair RGB/depth alignment.",
                              "Same-distance support contamination requires mask and mesh inspection.",
                              "Handle depth is weaker than body depth; inspect reconstructed handle.",
                              "No hidden cup interior/contact geometry or 6D pose is created."],
              "sequences": []}
    report_path = output / "report.json"
    try:
        for item in readiness["sequences"]:
            scene, maskdir = root / item["scene"], root / item["mask_directory"]
            generation = read(maskdir / "report.json")
            if sha(maskdir / "report.json") != item["generation_report_sha256"]:
                raise ValueError("Generation report changed")
            if sha(root / item["qa"]) != item["qa_sha256"]:
                raise ValueError("Visual QA changed")
            dest = output / scene.name
            for folder in ("rgb", "depth", "masks"):
                (dest / folder).mkdir(parents=True)
            record = {"role": item["role"], "source_scene": item["scene"],
                      "source_masks": item["mask_directory"],
                      "output_scene": dest.relative_to(root).as_posix(), "frames": []}
            result["sequences"].append(record)
            for source_frame in generation["frames"]:
                name = source_frame["frame"]
                rgbpath, depthpath, maskpath = scene / "rgb" / name, scene / "depth" / name, maskdir / "masks" / name
                for path, key in ((rgbpath, "source_rgb_sha256"), (depthpath, "source_depth_sha256"), (maskpath, "mask_sha256")):
                    if sha(path) != source_frame[key]:
                        raise ValueError("Source changed: " + str(path))
                depth, mask = imread(depthpath), imread(maskpath)
                if depth is None or mask is None or depth.dtype != np.uint16 or depth.shape != mask.shape or depth.ndim != 2:
                    raise ValueError("Unexpected raw depth/mask format")
                target = mask > 0
                keep = target & (depth >= args.min_depth_mm) & (depth <= args.max_depth_mm)
                filtered = np.where(keep, depth, 0).astype(np.uint16)
                if not np.any(keep):
                    raise ValueError("No retained object depth in " + name)
                ok, encoded = cv2.imencode(".png", filtered)
                if not ok:
                    raise ValueError("Cannot encode uint16 depth")
                encoded.tofile(str(dest / "depth" / name))
                verified = imread(dest / "depth" / name)
                if not np.array_equal(verified, filtered) or verified.dtype != np.uint16:
                    raise ValueError("Filtered PNG roundtrip mismatch")
                shutil.copy2(rgbpath, dest / "rgb" / name)
                shutil.copy2(maskpath, dest / "masks" / name)
                if sha(dest / "rgb" / name) != source_frame["source_rgb_sha256"] or sha(dest / "masks" / name) != source_frame["mask_sha256"]:
                    raise ValueError("RGB/mask copy mismatch")
                target_pixels = int(target.sum())
                record["frames"].append({"frame": name, "rgb_sha256": sha(rgbpath),
                                         "mask_sha256": sha(maskpath), "raw_depth_sha256": sha(depthpath),
                                         "filtered_depth_sha256": sha(dest / "depth" / name),
                                         "target_pixels": target_pixels,
                                         "retained_depth_pixels": int(keep.sum()),
                                         "retained_target_percent": 100 * int(keep.sum()) / target_pixels,
                                         "target_raw_missing_pixels": int(np.count_nonzero(target & (depth == 0))),
                                         "target_rejected_positive_depth_pixels": int(np.count_nonzero(target & (depth > 0) & ~keep)),
                                         "retained_values_unchanged": True})
            for name in ("K.txt", "cam_K.txt", "depth_scale.txt", "timestamps.csv", "timestamps.json"):
                shutil.copy2(scene / name, dest / name)
            # Preserve capture provenance with an explicit source name, not as filtered metadata.
            shutil.copy2(scene / "metadata.json", dest / "source_capture_metadata.json")
            (dest / "README.md").write_text(
                "# Cup reconstruction pilot input\n\n"
                "RGB/masks are byte-identical copies of reviewed inputs. Depth is uint16 millimeters; "
                "only mask-positive samples in the recorded distance window remain. Zero is missing/rejected. "
                "See ../report.json for every source/output hash. No depth interpolation or pose labels. "
                "Process each camera-height sequence separately until object registration is verified.\n", encoding="utf-8")
            record["mean_retained_target_percent"] = sum(f["retained_target_percent"] for f in record["frames"]) / len(record["frames"])
        result.update(passed=True, status="complete", paired_frames=sum(len(s["frames"]) for s in result["sequences"]))
    except BaseException as error:
        result.update(error="{}: {}".format(type(error).__name__, error), status="failed")
        raise
    finally:
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "paired_frames": result["paired_frames"],
                      "range_mm": result["depth_range_mm_inclusive"],
                      "mean_retained_target_percent": [s["mean_retained_target_percent"] for s in result["sequences"]],
                      "output": str(output)}))


if __name__ == "__main__":
    main()
