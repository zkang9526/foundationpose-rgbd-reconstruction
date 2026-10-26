#!/usr/bin/env python3
"""Check saved RGB-D sequence pairs, depth PNG format, scale and intrinsics."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("scene", type=Path)
args = parser.parse_args()
scene = args.scene.resolve()
metadata = json.loads((scene / "metadata.json").read_text())
assert metadata["passed"], "Capture did not finish successfully"
rgb_names = sorted(path.name for path in (scene / "rgb").glob("*.png"))
depth_names = sorted(path.name for path in (scene / "depth").glob("*.png"))
assert rgb_names == depth_names, "RGB and depth filenames differ"
assert len(rgb_names) == metadata["saved_frames"] > 0, "Saved frame count differs"
assert len(metadata["frames"]) == len(rgb_names), "Metadata frame count differs"
K = np.loadtxt(scene / "cam_K.txt")
assert K.shape == (3, 3) and np.isfinite(K).all() and K[0, 0] > 0 and K[1, 1] > 0
assert np.allclose(K, np.loadtxt(scene / "K.txt")), "Camera matrix files differ"
assert np.isclose(float((scene / "depth_scale.txt").read_text()), 0.001)
assert metadata["saved_depth"]["scale_meters_per_saved_unit"] == 0.001
for name, frame in zip(rgb_names, metadata["frames"]):
    assert frame["rgb"] == "rgb/" + name and frame["depth"] == "depth/" + name
    with Image.open(scene / "rgb" / name) as rgb:
        assert rgb.mode == "RGB" and rgb.size == (640, 480)
    depth_path = scene / "depth" / name
    with depth_path.open("rb") as stream:
        header = stream.read(26)
    assert header[:8] == b"\x89PNG\r\n\x1a\n" and header[24:26] == b"\x10\x00", "Depth is not 16-bit grayscale PNG"
    with Image.open(depth_path) as image:
        depth = np.asarray(image)
        assert image.size == (640, 480) and np.issubdtype(depth.dtype, np.integer)
        assert depth.min() >= 0 and depth.max() <= 65535
        assert np.isclose(float(np.count_nonzero(depth) / depth.size), frame["saved_valid_pixel_ratio"])
print(json.dumps({"passed": True, "paired_frames": len(rgb_names),
                  "depth_format": "16-bit grayscale PNG, millimeters", "scene": str(scene)}))
