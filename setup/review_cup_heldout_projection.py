#!/usr/bin/env python3
"""CPU silhouette review of estimated cup poses; no pose GT or accuracy metric."""
import argparse
import hashlib
import json
from pathlib import Path
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inference', type=Path, required=True)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--mask-dir', type=Path, required=True)
    p.add_argument('--mesh', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Output must be new; retained evidence is not overwritten')
    import cv2
    import numpy as np
    started = time.monotonic()
    source_report = json.loads((args.inference / 'report.json').read_text(encoding='utf-8'))
    if source_report.get('passed') is not True or source_report.get('completed_frames') != 5:
        raise ValueError('Need completed five-frame neural inference report')
    if sha(args.mesh) != source_report['source_mesh']['sha256']:
        raise ValueError('Mesh changed after inference')
    vertices, faces = [], []
    for line in args.mesh.read_text(encoding='utf-8').splitlines():
        parts = line.split()
        if parts and parts[0] == 'v':
            vertices.append([float(x) for x in parts[1:4]])
        elif parts and parts[0] == 'f':
            ids = [int(x.split('/')[0]) - 1 for x in parts[1:]]
            if any(x < 0 for x in ids):
                raise ValueError('Unsupported relative OBJ index')
            faces.extend([[ids[0], ids[i], ids[i + 1]] for i in range(1, len(ids) - 1)])
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    vertices *= source_report['mesh_coordinates']['source_vertex_to_meter_scale']
    K = np.asarray(source_report['camera_matrix'])
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'overlays').mkdir()
    (args.output / 'projected_silhouettes').mkdir()
    frames = []
    report = {'passed': False, 'method': 'CPU union of projected mesh triangles at saved estimated pose',
              'manual_mask_overlap_is_not_6d_accuracy': True, 'ground_truth_available': False,
              'pose_accuracy_validated': False, 'network_inference_reexecuted': False,
              'mesh_sha256': sha(args.mesh), 'inference_report_sha256': sha(args.inference / 'report.json'),
              'frames': frames, 'requires_visual_review': True}
    for item in source_report['frames']:
        stem = item['id']
        filename = stem + '.png'
        rgb_path, mask_path, pose_path = (args.scene / 'rgb' / filename,
                                        args.mask_dir / 'masks' / filename,
                                        args.inference / 'poses' / (stem + '.txt'))
        for source, expected in ((rgb_path, item['inputs']['rgb']['sha256']),
                                 (mask_path, item['inputs']['mask']['sha256']),
                                 (pose_path, item['pose']['sha256'])):
            if sha(source) != expected:
                raise ValueError('Source changed: ' + str(source))
        image = cv2.imread(str(rgb_path))
        target = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED) > 0
        pose = np.loadtxt(pose_path).reshape(4, 4)
        points = vertices @ pose[:3, :3].T + pose[:3, 3]
        if not np.isfinite(points).all() or np.min(points[:, 2]) <= 0:
            raise ValueError('Projected mesh not finite and wholly in front of camera')
        projected = points @ K.T
        projected = projected[:, :2] / projected[:, 2:3]
        rendered = np.zeros(target.shape, dtype=np.uint8)
        integer = np.rint(np.clip(projected, -1e6, 1e6)).astype(np.int32)
        for triangle in integer[faces]:
            cv2.fillConvexPoly(rendered, triangle, 255)
        predicted = rendered > 0
        intersection = int(np.count_nonzero(predicted & target))
        union = int(np.count_nonzero(predicted | target))
        false_positive = int(np.count_nonzero(predicted & ~target))
        false_negative = int(np.count_nonzero(target & ~predicted))
        colored = image.copy()
        colored[predicted] = (0.70 * colored[predicted] + 0.30 * np.array([255, 0, 255])).astype(np.uint8)
        for binary, color in ((rendered, (255, 0, 255)), (target.astype(np.uint8) * 255, (0, 255, 255))):
            contours = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
            cv2.drawContours(colored, contours, -1, color, 1)
        cv2.putText(colored, 'Yellow: manual mask; Magenta: estimated mesh', (7, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(colored, 'Qualitative projection only; no pose GT', (7, 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)
        overlay = args.output / 'overlays' / filename
        silhouette = args.output / 'projected_silhouettes' / filename
        if not cv2.imwrite(str(overlay), colored) or not cv2.imwrite(str(silhouette), rendered):
            raise RuntimeError('Could not save projection evidence')
        frames.append({'frame': stem, 'estimated_pose_sha256': sha(pose_path),
                       'mask_pixels': int(target.sum()), 'projected_pixels': int(predicted.sum()),
                       'manual_silhouette_overlap_iou': intersection / union if union else None,
                       'mesh_outside_manual_mask_pixels': false_positive,
                       'manual_mask_uncovered_pixels': false_negative,
                       'mesh_vertex_z_range_m': [float(points[:, 2].min()), float(points[:, 2].max())],
                       'overlay': str(overlay), 'overlay_sha256': sha(overlay),
                       'projected_silhouette_sha256': sha(silhouette),
                       'pose_is_ground_truth': False, 'accuracy_validated': False})
    report.update(passed=True, elapsed_seconds=time.monotonic() - started)
    with (args.output / 'report.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    print(json.dumps({'passed': True, 'frames': len(frames), 'output': str(args.output),
                      'pose_accuracy_validated': False,
                      'manual_silhouette_overlap': [x['manual_silhouette_overlap_iou'] for x in frames]}))


if __name__ == '__main__':
    main()
