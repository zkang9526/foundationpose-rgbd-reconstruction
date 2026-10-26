#!/usr/bin/env python3
"""Verify downloaded pilot evidence and export crops plus metric R/t; no pose GT."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(path, expected):
    if sha(path) != expected:
        raise ValueError('Evidence hash mismatch: ' + str(path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('inference', 'projection', 'scene', 'mask-dir', 'mesh', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Output must be new; previous evidence is preserved')
    import numpy as np
    from PIL import Image, ImageDraw
    inf = json.loads((args.inference / 'report.json').read_text(encoding='utf-8'))
    proj = json.loads((args.projection / 'report.json').read_text(encoding='utf-8'))
    if not inf.get('passed') or inf.get('completed_frames') != 5 or not proj.get('passed'):
        raise ValueError('Requires completed five-frame inference and projection review')
    checked(args.inference / 'report.json', proj['inference_report_sha256'])
    checked(args.mesh, inf['source_mesh']['sha256'])
    if proj['mesh_sha256'] != inf['source_mesh']['sha256']:
        raise ValueError('Inference and projection use different meshes')
    projections = {r['frame']: r for r in proj['frames']}
    rows, tiles, sources = [], [], []
    for frame in inf['frames']:
        stem = frame['id']
        pr = projections[stem]
        rgb = args.scene / 'rgb' / (stem + '.png')
        depth = args.scene / 'depth' / (stem + '.png')
        mask = args.mask_dir / 'masks' / (stem + '.png')
        posefile = args.inference / 'poses' / (stem + '.txt')
        axes = args.inference / 'visualizations' / (stem + '.png')
        overlay = args.projection / 'overlays' / (stem + '.png')
        silhouette = args.projection / 'projected_silhouettes' / (stem + '.png')
        for path, expected in ((rgb, frame['inputs']['rgb']['sha256']),
                               (depth, frame['inputs']['depth']['sha256']),
                               (mask, frame['inputs']['mask']['sha256']),
                               (posefile, frame['pose']['sha256']),
                               (axes, frame['visualization']['sha256']),
                               (overlay, pr['overlay_sha256']),
                               (silhouette, pr['projected_silhouette_sha256'])):
            checked(path, expected)
            sources.append(dict(path=str(path.resolve()), sha256=expected))
        T = np.loadtxt(posefile)
        if (T.shape != (4, 4) or not np.isfinite(T).all()
                or not np.allclose(T[3], [0, 0, 0, 1], atol=1e-5)
                or not np.allclose(T[:3, :3].T @ T[:3, :3], np.eye(3), atol=1e-4)
                or abs(np.linalg.det(T[:3, :3]) - 1) > 1e-4 or T[2, 3] <= 0):
            raise ValueError('Invalid rigid object-to-camera estimate: ' + stem)
        target = np.asarray(Image.open(mask)) > 0
        union = target | (np.asarray(Image.open(silhouette)) > 0)
        yy, xx = np.nonzero(union)
        rgbimage = Image.open(rgb).convert('RGB')
        box = (max(0, int(xx.min()) - 18), max(0, int(yy.min()) - 18),
               min(rgbimage.width, int(xx.max()) + 19),
               min(rgbimage.height, int(yy.max()) + 19))
        tile = Image.new('RGB', (330, 1050), 'white')
        draw = ImageDraw.Draw(tile)
        for row, path, title in ((0, rgb, 'Source RGB ' + stem),
                                 (1, overlay, 'Mask yellow / mesh magenta'),
                                 (2, axes, 'OBB axes: display frame only')):
            crop = Image.open(path).convert('RGB').crop(box)
            scale = min(320 / crop.width, 315 / crop.height)
            crop = crop.resize((max(1, round(crop.width * scale)),
                                max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
            tile.paste(crop, ((330 - crop.width) // 2, row * 350 + 30))
            draw.text((7, row * 350 + 7), title, fill='black')
        draw.text((7, 1030), 'Silhouette IoU %.3f; NO pose GT' % pr['manual_silhouette_overlap_iou'], fill='black')
        tiles.append(tile)
        rows.append(dict(frame=stem, rotation_matrix_camera_from_mesh=T[:3, :3].tolist(),
                         translation_camera_from_mesh_m=T[:3, 3].tolist(),
                         manual_silhouette_overlap_iou=pr['manual_silhouette_overlap_iou'],
                         pose_sha256=sha(posefile), pose_is_ground_truth=False,
                         pose_accuracy_validated=False))
    args.output.mkdir(parents=True, exist_ok=False)
    sheet = Image.new('RGB', (330 * len(tiles), 1090), 'white')
    ImageDraw.Draw(sheet).text((10, 10), 'Official pretrained FoundationPose: 5 independent register calls. Candidate mesh has holes. No metric accuracy acceptance.', fill='black')
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (i * 330, 40))
    sheetpath = args.output / 'comparison_5views.png'
    sheet.save(sheetpath)
    csvpath = args.output / 'poses_6d.csv'
    with csvpath.open('x', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['frame', 'tx_m', 'ty_m', 'tz_m'] +
                        ['r%d%d' % (i, j) for i in range(1, 4) for j in range(1, 4)] +
                        ['silhouette_iou_not_pose_accuracy'])
        for row in rows:
            writer.writerow([row['frame']] + row['translation_camera_from_mesh_m'] +
                            np.asarray(row['rotation_matrix_camera_from_mesh']).ravel().tolist() +
                            [row['manual_silhouette_overlap_iou']])
    report = dict(passed=True, scope='Evidence transfer verification and export only',
                  mean_manual_silhouette_overlap_iou=float(np.mean([r['manual_silhouette_overlap_iou'] for r in rows])),
                  pose_definition=inf['mesh_coordinates']['pose_definition'],
                  equation='p_camera_m = R @ p_original_mesh_m + t_m',
                  camera_axes='OpenCV: x right, y down, z forward',
                  object_frame='Original candidate mesh origin and axes; not calibrated robot or world frame',
                  ground_truth_available=False, pose_accuracy_validated=False,
                  official_top_rank_changed=False, planned_angles_used=False,
                  source_mesh_sha256=sha(args.mesh), inference_report_sha256=sha(args.inference / 'report.json'),
                  projection_report_sha256=sha(args.projection / 'report.json'),
                  verified_sources=sources, frames=rows,
                  artifacts={sheetpath.name: sha(sheetpath), csvpath.name: sha(csvpath)})
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, frames=len(rows), output=str(args.output),
                         mean_silhouette_iou=report['mean_manual_silhouette_overlap_iou'],
                         pose_accuracy_validated=False)))


if __name__ == '__main__':
    main()
