#!/usr/bin/env python3
"""Create a separate lightly filtered cloud; never change saved RGB-D, ICP poses or mesh."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clouds', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    original = (a.clouds/'after_rgb.bin').read_bytes()
    source_sha = hashlib.sha256(original).hexdigest()
    manifest = json.loads((a.clouds/'manifest.json').read_text())
    if source_sha != manifest['artifacts']['after_rgb']['sha256']:
        raise ValueError('Original cloud SHA differs')
    data = np.frombuffer(original, dtype=[('x','<f4'),('y','<f4'),('z','<f4'),('rgb','<u4')])
    xyz = np.column_stack([data[k] for k in ('x','y','z')]).astype(float)
    color = data['rgb']
    rgb = np.column_stack([(color>>16)&255, (color>>8)&255, color&255])/255.
    if not np.isfinite(xyz).all():
        raise ValueError('Nonfinite source points')
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz))
    cloud.colors = o3d.utility.Vector3dVector(rgb)
    voxel = cloud.voxel_down_sample(.001)
    clean, indices = voxel.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.5)
    if len(clean.points) < 100:
        raise ValueError('Insufficient filtered points')
    points = np.asarray(clean.points).copy()
    colors = np.asarray(clean.colors).copy()
    tree = cKDTree(points)
    smooth = points.copy()
    eligible_count = 0
    # One conservative normal-only projection to a weighted local plane.
    # Small/line-like/nonplanar neighborhoods are retained rather than rounded.
    for start in range(0, len(points), 2048):
        stop = min(start+2048, len(points))
        center = points[start:stop]
        distance, index = tree.query(center, k=min(160, len(points)), distance_upper_bound=.006, workers=1)
        valid = np.isfinite(distance)
        neighbors = points[np.minimum(index, len(points)-1)]
        weights = np.exp(-np.where(valid, distance, 1.)**2/(2*.003**2))*valid
        mean = (neighbors*weights[:,:,None]).sum(axis=1)/weights.sum(axis=1)[:,None]
        delta = neighbors-mean[:,None,:]
        covariance = np.einsum('bki,bkj,bk->bij', delta, delta, weights)/weights.sum(axis=1)[:,None,None]
        eig, vectors = np.linalg.eigh(covariance)
        normal = vectors[:,:,0]
        good = ((valid.sum(axis=1)>=10) & (eig[:,0]/np.maximum(eig.sum(axis=1),1e-20)<.15)
                & (eig[:,1]/np.maximum(eig[:,2],1e-20)>.12))
        offset = np.einsum('bi,bi->b', center-mean, normal)
        step = np.clip(.5*offset, -.0005, .0005)
        smooth[start:stop] -= (step*good)[:,None]*normal
        eligible_count += int(good.sum())
    a.output.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for name, positions, label in [('denoised_rgb',points,'1 mm体素＋去离群点'),
                                    ('filtered_rgb',smooth,'轻度平滑 · RGB')]:
        packed = np.empty(len(positions),dtype=data.dtype)
        for j, key in enumerate(('x','y','z')):
            packed[key] = positions[:,j]
        values = np.rint(np.clip(colors,0,1)*255).astype(np.uint32)
        packed['rgb'] = (values[:,0]<<16)|(values[:,1]<<8)|values[:,2]
        raw = packed.tobytes()
        (a.output/(name+'.bin')).write_bytes(raw)
        header = ('# .PCD v0.7\nVERSION 0.7\nFIELDS x y z rgb\nSIZE 4 4 4 4\nTYPE F F F U\nCOUNT 1 1 1 1\n'
                  f'WIDTH {len(packed)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(packed)}\nDATA binary\n')
        (a.output/(name+'.pcd')).write_bytes(header.encode()+raw)
        export = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(positions))
        export.colors = o3d.utility.Vector3dVector(colors)
        o3d.io.write_point_cloud(str(a.output/(name+'.ply')),export)
        artifacts[name] = dict(points=len(packed),sha256=hashlib.sha256(raw).hexdigest(),label=label,
                               bounds_m=[positions.min(axis=0).tolist(),positions.max(axis=0).tolist()])
    movement = np.linalg.norm(smooth-points,axis=1)*1000
    result = dict(scope='Light filtering of saved ICP-aligned observed points; derived geometry, not accuracy validation.',
                  source_after_rgb_sha256=source_sha, units='meters', frame_id='cup_model',
                  source_points=len(xyz), voxel_points=len(voxel.points), filtered_points=len(points),
                  statistical_outliers_removed=len(voxel.points)-len(points),
                  settings=dict(voxel_mm=1.,statistical_neighbors=20,statistical_std_ratio=2.5,
                                smooth_radius_mm=6.,gaussian_sigma_mm=3.,max_neighbors=160,min_neighbors=10,iterations=1,
                                max_surface_variation=.15,min_tangent_eigenvalue_ratio=.12,
                                normal_projection_fraction=.5,max_smoothing_displacement_mm=.5),
                  smoothing_eligible_points=eligible_count,
                  smoothing_displacement_mm=dict(median=float(np.median(movement)),p95=float(np.percentile(movement,95)),max=float(movement.max())),
                  artifacts=artifacts, original_modified=False,mesh_modified=False,poses_modified=False)
    if movement.max() > .50001 or not np.isfinite(smooth).all():
        raise ValueError('Smoothing displacement/finite check failed')
    if hashlib.sha256((a.clouds/'after_rgb.bin').read_bytes()).hexdigest() != source_sha:
        raise ValueError('Source changed during filtering')
    (a.output/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
