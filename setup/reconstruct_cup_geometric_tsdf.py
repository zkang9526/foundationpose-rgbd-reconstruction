#!/usr/bin/env python3
"""Experimental cup geometry initialization, ICP and depth TSDF.

Uses measured depth plane/circle/handle evidence, never planned angles. Hidden
handle orientations are interpolated from visible observations and explicitly
marked uncertain. This does not provide GT or complete unseen interior geometry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import open3d as o3d

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--scene', type=Path, required=True)
p.add_argument('--masks', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--top-y-max', type=int, default=75, help='RGB-reviewed upper plane ROI for this scene')
p.add_argument('--body-core-roi', type=int, nargs=4, default=[419,87,481,118], metavar=('X0','Y0','X1','Y1'))
p.add_argument('--body-halfspan-mm',type=float,default=80,help='Diagnostic body-depth window; original default retained')
p.add_argument('--handle-hidden-frames',type=int,nargs=2,default=[48,63],help='Inclusive RGB-reviewed hidden-handle range, not planned angles')
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
K = np.loadtxt(args.scene / 'K.txt')
rows, points_all, colors_all, depths, planes, cyan_all = [], [], [], [], [], []
o3d.utility.random.seed(0)
for index in range(72):
    name = '%06d.png' % index
    rgb = cv2.cvtColor(cv2.imread(str(args.scene / 'rgb' / name)), cv2.COLOR_BGR2RGB)
    depth = cv2.imread(str(args.scene / 'depth' / name), -1)
    mask = cv2.imread(str(args.masks / 'masks' / name), 0) > 0
    yy, xx = np.indices(depth.shape)
    valid = mask & (depth >= 300) & (depth <= 800)
    x0,y0,x1,y1=args.body_core_roi
    if not 0<=x0<x1<=640 or not 0<=y0<y1<=480:raise ValueError('Body ROI outside original image')
    body_values = depth[y0:y1,x0:x1]
    body_values = body_values[(body_values >= 300) & (body_values <= 800)]
    center_depth = float(np.median(body_values))
    if not len(body_values):raise ValueError('No body-core depth')
    rejected_far = int(np.count_nonzero(valid & (np.abs(depth.astype(float) - center_depth) > args.body_halfspan_mm)))
    valid &= np.abs(depth.astype(float) - center_depth) <= args.body_halfspan_mm
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    cyan = (hsv[:, :, 0] >= 70) & (hsv[:, :, 0] <= 105) & (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 45)
    z = depth[valid].astype(float) / 1000
    xyz = np.column_stack(((xx[valid] - K[0, 2]) * z / K[0, 0], (yy[valid] - K[1, 2]) * z / K[1, 1], z))
    top = yy[valid] < args.top_y_max
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz[top]))
    if len(cloud.points) < 100:
        raise ValueError('Too little top-plane depth')
    coefficients, inliers = cloud.segment_plane(distance_threshold=.0018, ransac_n=3, num_iterations=800)
    normal = np.asarray(coefficients[:3])
    normal /= np.linalg.norm(normal)
    if normal[1] < 0:
        normal *= -1
    planes.append((normal, xyz[top][inliers]))
    points_all.append(xyz)
    colors_all.append(rgb[valid].astype(float) / 255)
    cyan_all.append(cyan[valid])
    depths.append(np.where(valid, depth, 0).astype(np.uint16))
    rows.append(dict(frame=name, raw_rgb_sha256=hashlib.sha256((args.scene / 'rgb' / name).read_bytes()).hexdigest(),
                     raw_depth_sha256=hashlib.sha256((args.scene / 'depth' / name).read_bytes()).hexdigest(),
                     mask_sha256=hashlib.sha256((args.masks / 'masks' / name).read_bytes()).hexdigest(),
                     plane_points=len(inliers), plane_normal_camera=normal.tolist(),
                     sampled_body_depth_median_mm=center_depth, far_depth_pixels_rejected=rejected_far))
axis = np.median([n for n, _ in planes], axis=0)
axis /= np.linalg.norm(axis)
e1 = np.array([1., 0, 0]) - axis * axis[0]
e1 /= np.linalg.norm(e1)
e2 = np.cross(axis, e1)
basis = np.column_stack((e1, e2, axis))
angles = np.full(72, np.nan)
centers = []
for i, (xyz, (_, top)) in enumerate(zip(points_all, planes)):
    projected = top @ basis[:, :2]
    hull = cv2.convexHull(projected.astype(np.float32)).reshape(-1, 2).astype(float)
    A = np.column_stack((2 * hull[:, 0], 2 * hull[:, 1], np.ones(len(hull))))
    solution = np.linalg.lstsq(A, np.sum(hull**2, axis=1), rcond=None)[0]
    center_xy = solution[:2]
    radius = float(np.sqrt(max(0, solution[2] + np.sum(center_xy**2))))
    center = basis[:, :2] @ center_xy + axis * np.median(top @ axis)
    centers.append(center)
    local = (xyz - center) @ basis
    radial = np.linalg.norm(local[:, :2], axis=1)
    height = float(np.percentile(local[:, 2], 98))
    middle = (local[:, 2] > .15 * height) & (local[:, 2] < .85 * height)
    body_radius = float(np.percentile(radial[middle], 45))
    candidates = middle & cyan_all[i] & (radial > max(radius, body_radius) + .014) & (radial < max(radius, body_radius) + .055)
    unit = local[candidates, :2]
    if len(unit):
        unit = unit / np.linalg.norm(unit, axis=1, keepdims=True)
    vector = np.median(unit, axis=0) if len(unit) else np.zeros(2)
    strength = float(np.linalg.norm(vector))
    # The explicit RGB-reviewed range identifies hidden-handle observations;
    # radial depth outliers there cannot be labeled observed handle evidence.
    rgb_handle_hidden = args.handle_hidden_frames[0] <= i <= args.handle_hidden_frames[1]
    observed = len(unit) >= 45 and strength > .75 and not rgb_handle_hidden
    if observed:
        angles[i] = np.arctan2(vector[1], vector[0])
    rows[i].update(top_circle_radius_m=radius, body_radius_m=body_radius, cap_center_camera_m=center.tolist(),
        handle_candidate_points=int(candidates.sum()), handle_direction_strength=strength,
        handle_angle_observed=bool(observed), rgb_handle_hidden=rgb_handle_hidden,
        handle_yaw_radians=None if not observed else float(angles[i]))
    print('Geometry frame %d: handle=%d observed=%s radius=%.4f' % (i, candidates.sum(), observed, radius), flush=True)
observed_indices = np.flatnonzero(np.isfinite(angles))
if len(observed_indices) < 15:
    (args.output / 'geometry_diagnosis.json').write_text(json.dumps(dict(frames=rows), indent=2))
    raise ValueError('Insufficient directly observed handle orientations')
observed_angles = np.unwrap(angles[observed_indices])
all_angles = np.interp(np.arange(72), observed_indices, observed_angles)
all_angles -= all_angles[0]
span = float(np.ptp(all_angles))
if span < np.pi:
    (args.output / 'geometry_diagnosis.json').write_text(json.dumps(dict(frames=rows, angular_span_degrees=float(np.degrees(span))), indent=2))
    raise ValueError('Observed handle directions do not establish adequate rotation span')
transforms, global_points = [], []
for i, angle in enumerate(all_angles):
    c, s = np.cos(-angle), np.sin(-angle)
    Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
    transform = np.eye(4)
    transform[:3, :3] = Rz @ basis.T
    transform[:3, 3] = -transform[:3, :3] @ centers[i]
    transforms.append(transform)
    global_points.append(points_all[i] @ transform[:3, :3].T + transform[:3, 3])
target = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.concatenate(global_points)))
target = target.voxel_down_sample(.0015)
target.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=.008, max_nn=30))
volume = o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=.0015, sdf_trunc=.0075,
    color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8)
intrinsic = o3d.camera.PinholeCameraIntrinsic(640, 480, K[0, 0], K[1, 1], K[0, 2], K[1, 2])
(args.output / 'estimated_camera_to_model').mkdir()
for i, transform in enumerate(transforms):
    source = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(global_points[i])).voxel_down_sample(.0015)
    source.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=.008, max_nn=30))
    fit = o3d.pipelines.registration.registration_icp(source, target, .006, np.eye(4),
        o3d.pipelines.registration.TransformationEstimationPointToPlane(),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=30))
    correction = fit.transformation
    angle = float(np.degrees(np.arccos(np.clip((np.trace(correction[:3, :3]) - 1) / 2, -1, 1))))
    applied = angle < 7 and np.linalg.norm(correction[:3, 3]) < .004
    if applied:
        transform = correction @ transform
    np.savetxt(args.output / 'estimated_camera_to_model' / ('%06d.txt' % i), transform)
    rgb = cv2.cvtColor(cv2.imread(str(args.scene / 'rgb' / ('%06d.png' % i))), cv2.COLOR_BGR2RGB)
    rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(o3d.geometry.Image(rgb), o3d.geometry.Image(depths[i]),
        depth_scale=1000., depth_trunc=.8, convert_rgb_to_intensity=False)
    volume.integrate(rgbd, intrinsic, np.linalg.inv(transform))
    rows[i].update(estimated_yaw_degrees=float(np.degrees(all_angles[i])),
        angle_interpolated_from_visible_handle=not rows[i]['handle_angle_observed'],
        icp_fitness=float(fit.fitness), icp_rmse_m=float(fit.inlier_rmse), icp_correction_applied=bool(applied))
mesh = volume.extract_triangle_mesh()
mesh.remove_degenerate_triangles()
mesh.remove_duplicated_triangles()
mesh.remove_unreferenced_vertices()
mesh.compute_vertex_normals()
o3d.io.write_triangle_mesh(str(args.output / 'cup_geometric_tsdf.ply'), mesh)
vertices, faces, colors = np.asarray(mesh.vertices), np.asarray(mesh.triangles), np.asarray(mesh.vertex_colors)
with (args.output / 'cup_geometric_tsdf.obj').open('x') as stream:
    stream.write('# meters; raw-depth TSDF with data-derived approximate geometric poses; not GT\n')
    for i, vertex in enumerate(vertices):
        color = colors[i] if len(colors) else np.array([.1, .5, .5])
        stream.write('v ' + ' '.join('%.9g' % v for v in np.r_[vertex, color]) + '\n')
    for face in faces:
        stream.write('f %d %d %d\n' % tuple(face + 1))
report = dict(passed=True, scope='Experimental geometric-pose ICP TSDF candidate; requires visual and physical geometry review',
    body_core_roi_xyxy=args.body_core_roi,body_halfspan_mm=args.body_halfspan_mm,
    top_y_max=args.top_y_max,handle_hidden_frames_rgb_review=args.handle_hidden_frames,
    raw_sources_modified=False, planned_angles_used=False, poses_are_ground_truth=False,
    directly_observed_handle_frames=int(len(observed_indices)), interpolated_handle_frames=72-int(len(observed_indices)),
    angular_span_degrees=float(np.degrees(span)), axis_camera=axis.tolist(), frames=rows,
    vertices=len(vertices), faces=len(faces), extents_m=(vertices.max(axis=0)-vertices.min(axis=0)).tolist(),
    obj_sha256=hashlib.sha256((args.output / 'cup_geometric_tsdf.obj').read_bytes()).hexdigest(),
    mesh_quality_validated=False, unseen_interior_not_observed=True)
(args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ('passed', 'directly_observed_handle_frames', 'interpolated_handle_frames', 'angular_span_degrees', 'vertices', 'faces', 'extents_m')}), flush=True)
