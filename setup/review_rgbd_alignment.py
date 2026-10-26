#!/usr/bin/env python3
"""Create visual RGB/aligned-depth evidence; do not infer physical calibration.

Accepts one saved check directory (rgb.png/depth.png) or a capture sequence
(rgb/<frame>.png and depth/<frame>.png). Raw inputs are never changed.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--frame', default='000000')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jump-mm', type=float, default=20.,
                        help='depth discontinuity threshold for green edges; not an alignment tolerance')
    args = parser.parse_args()
    if args.jump_mm <= 0:
        parser.error('--jump-mm must be positive')
    if not args.frame.isdigit():
        parser.error('--frame must contain only the saved numeric frame stem')
    source = args.input.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, scope='visual_alignment_inspection_only',
                  physical_alignment_assessed=False, automatic_physical_verdict=None,
                  input=str(source), output=str(output),
                  created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        import cv2
        import numpy as np
        if (source / 'rgb.png').is_file():
            rgb_path, depth_path = source / 'rgb.png', source / 'depth.png'
        else:
            rgb_path = source / 'rgb' / (args.frame + '.png')
            depth_path = source / 'depth' / (args.frame + '.png')
        rgb = cv2.imread(str(rgb_path), cv2.IMREAD_COLOR)
        depth = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
        if rgb is None or depth is None:
            raise RuntimeError('RGB or depth file is missing or unreadable')
        if depth.dtype != np.uint16 or depth.ndim != 2 or depth.shape != rgb.shape[:2]:
            raise RuntimeError('Expected equal-size color and uint16 depth images')
        scale = float((source / 'depth_scale.txt').read_text(encoding='utf-8-sig').strip())
        if not np.isfinite(scale) or scale <= 0:
            raise RuntimeError('Invalid meters-per-depth-unit scale')
        meters = depth.astype(np.float32) * scale
        valid = depth > 0
        if not np.any(valid):
            raise RuntimeError('There are no valid depth samples to inspect')
        lower, upper = np.percentile(meters[valid], [2, 98])
        gray = np.zeros(depth.shape, np.uint8)
        if upper > lower:
            gray[valid] = np.rint(np.clip((meters[valid] - lower) / (upper - lower), 0, 1) * 255).astype(np.uint8)
        else:
            gray[valid] = 128
        colored = cv2.applyColorMap(gray, cv2.COLORMAP_TURBO)
        colored[~valid] = 0
        overlay = rgb.copy()
        blend = cv2.addWeighted(rgb, 0.6, colored, 0.4, 0)
        overlay[valid] = blend[valid]
        edges = np.zeros(depth.shape, np.uint8)
        threshold = args.jump_mm / 1000.
        horizontal = (valid[:, 1:] & valid[:, :-1] & (np.abs(meters[:, 1:] - meters[:, :-1]) > threshold))
        vertical = (valid[1:, :] & valid[:-1, :] & (np.abs(meters[1:, :] - meters[:-1, :]) > threshold))
        edges[:, 1:][horizontal] = 255
        edges[1:, :][vertical] = 255
        on_rgb = rgb.copy()
        on_rgb[edges > 0] = (0, 255, 0)
        # Zero depth has no geometric position. Display its boundaries separately.
        valid_edges = cv2.morphologyEx(valid.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        validity_rgb = rgb.copy()
        validity_rgb[valid_edges > 0] = (0, 165, 255)
        outputs = {'rgb.png': rgb, 'depth_color.png': colored, 'overlay.png': overlay,
                   'depth_edges_on_rgb.png': on_rgb,
                   'invalid_depth_boundaries_on_rgb.png': validity_rgb}
        panels = []
        for label, array in [('RGB', rgb), ('Aligned depth (0 = black)', colored),
                             ('Green = depth jump > %.0f mm' % args.jump_mm, on_rgb)]:
            panel = cv2.copyMakeBorder(array, 30, 0, 0, 0, cv2.BORDER_CONSTANT, value=(28, 28, 28))
            cv2.putText(panel, label, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            panels.append(panel)
        outputs['alignment_panel.png'] = np.concatenate(panels, axis=1)
        for name, array in outputs.items():
            if not cv2.imwrite(str(output / name), array):
                raise RuntimeError('Could not save: ' + name)
        K_path = source / 'cam_K.txt'
        if not K_path.is_file():
            K_path = source / 'K.txt'
        K = np.loadtxt(K_path)
        if K.shape != (3, 3) or not np.isfinite(K).all():
            raise RuntimeError('Invalid camera matrix')
        metadata_path = source / 'metadata.json'
        if not metadata_path.is_file():
            metadata_path = source / 'report.json'
        metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig')) if metadata_path.is_file() else {}
        profile = metadata.get('files', metadata.get('outputs', metadata))
        if not isinstance(profile, dict):
            profile = metadata
        color_K = profile.get('color_intrinsics', metadata.get('color_intrinsics'))
        aligned_K = profile.get('aligned_depth_intrinsics', metadata.get('aligned_depth_intrinsics'))
        same_intrinsics = None
        if color_K and aligned_K:
            same_intrinsics = all(np.isclose(color_K[k], aligned_K[k], atol=1e-6, rtol=0)
                                  for k in ('width', 'height', 'fx', 'fy', 'cx', 'cy'))
        report.update(passed=True, image_shape=list(depth.shape), meters_per_saved_unit=scale,
            valid_pixel_fraction=float(valid.mean()), K=K.tolist(),
            recorded_color_and_aligned_depth_intrinsics_match=same_intrinsics,
            display_range_meters=[float(lower), float(upper)], green_depth_jump_threshold_mm=args.jump_mm,
            green_edge_pixels=int(np.count_nonzero(edges)),
            artifacts=list(outputs),
            instructions='Compare green depth discontinuities to visible object boundaries on a stationary matte target. '
                         'Texture edges need not appear in depth. Orange boundaries mark missing depth, not misalignment. '
                         'Image dimensions/intrinsics matching and a successful run are not physical calibration acceptance.',
            source_files=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                          for p in (rgb_path, depth_path, source / 'depth_scale.txt', K_path)])
    except Exception as exc:
        report['error'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
