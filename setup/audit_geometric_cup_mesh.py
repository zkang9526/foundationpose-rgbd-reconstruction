#!/usr/bin/env python3
"""Audit experimental geometric TSDF and optionally remove disconnected debris.

Input geometry, raw depth and estimated transforms are read-only. Silhouette
consistency uses estimated poses, not GT. Cleaning never rescales the mesh.
"""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import open3d as o3d

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--result', type=Path, required=True)
p.add_argument('--scene', type=Path, required=True)
p.add_argument('--masks', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
mesh_path = args.result / 'cup_geometric_tsdf.ply'
mesh = o3d.io.read_triangle_mesh(str(mesh_path))
vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
labels, counts, areas = mesh.cluster_connected_triangles()
labels, counts = np.asarray(labels), np.asarray(counts)
components = []
for label in np.argsort(-counts)[:8]:
    used = np.unique(faces[labels == label])
    components.append(dict(triangles=int(counts[label]), extents_m=np.ptp(vertices[used], axis=0).tolist()))
largest = int(counts.max())
remove = counts[labels] < max(30, largest * .003)
clean = o3d.geometry.TriangleMesh(mesh)
clean.remove_triangles_by_mask(remove)
clean.remove_unreferenced_vertices()
clean.compute_vertex_normals()
o3d.io.write_triangle_mesh(str(args.output / 'cup_clean.ply'), clean)
v, f, colors = np.asarray(clean.vertices), np.asarray(clean.triangles), np.asarray(clean.vertex_colors)
with (args.output / 'cup_clean.obj').open('x') as stream:
    stream.write('# meters; estimated geometric poses, with flagged interpolation; cleaned disconnected debris, no rescaling\n')
    for i, vertex in enumerate(v):
        color = colors[i] if len(colors) else np.array([.1, .5, .5])
        stream.write('v ' + ' '.join('%.9g' % value for value in np.r_[vertex, color]) + '\n')
    for triangle in f:
        stream.write('f %d %d %d\n' % tuple(triangle + 1))
K = np.loadtxt(args.scene / 'K.txt')
stats = []
for index in range(72):
    world_to_camera = np.linalg.inv(np.loadtxt(args.result / 'estimated_camera_to_model' / ('%06d.txt' % index)))
    camera = v @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    projected = camera @ K.T
    xy = np.rint(projected[:, :2] / projected[:, 2:3]).astype(np.int32)
    silhouette = np.zeros((480, 640), np.uint8)
    for triangle in f:
        if np.all(camera[triangle, 2] > .05):
            cv2.fillConvexPoly(silhouette, xy[triangle], 1)
    name = '%06d.png' % index
    observed = cv2.imread(str(args.masks / 'masks' / name), 0) > 0
    predicted = silhouette > 0
    intersection, union = np.count_nonzero(predicted & observed), np.count_nonzero(predicted | observed)
    stats.append(dict(frame=name, silhouette_iou=float(intersection / union)))
    if index in (0, 12, 24, 36, 48, 60, 71):
        image = cv2.imread(str(args.scene / 'rgb' / name))
        image[predicted & ~observed] = (0, 0, 255)
        image[observed & ~predicted] = (0, 255, 0)
        cv2.imwrite(str(args.output / ('projection_%06d.png' % index)), image)
report = dict(scope='Numeric/connected-component/silhouette consistency audit using estimated poses, not GT',
    input_sha256=hashlib.sha256(mesh_path.read_bytes()).hexdigest(), mesh_scaled=False,
    original_extents_m=np.ptp(vertices, axis=0).tolist(), components=components,
    removed_disconnected_triangles=int(remove.sum()), cleaned_extents_m=np.ptp(v, axis=0).tolist(),
    vertex_1_99_percentile_extents_m=(np.percentile(v, 99, axis=0)-np.percentile(v, 1, axis=0)).tolist(),
    mean_silhouette_iou=float(np.mean([item['silhouette_iou'] for item in stats])),
    min_silhouette_iou=min(item['silhouette_iou'] for item in stats), frames=stats,
    geometry_quality_accepted=False, obj_sha256=hashlib.sha256((args.output / 'cup_clean.obj').read_bytes()).hexdigest())
(args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ('original_extents_m', 'cleaned_extents_m', 'removed_disconnected_triangles', 'mean_silhouette_iou', 'min_silhouette_iou')}), flush=True)
