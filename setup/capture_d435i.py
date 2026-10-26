#!/usr/bin/env python3
"""Capture a new D435i RGB-D sequence without a GUI, masks or pose inference.

Requires pyrealsense2, numpy and Pillow. RGB8 and Z16 streams are 640x480
at 30 FPS; depth is aligned to color. Saved depth PNGs use integer millimeters,
with 0 reserved for invalid depth. Existing sequence data are never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import importlib.metadata
import json
import math
from pathlib import Path
import signal
import sys
import time
import traceback


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def nonnegative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def get_device_info(rs, device):
    info = {}
    for name in ("name", "serial_number", "firmware_version", "usb_type_descriptor", "product_id", "physical_port"):
        field = getattr(rs.camera_info, name, None)
        info[name] = device.get_info(field) if field is not None and device.supports(field) else None
    return info


def get_intrinsics(profile):
    intrinsic = profile.as_video_stream_profile().get_intrinsics()
    return {
        "width": int(intrinsic.width), "height": int(intrinsic.height),
        "fx": float(intrinsic.fx), "fy": float(intrinsic.fy),
        "cx": float(intrinsic.ppx), "cy": float(intrinsic.ppy),
        "distortion_model": str(intrinsic.model),
        "distortion_coefficients": [float(value) for value in intrinsic.coeffs],
    }


def millimeter_depth(native_depth, native_scale, np):
    # Positive values round half up. Overflow and non-finite values are invalid,
    # rather than saturated to a misleading 65.535-meter surface.
    rounded = np.floor(native_depth.astype(np.float64) * native_scale * 1000.0 + 0.5)
    representable = (native_depth > 0) & np.isfinite(rounded) & (rounded >= 1) & (rounded <= 65535)
    result = np.zeros(native_depth.shape, dtype=np.uint16)
    result[representable] = rounded[representable].astype(np.uint16)
    rejected = int(np.count_nonzero((native_depth > 0) & ~representable))
    return result, rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=positive_float, default=30.0)
    parser.add_argument("--save-fps", type=positive_float, default=10.0)
    parser.add_argument("--countdown", type=nonnegative_int, default=5)
    parser.add_argument("--warmup", type=nonnegative_int, default=30)
    parser.add_argument("--timeout-ms", type=positive_int, default=5000)
    args = parser.parse_args()
    if args.save_fps > 30:
        parser.error("--save-fps cannot exceed the 30 FPS camera stream")
    output = args.output.expanduser().resolve()
    reserved = {"rgb", "depth", "color", "mask", "masks", "cam_k.txt", "k.txt", "depth_scale.txt"}
    try:
        if output.exists():
            require(output.is_dir(), "Output path is not a directory")
            conflicts = [path.name for path in output.iterdir()
                         if path.name.lower() in reserved or path.name.lower().startswith(("metadata", "report", "timestamp"))]
            require(not conflicts, "Refusing to overwrite existing sequence data: " + ", ".join(sorted(conflicts)))
        output.mkdir(parents=True, exist_ok=True)
        (output / "rgb").mkdir(exist_ok=False)
        (output / "depth").mkdir(exist_ok=False)
    except Exception as exc:
        print("{}: {}. Choose a new --output directory.".format(type(exc).__name__, exc), file=sys.stderr)
        return 1

    started = time.monotonic()
    report = {
        "schema_version": 1, "passed": False,
        "scope": "RGB-D acquisition only; no masks, reconstruction or pose inference",
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "output": str(output), "python": sys.version,
        "packages": {name: package_version(name) for name in ("pyrealsense2", "numpy", "Pillow")},
        "requested": {"seconds": args.seconds, "save_fps": args.save_fps,
                      "countdown_seconds": args.countdown, "warmup_frames": args.warmup,
                      "width": 640, "height": 480, "stream_fps": 30,
                      "color_format": "RGB8", "depth_format": "Z16", "align_to": "color",
                      "timeout_ms_per_wait": args.timeout_ms},
        "saved_depth": {"unit": "millimeter", "scale_meters_per_saved_unit": 0.001,
                        "dtype": "uint16", "invalid_value": 0,
                        "conversion": "round half up; zero, non-finite and out-of-range values become zero"},
        "warmup_frames": 0, "acquired_frames": 0, "saved_frames": 0,
        "frames": [], "warnings": [], "pipeline_started": False, "pipeline_stopped": False,
    }
    pipeline = None
    active_started = False
    csv_handle = None
    phase = "imports"
    capture_started = None
    first_arrival = None
    last_arrival = None
    valid_saved_pixels = 0
    total_saved_pixels = 0
    try:
        import pyrealsense2 as rs
        import numpy as np
        from PIL import Image
        report["sdk_version"] = str(getattr(rs, "__version__", None) or report["packages"]["pyrealsense2"] or "unknown")
        phase = "device_enumeration"
        context = rs.context()
        devices = list(context.query_devices())
        report["devices"] = [get_device_info(rs, device) for device in devices]
        require(devices, "The SDK found no devices; check USB connection, udev rules and permissions")
        selected = next((info for info in report["devices"] if "D435I" in (info.get("name") or "").upper()), None)
        require(selected is not None, "No connected device was identified as D435i")
        require(selected.get("serial_number"), "D435i serial number is unavailable")
        report["device"] = selected
        if selected.get("usb_type_descriptor") and not selected["usb_type_descriptor"].startswith("3"):
            report["warnings"].append("The SDK did not report USB 3: " + selected["usb_type_descriptor"])

        phase = "stream_start"
        pipeline = rs.pipeline(context)
        config = rs.config()
        config.enable_device(selected["serial_number"])
        config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        active = pipeline.start(config)
        active_started = True
        report["pipeline_started"] = True
        native_scale = float(active.get_device().first_depth_sensor().get_depth_scale())
        require(np.isfinite(native_scale) and native_scale > 0, "Invalid native depth scale returned by SDK")
        report["native_depth_scale_meters_per_unit"] = native_scale
        color_intrinsics = get_intrinsics(active.get_stream(rs.stream.color))
        report["color_intrinsics"] = color_intrinsics
        report["native_depth_intrinsics"] = get_intrinsics(active.get_stream(rs.stream.depth))
        report["active_streams"] = [
            {"stream": str(profile.stream_type()), "format": str(profile.format()), "fps": int(profile.fps())}
            for profile in active.get_streams()
        ]
        K = np.array([[color_intrinsics["fx"], 0., color_intrinsics["cx"]],
                      [0., color_intrinsics["fy"], color_intrinsics["cy"]], [0., 0., 1.]], dtype=np.float64)
        require(np.isfinite(K).all() and color_intrinsics["fx"] > 0 and color_intrinsics["fy"] > 0, "Invalid color camera intrinsics")
        for filename in ("cam_K.txt", "K.txt"):
            np.savetxt(str(output / filename), K, fmt="%.12g")
        (output / "depth_scale.txt").write_text("0.001\n", encoding="utf-8")
        align = rs.align(rs.stream.color)

        phase = "warmup"
        print("Warming up {} frames; then a {}-second countdown.".format(args.warmup, args.countdown), flush=True)
        for index in range(args.warmup):
            aligned = align.process(pipeline.wait_for_frames(args.timeout_ms))
            require(aligned.get_color_frame() and aligned.get_depth_frame(), "Missing RGB or depth during warmup")
            report["warmup_frames"] = index + 1
        phase = "countdown"
        print("Keep the object visible. Capture will start after the countdown; show different views slowly.", flush=True)
        for remaining in range(args.countdown, 0, -1):
            print("Starting in {}...".format(remaining), flush=True)
            time.sleep(1)

        fields = ["index", "rgb", "depth", "sample_slot", "scheduled_elapsed_seconds", "host_elapsed_seconds",
                  "color_frame_number", "depth_frame_number", "color_timestamp_ms", "depth_timestamp_ms",
                  "color_timestamp_domain", "depth_timestamp_domain", "native_valid_pixel_ratio",
                  "saved_valid_pixel_ratio", "conversion_rejected_pixels"]
        csv_handle = (output / "timestamps.csv").open("w", encoding="utf-8", newline="")
        writer = csv.DictWriter(csv_handle, fieldnames=fields)
        writer.writeheader()
        phase = "capture"
        next_slot = 0
        next_progress = 1.0
        capture_started = time.monotonic()
        report["capture_started_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        print("Capturing for {:.1f}s, saving up to {:.1f} FPS...".format(args.seconds, args.save_fps), flush=True)
        while time.monotonic() - capture_started < args.seconds:
            frames = pipeline.wait_for_frames(args.timeout_ms)
            arrival = time.monotonic()
            elapsed = arrival - capture_started
            aligned = align.process(frames)
            color_frame = aligned.get_color_frame()
            depth_frame = aligned.get_depth_frame()
            require(color_frame and depth_frame, "Missing RGB or depth after alignment")
            report["acquired_frames"] += 1
            if first_arrival is None:
                first_arrival = arrival
            last_arrival = arrival
            slot = int(elapsed * args.save_fps)
            if elapsed < args.seconds and slot >= next_slot:
                color = np.asanyarray(color_frame.get_data()).copy()
                native_depth = np.asanyarray(depth_frame.get_data()).copy()
                require(color.shape == (480, 640, 3) and color.dtype == np.uint8 and color_frame.profile.format() == rs.format.rgb8,
                        "Unexpected RGB frame shape, dtype or format")
                require(native_depth.shape == (480, 640) and native_depth.dtype == np.uint16 and depth_frame.profile.format() == rs.format.z16,
                        "Unexpected aligned native depth shape, dtype or format")
                if "aligned_depth_intrinsics" not in report:
                    report["aligned_depth_intrinsics"] = get_intrinsics(depth_frame.profile)
                depth, rejected = millimeter_depth(native_depth, native_scale, np)
                index = report["saved_frames"]
                rgb_path = "rgb/{:06d}.png".format(index)
                depth_path = "depth/{:06d}.png".format(index)
                # Use fast lossless PNG compression to reduce acquisition stalls.
                Image.fromarray(color).save(str(output / rgb_path), compress_level=1)
                Image.fromarray(depth).save(str(output / depth_path), compress_level=1)
                valid_count = int(np.count_nonzero(depth))
                valid_saved_pixels += valid_count
                total_saved_pixels += int(depth.size)
                entry = {
                    "index": index, "rgb": rgb_path, "depth": depth_path,
                    "sample_slot": slot, "scheduled_elapsed_seconds": slot / args.save_fps,
                    "host_elapsed_seconds": elapsed,
                    "color_frame_number": int(color_frame.get_frame_number()),
                    "depth_frame_number": int(depth_frame.get_frame_number()),
                    "color_timestamp_ms": float(color_frame.get_timestamp()),
                    "depth_timestamp_ms": float(depth_frame.get_timestamp()),
                    "color_timestamp_domain": str(color_frame.get_frame_timestamp_domain()),
                    "depth_timestamp_domain": str(depth_frame.get_frame_timestamp_domain()),
                    "native_valid_pixel_ratio": float(np.count_nonzero(native_depth) / native_depth.size),
                    "saved_valid_pixel_ratio": valid_count / depth.size,
                    "conversion_rejected_pixels": rejected,
                }
                report["frames"].append(entry)
                report["saved_frames"] += 1
                writer.writerow(entry)
                csv_handle.flush()
                # Advance against the fixed start time; never burst to catch up
                # with sampling slots missed during acquisition or disk writes.
                next_slot = slot + 1
            if elapsed >= next_progress:
                print("{:.1f}/{:.1f}s: acquired {}, saved {}".format(elapsed, args.seconds, report["acquired_frames"], report["saved_frames"]), flush=True)
                next_progress = math.floor(elapsed) + 1.0
        require(report["saved_frames"] > 0, "No frame pair was saved within the capture duration")
        require(valid_saved_pixels > 0, "All saved depth pixels are invalid; the sequence cannot support RGB-D reconstruction")
        report["passed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = {"phase": phase, "type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        traceback.print_exc()
    finally:
        if capture_started is not None:
            report["capture_seconds"] = time.monotonic() - capture_started
        if csv_handle is not None:
            try:
                csv_handle.close()
            except Exception as exc:
                report["passed"] = False
                report["csv_close_error"] = "{}: {}".format(type(exc).__name__, exc)
        if pipeline is not None:
            try:
                pipeline.stop()
                report["pipeline_stopped"] = True
            except Exception as exc:
                if active_started:
                    report["passed"] = False
                    report["stop_error"] = "{}: {}".format(type(exc).__name__, exc)
        if capture_started is not None:
            span = last_arrival - first_arrival if first_arrival is not None and last_arrival is not None else 0.0
            report["actual_acquisition_fps"] = (report["acquired_frames"] - 1) / span if span > 0 else None
            saved_span = report["frames"][-1]["host_elapsed_seconds"] - report["frames"][0]["host_elapsed_seconds"] if len(report["frames"]) > 1 else 0.0
            report["actual_saved_fps"] = (report["saved_frames"] - 1) / saved_span if saved_span > 0 else None
        report["aggregate_saved_valid_pixel_ratio"] = valid_saved_pixels / total_saved_pixels if total_saved_pixels else 0.0
        report["elapsed_seconds"] = time.monotonic() - started
        report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            write_json(output / "timestamps.json", report["frames"])
            write_json(output / "metadata.json", report)
            summary = {key: value for key, value in report.items() if key != "frames"}
            write_json(output / "report.json", summary)
        except Exception as exc:
            print("Could not save capture report: {}: {}".format(type(exc).__name__, exc), file=sys.stderr)
            return 1
    print(json.dumps({"passed": report["passed"], "saved_frames": report["saved_frames"], "output": str(output)}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if hasattr(signal, "SIGBREAK"):
        def on_console_break(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, on_console_break)
    raise SystemExit(main())
