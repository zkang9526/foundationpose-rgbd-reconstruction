#!/usr/bin/env python3
"""Read-only probe of PyTorch CUDA and RealSense Python SDK availability."""
import importlib.util
import json
import platform
import sys

result = {"python": sys.version, "executable": sys.executable,
          "platform": platform.platform(), "torch": None, "realsense": None}
if importlib.util.find_spec("torch") is not None:
    try:
        import torch
        result["torch"] = {"version": torch.__version__, "cuda_build": torch.version.cuda,
                           "cuda_available": torch.cuda.is_available()}
        if torch.cuda.is_available():
            value = torch.eye(3, device="cuda")
            result["torch"]["cuda_execution_passed"] = bool(torch.equal(value @ value, value))
            result["torch"]["device"] = torch.cuda.get_device_name(0)
    except Exception as error:
        result["torch"] = {"error": repr(error)}
if importlib.util.find_spec("pyrealsense2") is not None:
    try:
        import pyrealsense2 as rs
        devices = rs.context().query_devices()
        result["realsense"] = {"module": getattr(rs, "__file__", None), "devices": []}
        for device in devices:
            item = {}
            for name in ("name", "serial_number", "firmware_version", "usb_type_descriptor"):
                info = getattr(rs.camera_info, name)
                if device.supports(info):
                    item[name] = device.get_info(info)
            result["realsense"]["devices"].append(item)
    except Exception as error:
        result["realsense"] = {"error": repr(error)}
print(json.dumps(result, indent=2))
