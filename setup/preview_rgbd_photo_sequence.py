#!/usr/bin/env python3
"""Create read-only RGB-D contact sheets for every saved manual photo.

The optional crop is only a display region, not segmentation or a quality
verdict. Depth colormap limits affect previews only; raw data stays unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--crop', type=int, nargs=4, metavar=('X0', 'Y0', 'X1', 'Y1'))
    args = parser.parse_args()
    scene = args.scene.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scale = float((scene / 'depth_scale.txt').read_text(encoding='utf-8-sig').strip())
    paths = sorted((scene / 'rgb').glob('*.png'))
    if not paths:
        raise RuntimeError('No saved RGB images')
    width, height = Image.open(paths[0]).size
    crop = args.crop or [0, 0, width, height]
    if not (0 <= crop[0] < crop[2] <= width and 0 <= crop[1] < crop[3] <= height):
        raise ValueError('Crop is outside the source image')
    modes = dict(rgb_overview=[], rgb_crop=[], depth_crop=[])
    sources = []
    for path in paths:
        depth_path = scene / 'depth' / path.name
        rgb = Image.open(path).convert('RGB')
        depth = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
        if depth is None or depth.dtype != np.uint16 or depth.shape != (height, width):
            raise ValueError('Invalid depth image: ' + str(depth_path))
        meters = depth.astype(np.float32) * scale
        gray = np.rint(np.clip((meters - 0.30) / 0.50, 0, 1) * 255).astype(np.uint8)
        colored = cv2.cvtColor(cv2.applyColorMap(gray, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)
        colored[depth == 0] = 0
        modes['rgb_overview'].append((path.stem, rgb.resize((320, 240))))
        modes['rgb_crop'].append((path.stem, rgb.crop(crop).resize((320, 240))))
        modes['depth_crop'].append((path.stem, Image.fromarray(colored).crop(crop).resize((320, 240))))
        sources.extend(dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                       for p in (path, depth_path))
    for mode, entries in modes.items():
        for start in range(0, len(entries), 8):
            page = entries[start:start + 8]
            rows = (len(page) + 3) // 4
            sheet = Image.new('RGB', (1280, rows * 264), (25, 25, 25))
            draw = ImageDraw.Draw(sheet)
            for index, (label, picture) in enumerate(page):
                x, y = (index % 4) * 320, (index // 4) * 264
                draw.text((x + 8, y + 5), label, fill=(255, 255, 255))
                sheet.paste(picture, (x, y + 24))
            sheet.save(output / ('%s_%02d.png' % (mode, start // 8)))
    report = dict(passed=True, scope='contact_sheets_only_no_quality_verdict',
                  scene=str(scene), frames=len(paths), display_crop_xyxy=crop,
                  depth_preview_range_meters=[0.30, 0.80], depth_missing_color='black',
                  raw_images_modified=False, source_files=sources,
                  artifacts=sorted(p.name for p in output.glob('*.png')))
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, frames=len(paths), output=str(output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
