"""Compare bounded handle-only Taubin smoothing against the saved RGB-D views."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np
import open3d as o3d

from evaluate_cup_mesh_candidates import save, topology


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def region_weights(vertices, direction):
    along = vertices[:, :2] @ direction
    tangent = vertices[:, :2] @ np.array([-direction[1], direction[0]])
    outward = np.clip((along - .037) / .013, 0, 1)
    transverse = np.clip((.035 - np.abs(tangent)) / .010, 0, 1)
    return outward * transverse


def edge_angles(mesh, weights):
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    triangles = vertices[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-20)
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    face_ids = np.tile(np.arange(len(faces)), 3)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    sorted_edges = edges[order]
    duplicate = np.all(sorted_edges[1:] == sorted_edges[:-1], axis=1)
    pairs = np.flatnonzero(duplicate)
    handle = weights[sorted_edges[pairs]].mean(axis=1) > .5
    pairs = pairs[handle]
    angles = np.degrees(np.arccos(np.clip(np.sum(normals[face_ids[order[pairs]]] *
        normals[face_ids[order[pairs + 1]]], axis=1), -1, 1)))
    return dict(shared_handle_edges=len(angles),
                dihedral_degrees_percentiles=np.percentile(angles, [50, 90, 95, 99]).tolist())


def candidate(base, weights, boundary, iterations, limit_mm):
    vertices = np.asarray(base.vertices).copy()
    smoothed = base.filter_smooth_taubin(number_of_iterations=iterations, lambda_filter=.5, mu=-.53,
                                        filter_scope=o3d.geometry.FilterScope.Vertex)
    delta = (np.asarray(smoothed.vertices) - vertices) * weights[:, None]
    limits = np.full(len(vertices), limit_mm / 1000)
    limits[boundary] = min(limit_mm, .6) / 1000
    delta *= np.minimum(1, limits / np.maximum(np.linalg.norm(delta, axis=1), 1e-20))[:, None]
    faces = np.asarray(base.triangles)
    old_triangles = vertices[faces]
    old_normal = np.cross(old_triangles[:, 1] - old_triangles[:, 0], old_triangles[:, 2] - old_triangles[:, 0])
    old_area_twice = np.linalg.norm(old_normal, axis=1)
    meaningful = old_area_twice > 1e-18
    # Reduce local steps around skinny triangles before committing the vertices.
    # This keeps the displacement cap compatible with the retained face winding.
    reduced_vertices = np.zeros(len(vertices), dtype=bool)
    for _ in range(40):
        triangles = (vertices + delta)[faces]
        normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        folded = meaningful & ((np.sum(old_normal * normals, axis=1) <= 0) |
                              (np.linalg.norm(normals, axis=1) < old_area_twice * .05))
        if not folded.any():
            break
        affected = np.unique(faces[folded])
        reduced_vertices[affected] = True
        delta[affected] *= .5
    smoothed.vertices = o3d.utility.Vector3dVector(vertices + delta)
    smoothed.vertex_colors = copy.deepcopy(base.vertex_colors)
    smoothed.compute_vertex_normals()
    assert np.array_equal(np.asarray(smoothed.triangles), np.asarray(base.triangles))
    assert np.array_equal(np.asarray(smoothed.vertices)[weights == 0], vertices[weights == 0])
    assert np.isfinite(np.asarray(smoothed.vertices)).all()
    new_triangles = np.asarray(smoothed.vertices)[np.asarray(smoothed.triangles)]
    new_normal = np.cross(new_triangles[:, 1] - new_triangles[:, 0], new_triangles[:, 2] - new_triangles[:, 0])
    normal_dot = np.sum(old_normal * new_normal, axis=1)
    movement = np.linalg.norm(delta, axis=1) * 1000
    info, _ = topology(smoothed)
    return smoothed, dict(iterations=iterations, max_vertex_displacement_mm=limit_mm,
        max_boundary_displacement_mm=min(limit_mm, .6), changed_vertices=int((movement > 1e-8).sum()),
        fixed_vertices=int((weights == 0).sum()), movement_mm_percentiles=np.percentile(movement[weights > 0], [50, 95, 100]).tolist(),
        locally_reduced_step_vertices=int(reduced_vertices.sum()),
        reversed_face_normals=int(np.count_nonzero(meaningful & (normal_dot < 0))),
        minimum_triangle_area_mm2=float(np.linalg.norm(new_normal, axis=1).min() * 500000),
        topology=info, edge_angles=edge_angles(smoothed, weights))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('mesh', 'geometry-report', 'scene', 'masks', 'poses', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    evidence = {str(path): sha(path) for path in [args.mesh, args.geometry_report, args.scene / 'K.txt']}
    geometry = json.loads(args.geometry_report.read_text())
    assert geometry['frames'][0]['handle_angle_observed']
    angle = geometry['frames'][0]['handle_yaw_radians']
    direction = np.array([np.cos(angle), np.sin(angle)])
    base = o3d.io.read_triangle_mesh(str(args.mesh))
    weights = region_weights(np.asarray(base.vertices), direction)
    base_topology, boundary = topology(base)
    assert (weights > .5).sum() > 100
    meshes = dict(original=base)
    processing = dict(original=dict(topology=base_topology, edge_angles=edge_angles(base, weights)))
    for name, iterations, limit in [('light', 8, .8), ('medium', 25, 1.5), ('strong', 60, 2.5)]:
        meshes[name], processing[name] = candidate(base, weights, boundary, iterations, limit)
        assert processing[name]['topology']['boundary_edges'] == base_topology['boundary_edges']
        assert processing[name]['topology']['nonmanifold_edges'] == base_topology['nonmanifold_edges']
        save(meshes[name], args.output / name)
    K = np.loadtxt(args.scene / 'K.txt')
    yy, xx = np.indices((480, 640))
    pixel = np.stack([(xx + .5 - K[0, 2]) / K[0, 0], (yy + .5 - K[1, 2]) / K[1, 1], np.ones_like(xx)], axis=-1)
    scenes = {}
    for key, mesh in meshes.items():
        scene = o3d.t.geometry.RaycastingScene()
        scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
        scenes[key] = scene
    frames = {key: [] for key in meshes}
    for index in range(72):
        name = '%06d.png' % index
        rgb_path, depth_path = args.scene / 'rgb' / name, args.scene / 'depth' / name
        mask_path, pose_path = args.masks / 'masks' / name, args.poses / ('%06d.txt' % index)
        for path in (rgb_path, depth_path, mask_path, pose_path):
            evidence[str(path)] = sha(path)
        rgb, measured = cv2.imread(str(rgb_path)), cv2.imread(str(depth_path), -1).astype(float) / 1000
        mask = cv2.imread(str(mask_path), 0) > 0
        T = np.loadtxt(pose_path)
        rays = o3d.t.geometry.RaycastingScene.create_rays_pinhole(intrinsic_matrix=o3d.core.Tensor(K),
            extrinsic_matrix=o3d.core.Tensor(np.linalg.inv(T)), width_px=640, height_px=480)
        depths = {key: scene.cast_rays(rays, nthreads=2)['t_hit'].numpy() for key, scene in scenes.items()}
        z = depths['original']
        camera = pixel * np.where(np.isfinite(z), z, 0)[..., None]
        world = camera @ T[:3, :3].T + T[:3, 3]
        handle = mask & np.isfinite(z) & (region_weights(world.reshape(-1, 3), direction).reshape(mask.shape) > .5)
        for key, depth in depths.items():
            predicted = np.isfinite(depth) & (depth > 0)
            overlap = predicted & mask & (measured > 0)
            residual = np.abs(depth[overlap] - measured[overlap]) * 1000
            handle_overlap = overlap & handle
            frames[key].append(dict(frame=name, mask_iou=float((predicted & mask).sum() / (predicted | mask).sum()),
                median_depth_residual_mm=float(np.median(residual)), handle_pixels=int(handle.sum()),
                handle_coverage=float((predicted & handle).sum() / max(1, handle.sum())),
                handle_depth_residual_mm=float(np.median(np.abs(depth[handle_overlap] - measured[handle_overlap]) * 1000)) if handle_overlap.any() else None))
            if index in (0, 12, 24, 36, 48, 60, 71):
                preview = rgb.copy()
                preview[predicted & ~mask] = (0, 0, 255)
                preview[mask & ~predicted] = (0, 255, 0)
                cv2.imwrite(str(args.output / (key + '_projection_%06d.png' % index)), preview)
        if index % 12 == 0:
            print('Compared %d/72 views' % index, flush=True)
    summary = {}
    for key, rows in frames.items():
        handles = [row for row in rows if row['handle_pixels'] >= 20 and row['handle_depth_residual_mm'] is not None]
        summary[key] = dict(mean_iou=float(np.mean([row['mask_iou'] for row in rows])),
            median_frame_depth_mm=float(np.median([row['median_depth_residual_mm'] for row in rows])),
            mean_handle_coverage=float(np.mean([row['handle_coverage'] for row in handles])),
            median_handle_depth_mm=float(np.median([row['handle_depth_residual_mm'] for row in handles])),
            handle_views=len(handles))
    reference = summary['original']
    acceptance = {}
    for key in ('light', 'medium', 'strong'):
        current = summary[key]
        acceptance[key] = dict(passed=current['mean_iou'] >= reference['mean_iou'] - .003 and
            current['median_frame_depth_mm'] <= reference['median_frame_depth_mm'] + .2 and
            current['mean_handle_coverage'] >= reference['mean_handle_coverage'] - .015 and
            current['median_handle_depth_mm'] <= reference['median_handle_depth_mm'] + .5 and
            processing[key]['reversed_face_normals'] == 0,
            iou_change=current['mean_iou'] - reference['mean_iou'],
            handle_coverage_change=current['mean_handle_coverage'] - reference['mean_handle_coverage'],
            median_handle_depth_change_mm=current['median_handle_depth_mm'] - reference['median_handle_depth_mm'])
    accepted = [key for key in ('light', 'medium', 'strong') if acceptance[key]['passed']]
    selected = min(accepted, key=lambda key: processing[key]['edge_angles']['dihedral_degrees_percentiles'][1]) if accepted else 'original'
    save(meshes[selected], args.output / 'cup_handle_selected')
    assert all(sha(Path(path)) == digest for path, digest in evidence.items())
    report = dict(passed=True, selected_by_consistency=selected, handle_direction_xy=direction.tolist(),
        region=dict(start_along_handle_mm=37, fully_smoothed_along_handle_mm=50,
                    full_transverse_halfwidth_mm=25, outer_transverse_halfwidth_mm=35),
        processing=processing, evaluation=summary, acceptance=acceptance, frames=frames,
        source_files_sha256=evidence, elapsed_seconds=time.monotonic() - started,
        physical_accuracy_validated=False, requires_visual_review=True, source_mesh_sha256=sha(args.mesh),
        limitations=['Smoothing changes the estimated surface using the same reference views and poses',
                     'Local protrusions and missing surfaces can remain after bounded smoothing'])
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(selected=selected, processing=processing, evaluation=summary, acceptance=acceptance)), flush=True)


if __name__ == '__main__':
    main()
