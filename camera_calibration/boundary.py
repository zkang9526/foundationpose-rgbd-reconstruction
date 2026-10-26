"""Measure aligned depth discontinuities against a human-marked physical board.

Signed offset is positive towards board interior. No pixel threshold is treated
as a manufacturer tolerance; occlusion and missing depth remain explicit.
"""
from pathlib import Path

import cv2
import numpy as np

from common import distribution, now, sha, write_json


def check_boundary(trial, vertices, scale, output):
    trial, output = Path(trial), Path(output)
    polygon = np.array(vertices, float)
    rgb = cv2.imread(str(trial / 'rgb.png'))
    depth = np.load(str(trial / 'depth_aligned.npy'), allow_pickle=False)
    if rgb is None or depth.shape != rgb.shape[:2] or depth.dtype != np.uint16:
        raise ValueError('Expected original RGB and aligned uint16 depth')
    h, w = depth.shape
    if polygon.shape != (4, 2) or not np.isfinite(polygon).all() or not (
            (polygon[:, 0] >= 0).all() and (polygon[:, 0] < w).all() and
            (polygon[:, 1] >= 0).all() and (polygon[:, 1] < h).all()):
        raise ValueError('Four finite physical outer board corners must be inside RGB image')
    if not cv2.isContourConvex(polygon.astype(np.float32)) or abs(cv2.contourArea(polygon.astype(np.float32))) < 2000:
        raise ValueError('Click four outer board corners in clockwise or counterclockwise order')
    output.mkdir(parents=True, exist_ok=False)
    result = dict(created_utc=now(), trial=str(trial), physical_boundary_manually_marked=True,
                  physical_calibration_accepted=False, vertices_rgb_px=polygon.tolist(), edges=[],
                  method='Median 3x3 valid depth; outside-to-inside negative step over 4 px; search +/-12 px; skip edge endpoints',
                  jump_threshold_mm=30, search_radius_px=12,
                  notes=['Mark the physical board perimeter, not the black/white pattern edge or internal corners.',
                         'Use a flat matte board separated from background by >50 mm. Missing/ambiguous/out-of-range depth edges are excluded and counted.',
                         'Occlusion can move a visible depth silhouette relative to RGB. Inspect each side and multiple poses; this metric is not an automatic pass.'],
                  source_sha256={name: sha(trial / name) for name in ('rgb.png', 'depth_aligned.npy')})
    overlay = rgb.copy()
    cv2.polylines(overlay, [np.round(polygon).astype(np.int32)], True, (0, 255, 255), 1)
    z = depth.astype(float) * scale
    offsets = np.arange(-14, 15, dtype=float)
    for e in range(4):
        start, end = polygon[e], polygon[(e+1) % 4]
        vector = end-start
        normal = np.array([-vector[1], vector[0]]) / np.linalg.norm(vector)
        middle = (start+end)/2
        if np.dot(normal, polygon.mean(axis=0)-middle) < 0:
            normal = -normal
        samples, missed, ambiguous = [], 0, 0
        for fraction in np.linspace(.15, .85, 80):
            point = start + fraction*vector
            pixels = np.round(point + offsets[:, None]*normal).astype(int)
            values = []
            for x, y in pixels:
                if not (1 <= x < w-1 and 1 <= y < h-1):
                    values.append(np.nan)
                    continue
                patch = z[y-1:y+2, x-1:x+2]
                valid = patch[patch > 0]
                values.append(float(np.median(valid)) if len(valid) >= 5 else np.nan)
            values = np.array(values)
            jumps = values[:-4] - values[4:]
            candidates = np.flatnonzero(jumps >= .03)
            if not len(candidates):
                missed += 1
                continue
            groups = np.split(candidates, np.where(np.diff(candidates) > 1)[0]+1)
            if len(groups) != 1:
                ambiguous += 1
                continue
            best = groups[0][np.argmax(jumps[groups[0]])]
            plateau = groups[0][jumps[groups[0]] >= jumps[best]*.9]
            offset = float(np.mean(offsets[plateau+2]))
            samples.append(offset)
            pixel = np.round(point + offset*normal).astype(int)
            cv2.circle(overlay, tuple(pixel), 1, (0, 255, 0), -1)
        result['edges'].append(dict(edge=e, attempted=80, matched=len(samples), missing=missed,
                                    ambiguous=ambiguous, match_fraction=len(samples)/80,
                                    signed_offset_px=distribution(samples), absolute_offset_px=distribution(np.abs(samples))))
    write_json(output / 'boundary.json', result)
    if not cv2.imwrite(str(output / 'boundary_overlay.png'), overlay):
        raise OSError('Could not write boundary overlay')
    return result
