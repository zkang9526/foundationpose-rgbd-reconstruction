#!/usr/bin/env python3
"""Verify D435i enumeration or aligned RGB-D capture without a GUI or inference.

Dependencies: pyrealsense2, numpy, Pillow. Outputs are overwritten by name;
existing unrelated files are never removed. Depth PNG values retain the camera's
native units; multiply by depth_scale.txt to obtain meters.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.metadata
import json
from pathlib import Path
import platform
import signal
import sys
import time
import traceback


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def nonnegative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def version(distribution):
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def device_info(rs, device):
    info = {}
    for name in (
        "name", "serial_number", "firmware_version", "recommended_firmware_version",
        "usb_type_descriptor", "product_id", "product_line", "physical_port",
    ):
        field = getattr(rs.camera_info, name, None)
        try:
            info[name] = device.get_info(field) if field is not None and device.supports(field) else None
        except Exception as exc:
            info[name] = None
            info[name + "_error"] = str(exc)
    return info


def intrinsics_info(profile):
    intrinsic = profile.as_video_stream_profile().get_intrinsics()
    return {
        "width": int(intrinsic.width), "height": int(intrinsic.height),
        "fx": float(intrinsic.fx), "fy": float(intrinsic.fy),
        "cx": float(intrinsic.ppx), "cy": float(intrinsic.ppy),
        "distortion_model": str(intrinsic.model),
        "distortion_coefficients": [float(value) for value in intrinsic.coeffs],
    }


def stream_info(profile):
    return {
        "stream": str(profile.stream_type()),
        "format": str(profile.format()),
        "fps": int(profile.fps()),
        "intrinsics": intrinsics_info(profile),
    }


def depth_statistics(depth, scale, np):
    valid = depth > 0
    count = int(np.count_nonzero(valid))
    statistics = {
        "total_pixels": int(depth.size), "valid_pixels": count,
        "valid_pixel_ratio": float(count / depth.size),
        "invalid_rule": "native depth value == 0",
    }
    if count:
        native = depth[valid].astype(np.float64)
        statistics["native_units"] = {
            "min": int(native.min()), "max": int(native.max()),
            "mean": float(native.mean()), "median": float(np.median(native)),
        }
        statistics["meters"] = {
            key: float(value * scale)
            for key, value in statistics["native_units"].items()
        }
    return statistics


def save_capture(output, color, depth, color_intrinsics, depth_intrinsics, scale, np, Image):
    Image.fromarray(color).save(str(output / "rgb.png"))
    # Pillow preserves this uint16 array as a 16-bit grayscale PNG.
    require(depth.dtype == np.uint16, "Aligned native depth must be uint16")
    Image.fromarray(depth).save(str(output / "depth.png"))
    meters = depth.astype(np.float32) * np.float32(scale)
    np.save(str(output / "depth_meters.npy"), meters, allow_pickle=False)
    K = np.array([
        [color_intrinsics["fx"], 0.0, color_intrinsics["cx"]],
        [0.0, color_intrinsics["fy"], color_intrinsics["cy"]],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    np.savetxt(str(output / "K.txt"), K, fmt="%.12g")
    (output / "depth_scale.txt").write_text("{:.17g}\n".format(scale), encoding="utf-8")

    valid = depth > 0
    gray = np.zeros(depth.shape, dtype=np.uint8)
    colored = np.zeros(depth.shape + (3,), dtype=np.uint8)
    preview = {"invalid_pixels": "black", "colormap": "near blue, far red"}
    if np.any(valid):
        lower, upper = np.percentile(meters[valid], [2, 98])
        if upper <= lower:
            normalized = np.full(depth.shape, 0.5, dtype=np.float32)
        else:
            normalized = np.clip((meters - lower) / (upper - lower), 0.0, 1.0)
        # Leave zero reserved for invalid pixels in the grayscale preview.
        gray[valid] = (1.0 + normalized[valid] * 254.0).astype(np.uint8)
        colors = np.stack([
            np.clip(1.5 - np.abs(4.0 * normalized - 3.0), 0.0, 1.0),
            np.clip(1.5 - np.abs(4.0 * normalized - 2.0), 0.0, 1.0),
            np.clip(1.5 - np.abs(4.0 * normalized - 1.0), 0.0, 1.0),
        ], axis=-1)
        colored[valid] = (colors[valid] * 255.0).astype(np.uint8)
        preview.update(lower_meters=float(lower), upper_meters=float(upper), percentiles=[2, 98])
    Image.fromarray(gray).save(str(output / "depth_preview_gray.png"))
    Image.fromarray(colored).save(str(output / "depth_preview_color.png"))
    return {
        "rgb": str(output / "rgb.png"),
        "aligned_native_depth_uint16": str(output / "depth.png"),
        "depth_meters_float32": str(output / "depth_meters.npy"),
        "depth_preview_gray": str(output / "depth_preview_gray.png"),
        "depth_preview_color": str(output / "depth_preview_color.png"),
        "camera_matrix": str(output / "K.txt"),
        "depth_scale": str(output / "depth_scale.txt"),
        "color_intrinsics": color_intrinsics,
        "aligned_depth_intrinsics": depth_intrinsics,
        "preview": preview,
    }


def write_report(report, output):
    temporary = output / "report.json.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(output / "report.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("d435i_verification"))
    parser.add_argument("--frames", type=positive_int, default=60)
    parser.add_argument("--warmup", type=nonnegative_int, default=30)
    parser.add_argument("--timeout-ms", type=positive_int, default=5000,
                        help="maximum wait for each frame pair (default: 5000 ms)")
    parser.add_argument("--enumerate-only", action="store_true",
                        help="list SDK devices and save report without starting any streams")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    try:
        output.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print("Cannot create report directory {}: {}".format(output, exc), file=sys.stderr)
        return 1

    started = time.monotonic()
    report = {
        "schema_version": 1, "passed": False,
        "mode": "enumeration_only" if args.enumerate_only else "aligned_rgbd_capture",
        "scope": "camera enumeration or frame acquisition only; no pose inference or reconstruction",
        "inference_validated": False,
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python": sys.version, "python_executable": sys.executable,
        "platform": platform.platform(), "output": str(output),
        "packages": {
            "pyrealsense2": version("pyrealsense2"), "numpy": version("numpy"), "Pillow": version("Pillow"),
        },
        "requested": {
            "width": 640, "height": 480, "fps": 30,
            "color_format": "RGB8", "depth_format": "Z16", "align_to": "color",
            "warmup_frames": args.warmup, "verification_frames": args.frames,
            "timeout_ms_per_wait": args.timeout_ms,
        },
        "devices": [], "warmup_frames": 0, "acquired_frames": 0,
        "frames": [], "warnings": [], "pipeline_started": False, "pipeline_stopped": False,
    }
    pipeline = None
    pipeline_started = False
    last_capture = None
    phase = "sdk_import"
    try:
        import pyrealsense2 as rs
        report["sdk_version"] = str(getattr(rs, "__version__", None) or report["packages"]["pyrealsense2"] or "unknown")
        phase = "device_enumeration"
        context = rs.context()
        devices = list(context.query_devices())
        report["devices"] = [device_info(rs, device) for device in devices]
        report["device_count"] = len(devices)
        print(json.dumps({"sdk_version": report["sdk_version"], "devices": report["devices"]}, ensure_ascii=False), flush=True)
        require(devices, "The SDK found no devices. Check USB connection, udev rules and device permissions.")
        if args.enumerate_only:
            # This mode deliberately does not import image dependencies, construct
            # a pipeline, resolve a stream configuration, or start the camera.
            report["passed"] = True
            report["d435i_present"] = any("D435I" in (info.get("name") or "").upper() for info in report["devices"])
        else:
            phase = "image_dependencies"
            import numpy as np
            from PIL import Image
            phase = "device_selection"
            selected = next((info for info in report["devices"] if "D435I" in (info.get("name") or "").upper()), None)
            require(selected is not None, "The SDK found RealSense devices, but no device identified as D435i.")
            serial = selected.get("serial_number")
            require(serial, "D435i serial number is unavailable; cannot select the device reliably.")
            report["selected_device"] = selected
            if selected.get("usb_type_descriptor") and not selected["usb_type_descriptor"].startswith("3"):
                report["warnings"].append("The SDK did not report a USB 3 connection: " + selected["usb_type_descriptor"])

            phase = "stream_start"
            pipeline = rs.pipeline(context)
            config = rs.config()
            config.enable_device(serial)
            config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
            config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
            active = pipeline.start(config)
            pipeline_started = True
            report["pipeline_started"] = True
            report["active_device"] = device_info(rs, active.get_device())
            report["active_streams"] = [stream_info(profile) for profile in active.get_streams()]
            scale = float(active.get_device().first_depth_sensor().get_depth_scale())
            require(np.isfinite(scale) and scale > 0, "The SDK returned an invalid native depth scale")
            report["depth_scale_meters_per_native_unit"] = scale
            alignment = rs.align(rs.stream.color)

            phase = "warmup"
            for index in range(args.warmup):
                frames = pipeline.wait_for_frames(args.timeout_ms)
                aligned = alignment.process(frames)
                require(aligned.get_color_frame() and aligned.get_depth_frame(), "Missing RGB or depth during warmup")
                report["warmup_frames"] = index + 1

            phase = "capture"
            capture_started = time.monotonic()
            color_numbers = set()
            depth_numbers = set()
            total_valid = 0
            total_pixels = 0
            for index in range(args.frames):
                frames = pipeline.wait_for_frames(args.timeout_ms)
                host_time = time.monotonic()
                aligned = alignment.process(frames)
                color_frame = aligned.get_color_frame()
                depth_frame = aligned.get_depth_frame()
                require(color_frame and depth_frame, "Missing RGB or depth in aligned frame pair")
                color = np.asanyarray(color_frame.get_data()).copy()
                depth = np.asanyarray(depth_frame.get_data()).copy()
                require(color.shape == (480, 640, 3) and color.dtype == np.uint8, "Unexpected RGB shape or dtype")
                require(depth.shape == (480, 640) and depth.dtype == np.uint16, "Unexpected aligned depth shape or dtype")
                require(color_frame.profile.format() == rs.format.rgb8, "The active color frame is not RGB8")
                require(depth_frame.profile.format() == rs.format.z16, "The active depth frame is not Z16")
                color_intrinsic = intrinsics_info(color_frame.profile)
                depth_intrinsic = intrinsics_info(depth_frame.profile)
                statistics = depth_statistics(depth, scale, np)
                color_number = int(color_frame.get_frame_number())
                depth_number = int(depth_frame.get_frame_number())
                color_numbers.add(color_number)
                depth_numbers.add(depth_number)
                total_valid += statistics["valid_pixels"]
                total_pixels += statistics["total_pixels"]
                entry = {
                    "index": index,
                    "host_elapsed_seconds": host_time - capture_started,
                    "color_frame_number": color_number, "depth_frame_number": depth_number,
                    "color_timestamp_ms": float(color_frame.get_timestamp()),
                    "depth_timestamp_ms": float(depth_frame.get_timestamp()),
                    "color_timestamp_domain": str(color_frame.get_frame_timestamp_domain()),
                    "depth_timestamp_domain": str(depth_frame.get_frame_timestamp_domain()),
                    "depth": statistics,
                }
                report["frames"].append(entry)
                report["acquired_frames"] = index + 1
                last_capture = (color, depth, color_intrinsic, depth_intrinsic, scale)
                if index == 0 or (index + 1) % 10 == 0 or index + 1 == args.frames:
                    print("Captured {}/{} aligned pairs; valid depth {:.1%}".format(index + 1, args.frames, statistics["valid_pixel_ratio"]), flush=True)

            capture_elapsed = time.monotonic() - capture_started
            report["capture_seconds"] = capture_elapsed
            report["acquisition_fps"] = args.frames / capture_elapsed if capture_elapsed > 0 else None
            host_span = report["frames"][-1]["host_elapsed_seconds"] - report["frames"][0]["host_elapsed_seconds"]
            report["actual_fps"] = (args.frames - 1) / host_span if args.frames > 1 and host_span > 0 else None
            report["actual_fps_basis"] = "aligned pair arrival intervals measured with host monotonic clock"
            report["unique_color_frames"] = len(color_numbers)
            report["unique_depth_frames"] = len(depth_numbers)
            report["aggregate_valid_pixel_ratio"] = total_valid / total_pixels if total_pixels else 0.0
            report["last_frame_depth"] = report["frames"][-1]["depth"]
            if len(color_numbers) < args.frames or len(depth_numbers) < args.frames:
                report["warnings"].append("Some aligned pairs reused a color or depth frame; inspect frame numbers and measured FPS.")
            require(report["acquired_frames"] == args.frames, "Incomplete frame acquisition")
            require(total_valid > 0, "All acquired depth pixels were zero; depth acquisition is unusable.")
            require(report["last_frame_depth"]["valid_pixels"] > 0, "The final depth frame contains no valid pixels.")
            phase = "save_capture"
            report["files"] = save_capture(output, *last_capture, np, Image)
            report["passed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = {
            "phase": phase, "type": type(exc).__name__, "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        traceback.print_exc()
        # Keep the latest successfully acquired pair for diagnosing a later
        # timeout or unusable depth; this does not mark the verification passed.
        if last_capture is not None and "files" not in report:
            try:
                report["files"] = save_capture(output, *last_capture, np, Image)
            except Exception as save_exc:
                report["warnings"].append("Could not save the last frame: {}: {}".format(type(save_exc).__name__, save_exc))
    finally:
        if pipeline is not None:
            try:
                pipeline.stop()
                report["pipeline_stopped"] = True
            except Exception as exc:
                if pipeline_started:
                    report["passed"] = False
                    report["stop_error"] = "{}: {}".format(type(exc).__name__, exc)
                else:
                    report["warnings"].append("Pipeline never started; stop reported: " + str(exc))
        report["elapsed_seconds"] = time.monotonic() - started
        report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            write_report(report, output)
        except Exception as exc:
            print("Could not save report: {}: {}".format(type(exc).__name__, exc), file=sys.stderr)
            return 1
    print(json.dumps({"passed": report["passed"], "mode": report["mode"],
                      "acquired_frames": report["acquired_frames"], "report": str(output / "report.json")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if hasattr(signal, "SIGBREAK"):
        def on_console_break(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, on_console_break)
    raise SystemExit(main())
