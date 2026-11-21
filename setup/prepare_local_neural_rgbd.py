#!/usr/bin/env python3
"""Freeze reviewed local72 RGB-D and estimated ICP poses for neural fitting."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reconstruction', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reconstruction = args.reconstruction.resolve(strict=True)
    job = json.loads((reconstruction/'job.json').read_text())
    scene = Path(job['scene'])
    masks = reconstruction/'reviewed_snapshot/masks'
    geometry = reconstruction/'rgb_cap_geometry_v1'
    report = json.loads((geometry/'report.json').read_text())
    if not report['passed'] or report['planned_angles_used']:
        raise ValueError('Expected successful estimated geometric reconstruction')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in ('rgb', 'depth', 'masks', 'estimated_camera_to_model'):
        (output/name).mkdir()
    K = np.loadtxt(scene/'K.txt')
    np.savetxt(output/'K.txt', K, fmt='%.12g')
    (output/'depth_scale.txt').write_text('0.001\n')
    rows = []
    sources = []
    points = []
    for index in range(72):
        stem = f'{index:06d}'
        rgb_path, depth_path = scene/'rgb'/(stem+'.png'), scene/'depth'/(stem+'.png')
        mask_path, pose_path = masks/(stem+'.png'), geometry/'estimated_camera_to_model'/(stem+'.txt')
        recorded = report['frames'][index]
        for path, expected in [(rgb_path, recorded['raw_rgb_sha256']),
                               (depth_path, recorded['raw_depth_sha256']), (mask_path, recorded['mask_sha256'])]:
            if sha(path) != expected:
                raise ValueError('Source changed after reviewed reconstruction: '+str(path))
        depth, mask = cv2.imread(str(depth_path), -1), cv2.imread(str(mask_path), 0)
        if depth.dtype != np.uint16 or not set(np.unique(mask)).issubset({0, 255}):
            raise ValueError('Expected millimeter uint16 depth and binary mask')
        valid = (mask > 0) & (depth >= 300) & (depth <= 800)
        x0, y0, x1, y1 = report['body_core_roi_xyxy']
        core = depth[y0:y1, x0:x1]
        core = core[(core >= 300) & (core <= 800)]
        if len(core) == 0:
            raise ValueError('Body depth ROI empty')
        valid &= np.abs(depth.astype(float)-np.median(core)) <= report['body_halfspan_mm']
        median = cv2.medianBlur(depth, 3)
        neighbors = cv2.boxFilter((depth > 0).astype(np.float32), -1, (3, 3), normalize=False)
        valid &= (neighbors >= 5) & (np.abs(depth.astype(float)-median.astype(float)) <= report['depth_consistency_mm'])
        filtered = np.where(valid, depth, 0).astype(np.uint16)
        cv2.imwrite(str(output/'depth'/(stem+'.png')), filtered)
        shutil.copy2(rgb_path, output/'rgb'/(stem+'.png'))
        shutil.copy2(mask_path, output/'masks'/(stem+'.png'))
        shutil.copy2(pose_path, output/'estimated_camera_to_model'/(stem+'.txt'))
        transform = np.loadtxt(pose_path)
        if (transform.shape != (4, 4) or not np.isfinite(transform).all()
                or not np.allclose(transform[3], [0, 0, 0, 1])
                or not np.allclose(transform[:3, :3].T@transform[:3, :3], np.eye(3), atol=1e-5)):
            raise ValueError('Invalid estimated rigid transform')
        yy, xx = np.nonzero(valid)
        z = depth[valid].astype(float)*.001
        camera = np.column_stack(((xx-K[0, 2])*z/K[0, 0], (yy-K[1, 2])*z/K[1, 1], z))
        model = camera @ transform[:3, :3].T+transform[:3, 3]
        points.append(model[::8])
        rows.append(dict(frame=stem, valid_depth_pixels=int(valid.sum()), mask_pixels=int((mask > 0).sum()),
                         prepared_depth_sha256=sha(output/'depth'/(stem+'.png'))))
        sources.extend(dict(path=str(path), sha256=sha(path)) for path in (rgb_path, depth_path, mask_path, pose_path))
    cloud = np.concatenate(points)
    bounds = np.percentile(cloud, [.5, 99.5], axis=0)
    result = dict(passed=True, source_scene=str(scene), source_reconstruction=str(reconstruction),
                  raw_sources_modified=False, source_files=sources, frames=rows,
                  pose_definition='T_model_from_camera, OpenCV, estimated ICP', poses_are_gt=False,
                  existing_mesh_used=False, planned_angles_used=False,
                  depth_filter='Existing masked300..800mm, core median +/-80mm,3x3 consistency6mm; original depths preserved',
                  robust_model_bounds_m=bounds.tolist(),
                  robust_model_extents_mm=((bounds[1]-bounds[0])*1000).tolist(),
                  user_review='54 saved revisions +18 user-approved drafts from2026-11-12')
    (output/'source_manifest.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(output=str(output), frames=72, robust_extents_mm=result['robust_model_extents_mm'],
                         mean_valid_depth_fraction=float(np.mean([row['valid_depth_pixels']/row['mask_pixels'] for row in rows]))), indent=2))


if __name__ == '__main__':
    main()
