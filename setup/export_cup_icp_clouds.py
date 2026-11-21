#!/usr/bin/env python3
"""Recover observed RGB-D points using saved reconstruction transforms, without rerunning ICP."""
import argparse
import colorsys
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from cup_reconstruction_depth import selected_depth_mask


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('scene', 'masks', 'result', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--frame-step', type=int, default=1)
    a = p.parse_args()
    if a.frame_step < 1:
        p.error('frame-step must be positive')
    report = json.loads((a.result / 'report.json').read_text())
    K = np.loadtxt(a.scene / 'K.txt')
    axis = np.asarray(report['axis_camera'], dtype=float)
    axis /= np.linalg.norm(axis)
    e1 = np.array([1., 0, 0]) - axis * axis[0]
    e1 /= np.linalg.norm(e1)
    basis = np.column_stack((e1, np.cross(axis, e1), axis))
    clouds = {k: [] for k in ('after_rgb', 'after_frames', 'before_frames')}
    records = []
    for i, row in enumerate(report['frames']):
        if i % a.frame_step:
            continue
        name = row['frame']
        paths = [a.scene / 'rgb' / name, a.scene / 'depth' / name, a.masks / 'masks' / name]
        hashes = [sha(q) for q in paths]
        expected = [row[k] for k in ('raw_rgb_sha256', 'raw_depth_sha256', 'mask_sha256')]
        if hashes != expected:
            raise ValueError('Input differs from saved reconstruction: ' + name)
        rgb = cv2.cvtColor(cv2.imread(str(paths[0])), cv2.COLOR_BGR2RGB)
        depth = cv2.imread(str(paths[1]), -1)
        mask = cv2.imread(str(paths[2]), 0) > 0
        valid = selected_depth_mask(depth,mask,report,row)
        y, x = np.nonzero(valid)
        z = depth[valid].astype(float) / 1000
        points = np.column_stack(((x-K[0, 2])*z/K[0, 0], (y-K[1, 2])*z/K[1, 1], z))
        pose_path = a.result / 'estimated_camera_to_model' / (Path(name).stem + '.txt')
        T = np.loadtxt(pose_path)
        if T.shape != (4, 4) or not np.isfinite(T).all():
            raise ValueError('Invalid saved transform: ' + str(pose_path))
        after = points @ T[:3, :3].T + T[:3, 3]
        angle = -np.radians(row['estimated_yaw_degrees'])
        c, s = np.cos(angle), np.sin(angle)
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ basis.T
        before = (points - row['cap_center_camera_m']) @ R.T
        color = (np.asarray(colorsys.hsv_to_rgb(i / len(report['frames']), .8, 1))*255).astype(np.uint32)
        frame_rgb = np.full(len(points), (color[0]<<16) | (color[1]<<8) | color[2], dtype='<u4')
        source_rgb = rgb[valid].astype(np.uint32)
        packed = (source_rgb[:, 0]<<16) | (source_rgb[:, 1]<<8) | source_rgb[:, 2]
        for key, xyz, col in [('after_rgb', after, packed), ('after_frames', after, frame_rgb), ('before_frames', before, frame_rgb)]:
            data = np.empty(len(points), dtype=[('x','<f4'),('y','<f4'),('z','<f4'),('rgb','<u4')])
            for j, field in enumerate(('x', 'y', 'z')):
                data[field] = xyz[:, j]
            data['rgb'] = col
            clouds[key].append(data)
        records.append(dict(frame=name, points=len(points), pose_sha256=sha(pose_path), input_sha256=hashes,
                            icp_correction_applied=row['icp_correction_applied'],
                            direction_interpolated=row['angle_interpolated_from_visible_handle']))
    if not records:
        raise ValueError('No frames')
    a.output.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for key, chunks in clouds.items():
        data = np.concatenate(chunks)
        raw = data.tobytes()
        (a.output / (key + '.bin')).write_bytes(raw)
        header = ('# .PCD v0.7\nVERSION 0.7\nFIELDS x y z rgb\nSIZE 4 4 4 4\nTYPE F F F U\nCOUNT 1 1 1 1\n'
                  f'WIDTH {len(data)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(data)}\nDATA binary\n')
        (a.output / (key + '.pcd')).write_bytes(header.encode() + raw)
        xyz = np.column_stack([data[n] for n in ('x','y','z')])
        artifacts[key] = dict(points=len(data), sha256=hashlib.sha256(raw).hexdigest(),
                              bounds_m=[xyz.min(axis=0).tolist(), xyz.max(axis=0).tolist()])
    out = dict(scope='Actual masked depth points transformed by saved geometric+bounded-ICP poses; before TSDF. Not GT.',
               before_scope='Before ICP means geometry-initialized, not unaligned camera coordinates.',
               result_report_sha256=sha(a.result/'report.json'), K_sha256=sha(a.scene/'K.txt'),
               depth_selection=dict(mask_erode_pixels=report.get('mask_erode_pixels',0),
                   depth_consistency_mm=report.get('depth_consistency_mm',0)),
               frame_id='cup_model', units='meters', frames=records, artifacts=artifacts)
    (a.output/'manifest.json').write_text(json.dumps(out, indent=2)+'\n')
    print(json.dumps(dict(output=str(a.output), frames=len(records), artifacts=artifacts)))


if __name__ == '__main__':
    main()
