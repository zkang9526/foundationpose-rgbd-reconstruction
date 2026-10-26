#!/usr/bin/env python3
"""Save individual, fresh D435i RGB-D pairs after an Enter key request.

Keep the camera fixed. Rotate the object, let it settle, remove your hand, then
press Enter. Images are PNG pairs, not a video. Planned angles are operator
instructions only: they are neither measured angles nor ground-truth poses.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
from pathlib import Path
import queue
import signal
import shutil
import sys
import threading
import time
import traceback

from capture_d435i import (
    get_device_info, get_intrinsics, millimeter_depth, nonnegative_int,
    package_version, positive_float, positive_int, require, write_json,
)
from realsense_capture_options import CaptureOptions


def read_requests(requests):
    """Only stdin blocks here; the main thread keeps draining camera frames."""
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                requests.put(("eof", time.monotonic()))
                return
            value = line.strip().lower()
            action = "enter" if not value else ("quit" if value == "q" else "unknown")
            requests.put((action, time.monotonic()))
            if action == "quit":
                return
    except Exception as exc:
        requests.put(("stdin_error", "{}: {}".format(type(exc).__name__, exc)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--views", type=positive_int, default=36)
    parser.add_argument("--planned-angle-step", type=positive_float, default=10.0,
                        help="planned operator rotation per photo, degrees; not a measured pose")
    parser.add_argument("--warmup", type=nonnegative_int, default=90)
    parser.add_argument("--settle-seconds", type=positive_float, default=1.0,
                        help="keep draining frames for this time after Enter before saving")
    parser.add_argument("--max-timestamp-gap-ms", type=positive_float, default=30.0)
    parser.add_argument("--timeout-ms", type=positive_int, default=5000)
    parser.add_argument("--pair-timeout-seconds", type=positive_float, default=10.0,
                        help="maximum additional wait for a fresh synchronized pair after settling")
    parser.add_argument("--record-bag", action="store_true",
                        help="also record original SDK streams to raw_streams.bag; includes waiting and motion")
    parser.add_argument("--depth-preset", choices=("device-default", "high-accuracy", "high-density"), default="device-default",
                        help="device-default preserves current settings; explicit presets back up and restore actual parameters")
    parser.add_argument("--depth-auto-exposure", action="store_true",
                        help="enable depth auto-exposure for this run, with full settings backup and restoration")
    parser.add_argument("--min-free-gb", type=positive_float, default=2.0,
                        help="stop safely while at least this many GiB remain on the capture drive")
    parser.add_argument("--save-filtered-depth", action="store_true",
                        help="save additional derived spatial/temporal/hole-filled depth; keep depth/ raw")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    reserved = {"rgb", "depth", "depth_filtered", "raw_streams.bag", "color", "mask", "masks", "cam_k.txt", "k.txt", "depth_scale.txt"}
    try:
        if output.exists():
            require(output.is_dir(), "Output path is not a directory")
            conflicts = [path.name for path in output.iterdir()
                         if path.name.lower() in reserved or path.name.lower().startswith(("metadata", "report", "timestamp"))]
            require(not conflicts, "Refusing to overwrite existing scene data: " + ", ".join(sorted(conflicts)))
        output.mkdir(parents=True, exist_ok=True)
        (output / "rgb").mkdir(exist_ok=False)
        (output / "depth").mkdir(exist_ok=False)
        if args.save_filtered_depth:
            (output / "depth_filtered").mkdir(exist_ok=False)
    except Exception as exc:
        print("{}: {}. Choose a new --output directory.".format(type(exc).__name__, exc), file=sys.stderr)
        return 1

    started = time.monotonic()
    report = {
        "schema_version": 1, "passed": False, "status": "incomplete",
        "capture_mode": "manual_stationary_rgbd_photos",
        "scope": "RGB-D acquisition only; no masks, reconstruction or pose inference",
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "output": str(output), "python": sys.version,
        "packages": {name: package_version(name) for name in ("pyrealsense2", "numpy", "Pillow")},
        "requested": {"views": args.views, "planned_angle_step_degrees": args.planned_angle_step,
                      "warmup_frames": args.warmup, "settle_seconds": args.settle_seconds,
                      "width": 640, "height": 480, "stream_fps": 30,
                      "color_format": "RGB8", "depth_format": "Z16", "align_to": "color",
                      "max_timestamp_gap_ms": args.max_timestamp_gap_ms,
                      "timeout_ms_per_wait": args.timeout_ms,
                      "pair_timeout_seconds": args.pair_timeout_seconds},
        "planned_angles_are_measured": False,
        "planned_angles_are_ground_truth_poses": False,
        "saved_depth": {"unit": "millimeter", "scale_meters_per_saved_unit": 0.001,
                        "dtype": "uint16", "invalid_value": 0,
                        "conversion": "round half up; zero, non-finite and out-of-range values become zero"},
        "warmup_frames": 0, "acquired_frames": 0, "saved_frames": 0,
        "frames": [], "warnings": [], "pipeline_started": False, "pipeline_stopped": False,
        "rejected_pairs": {"timestamp_gap": 0, "timestamp_domain": 0, "repeated_or_pre_request_frame": 0},
        "storage_guard": {"minimum_free_bytes": int(args.min_free_gb * 1024**3),
                          "check_interval_seconds": 1.0},
    }
    pipeline = None
    capture_options = None
    active_started = False
    csv_handle = None
    phase = "imports"
    capture_started = None
    valid_saved_pixels = 0
    total_saved_pixels = 0

    def save_reports():
        write_json(output / "timestamps.json", report["frames"])
        write_json(output / "metadata.json", report)
        write_json(output / "report.json", {key: value for key, value in report.items() if key != "frames"})

    def prompt_next():
        index = report["saved_frames"]
        angle = index * args.planned_angle_step
        print("Photo {}/{}: planned rotation {:.1f} degrees (not measured).".format(index + 1, args.views, angle), flush=True)
        print("Rotate the cup, STOP, remove your hand; press Enter to save one RGB-D pair, or q + Enter to stop.", flush=True)

    try:
        import pyrealsense2 as rs
        import numpy as np
        from PIL import Image

        report["sdk_version"] = str(getattr(rs, "__version__", None) or report["packages"]["pyrealsense2"] or "unknown")
        phase = "device_enumeration"
        context = rs.context()
        devices = list(context.query_devices())
        report["devices"] = [get_device_info(rs, device) for device in devices]
        require(devices, "The SDK found no devices; check the D435i USB connection")
        selected = next((info for info in report["devices"] if "D435I" in (info.get("name") or "").upper()), None)
        require(selected is not None, "No connected device was identified as D435i")
        require(selected.get("serial_number"), "D435i serial number is unavailable")
        report["device"] = selected
        if selected.get("usb_type_descriptor") and not selected["usb_type_descriptor"].startswith("3"):
            report["warnings"].append("The SDK did not report USB 3: " + selected["usb_type_descriptor"])

        phase = "stream_start"
        available_bytes = shutil.disk_usage(output).free
        report['storage_guard']['free_bytes_before_stream'] = available_bytes
        require(available_bytes >= report['storage_guard']['minimum_free_bytes'],
                'Capture drive has less than the required free space; no stream started')
        pipeline = rs.pipeline(context)
        config = rs.config()
        config.enable_device(selected["serial_number"])
        config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        if args.record_bag:
            config.enable_record_to_file(str(output / "raw_streams.bag"))
        report["bag_recording"] = {"enabled": args.record_bag, "file": "raw_streams.bag" if args.record_bag else None,
                                   "scope": "native unaligned streams, including warmup, waiting and motion"}
        active = pipeline.start(config)
        active_started = True
        report["pipeline_started"] = True
        depth_sensor = active.get_device().first_depth_sensor()
        # A recording pipeline exposes an SDK recorder wrapper, which cannot
        # be cast to rs400_advanced_mode. Use the enumerated physical device.
        physical_device = next(device for device in devices
                               if device.get_info(rs.camera_info.serial_number) == selected['serial_number'])
        capture_options = CaptureOptions(rs, depth_sensor, report, physical_device, output)
        capture_options.configure(args.depth_preset, args.save_filtered_depth, args.depth_auto_exposure)
        native_scale = float(depth_sensor.get_depth_scale())
        require(np.isfinite(native_scale) and native_scale > 0, "Invalid native depth scale returned by SDK")
        report["native_depth_scale_meters_per_unit"] = native_scale
        color_intrinsics = get_intrinsics(active.get_stream(rs.stream.color))
        report["color_intrinsics"] = color_intrinsics
        report["native_depth_intrinsics"] = get_intrinsics(active.get_stream(rs.stream.depth))
        native_extrinsics = active.get_stream(rs.stream.depth).get_extrinsics_to(active.get_stream(rs.stream.color))
        report["native_depth_to_color_extrinsics"] = {
            "rotation_column_major": list(native_extrinsics.rotation),
            "translation_meters": list(native_extrinsics.translation),
            "source": "SDK active stream profiles; not multiview object poses"}
        report["active_streams"] = [
            {"stream": str(profile.stream_type()), "format": str(profile.format()), "fps": int(profile.fps())}
            for profile in active.get_streams()
        ]
        K = np.array([[color_intrinsics["fx"], 0., color_intrinsics["cx"]],
                      [0., color_intrinsics["fy"], color_intrinsics["cy"]], [0., 0., 1.]], dtype=np.float64)
        require(np.isfinite(K).all() and color_intrinsics["fx"] > 0 and color_intrinsics["fy"] > 0,
                "Invalid color camera intrinsics")
        for filename in ("cam_K.txt", "K.txt"):
            np.savetxt(str(output / filename), K, fmt="%.12g")
        (output / "depth_scale.txt").write_text("0.001\n", encoding="utf-8")
        align = rs.align(rs.stream.color)

        phase = "warmup"
        print("Warming up {} RGB-D pairs. Keep the fixed camera and cup steady.".format(args.warmup), flush=True)
        for index in range(args.warmup):
            aligned = align.process(pipeline.wait_for_frames(args.timeout_ms))
            require(aligned.get_color_frame() and aligned.get_depth_frame(), "Missing RGB or depth during warmup")
            capture_options.process(aligned.get_depth_frame())
            report["warmup_frames"] = index + 1
        fields = ["index", "rgb", "depth", "planned_angle_degrees", "planned_angle_is_measured",
                  "host_elapsed_seconds", "request_host_elapsed_seconds", "settle_seconds",
                  "color_frame_number", "depth_frame_number", "color_timestamp_ms", "depth_timestamp_ms",
                  "timestamp_gap_ms", "color_timestamp_domain", "depth_timestamp_domain",
                  "native_valid_pixel_ratio", "saved_valid_pixel_ratio", "conversion_rejected_pixels"]
        csv_handle = (output / "timestamps.csv").open("w", encoding="utf-8", newline="")
        writer = csv.DictWriter(csv_handle, fieldnames=fields)
        writer.writeheader()
        csv_handle.flush()
        capture_started = time.monotonic()
        report["capture_started_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        requests = queue.Queue()
        threading.Thread(target=read_requests, args=(requests,), daemon=True).start()
        phase = "waiting_for_enter"
        pending = None
        last_saved_numbers = None
        stopped_by_operator = False
        prompt_next()
        save_reports()
        last_space_check = 0.0
        while report["saved_frames"] < args.views:
            if time.monotonic() - last_space_check >= 1.0:
                available_bytes = shutil.disk_usage(output).free
                report['storage_guard']['last_free_bytes'] = available_bytes
                require(available_bytes >= report['storage_guard']['minimum_free_bytes'],
                        'Capture drive is nearly full; stop and retain existing pairs')
                last_space_check = time.monotonic()
            # Never stop camera acquisition while waiting for terminal input.
            aligned = align.process(pipeline.wait_for_frames(args.timeout_ms))
            arrival = time.monotonic()
            color_frame = aligned.get_color_frame()
            depth_frame = aligned.get_depth_frame()
            require(color_frame and depth_frame, "Missing RGB or depth after alignment")
            filtered_frame = capture_options.process(depth_frame)
            report["acquired_frames"] += 1
            numbers = (int(color_frame.get_frame_number()), int(depth_frame.get_frame_number()))
            while True:
                try:
                    action, request_time = requests.get_nowait()
                except queue.Empty:
                    break
                if action in ("quit", "eof", "stdin_error"):
                    report["stop_reason"] = action
                    if action == "stdin_error":
                        report["stdin_error"] = request_time
                    stopped_by_operator = True
                    break
                if action == "unknown":
                    print("Use an empty Enter key press to save, or q + Enter to stop.", flush=True)
                elif pending is None:
                    pending = {"request_time": request_time, "baseline_numbers": numbers}
                    phase = "settling"
                    print("Request received; draining fresh frames for {:.1f}s. Keep the cup STILL.".format(args.settle_seconds), flush=True)
                else:
                    print("Extra Enter ignored while this photo is pending; wait for Saved before rotating again.", flush=True)
            if stopped_by_operator:
                break
            if pending is None:
                continue
            ready_at = pending["request_time"] + args.settle_seconds
            require(arrival <= ready_at + args.pair_timeout_seconds, "No fresh synchronized RGB-D pair after Enter within timeout")
            if arrival < ready_at:
                continue
            phase = "saving_requested_pair"
            if (numbers[0] <= pending["baseline_numbers"][0] or numbers[1] <= pending["baseline_numbers"][1]
                    or (last_saved_numbers is not None and (numbers[0] <= last_saved_numbers[0] or numbers[1] <= last_saved_numbers[1]))):
                report["rejected_pairs"]["repeated_or_pre_request_frame"] += 1
                continue
            color_domain = str(color_frame.get_frame_timestamp_domain())
            depth_domain = str(depth_frame.get_frame_timestamp_domain())
            if color_domain != depth_domain:
                report["rejected_pairs"]["timestamp_domain"] += 1
                continue
            color_timestamp = float(color_frame.get_timestamp())
            depth_timestamp = float(depth_frame.get_timestamp())
            gap = abs(color_timestamp - depth_timestamp)
            if not np.isfinite(gap) or gap > args.max_timestamp_gap_ms:
                report["rejected_pairs"]["timestamp_gap"] += 1
                continue
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
            Image.fromarray(color).save(str(output / rgb_path), compress_level=1)
            Image.fromarray(depth).save(str(output / depth_path), compress_level=1)
            if filtered_frame is not None:
                filtered_native = np.asanyarray(filtered_frame.get_data()).copy()
                require(filtered_native.shape == native_depth.shape and filtered_native.dtype == np.uint16,
                        "Unexpected filtered depth shape or dtype")
                filtered_depth, _ = millimeter_depth(filtered_native, native_scale, np)
                Image.fromarray(filtered_depth).save(str(output / ("depth_filtered/{:06d}.png".format(index))), compress_level=1)
            valid_count = int(np.count_nonzero(depth))
            valid_saved_pixels += valid_count
            total_saved_pixels += int(depth.size)
            entry = {
                "index": index, "rgb": rgb_path, "depth": depth_path,
                "planned_angle_degrees": index * args.planned_angle_step,
                "planned_angle_is_measured": False,
                "host_elapsed_seconds": arrival - capture_started,
                "request_host_elapsed_seconds": pending["request_time"] - capture_started,
                "settle_seconds": args.settle_seconds,
                "color_frame_number": numbers[0], "depth_frame_number": numbers[1],
                "color_timestamp_ms": color_timestamp, "depth_timestamp_ms": depth_timestamp,
                "timestamp_gap_ms": gap, "color_timestamp_domain": color_domain,
                "depth_timestamp_domain": depth_domain,
                "native_valid_pixel_ratio": float(np.count_nonzero(native_depth) / native_depth.size),
                "saved_valid_pixel_ratio": valid_count / depth.size,
                "conversion_rejected_pixels": rejected,
            }
            report["frames"].append(entry)
            report["saved_frames"] += 1
            writer.writerow(entry)
            csv_handle.flush()
            last_saved_numbers = numbers
            pending = None
            report["aggregate_saved_valid_pixel_ratio"] = valid_saved_pixels / total_saved_pixels
            save_reports()
            print("Saved {}/{}: planned angle {:.1f} degrees; timestamp gap {:.2f}ms; raw depth valid (whole image) {:.1f}%.".format(
                report["saved_frames"], args.views, entry["planned_angle_degrees"], gap, entry["saved_valid_pixel_ratio"] * 100), flush=True)
            print("  RGB: {}\n  depth: {}".format(output / rgb_path, output / depth_path), flush=True)
            if report["saved_frames"] < args.views:
                phase = "waiting_for_enter"
                prompt_next()
        if report["saved_frames"] == args.views:
            require(valid_saved_pixels > 0, "All saved depth pixels are invalid")
            report["passed"] = True
            report["status"] = "complete"
        else:
            print("Stopped early: {}/{} pairs retained; status incomplete, passed=false.".format(report["saved_frames"], args.views), flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = {"phase": phase, "type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        report["stop_reason"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "error"
        traceback.print_exc()
    finally:
        if capture_options is not None:
            try:
                capture_options.restore()
            except Exception as exc:
                report["passed"] = False
                report["preset_restore_error"] = "{}: {}".format(type(exc).__name__, exc)
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
        if not report["passed"]:
            report["status"] = "incomplete"
        report["aggregate_saved_valid_pixel_ratio"] = valid_saved_pixels / total_saved_pixels if total_saved_pixels else 0.0
        report["elapsed_seconds"] = time.monotonic() - started
        if capture_started is not None:
            report["capture_seconds"] = time.monotonic() - capture_started
        report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            save_reports()
        except Exception as exc:
            print("Could not save capture report: {}: {}".format(type(exc).__name__, exc), file=sys.stderr)
            return 1
    print(json.dumps({"passed": report["passed"], "status": report["status"], "saved_frames": report["saved_frames"], "output": str(output)}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if hasattr(signal, "SIGBREAK"):
        def on_console_break(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, on_console_break)
    raise SystemExit(main())
