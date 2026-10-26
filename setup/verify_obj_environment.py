#!/usr/bin/env python3
"""Exercise Open3D ICP, pose graphs, metric TSDF fusion and OBJ round-trip.

Only synthetic data is used. This is an environment check, not a reconstruction
of the user's object, nor evidence that real camera data will register correctly.
No GUI, network or dataset downloads are required.
"""
import argparse
import copy
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(passed=False, scope='synthetic_environment_check_only',
                  real_object_reconstruction_validated=False,
                  started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  platform=platform.platform(), python=sys.version,
                  python_executable=sys.executable, packages={}, checks={})
    try:
        import numpy as np
        import cv2
        import open3d as o3d
        import trimesh
        from PIL import Image
        for name in ('open3d', 'numpy', 'opencv-python', 'trimesh', 'Pillow', 'torch'):
            try:
                report['packages'][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                report['packages'][name] = None
        result = subprocess.run([sys.executable, '-m', 'pip', 'check'],
                                capture_output=True, text=True, timeout=60)
        report['checks']['pip_check'] = dict(exit_code=result.returncode,
                                             output=(result.stdout + result.stderr).strip())
        require(result.returncode == 0, 'Installed reconstruction dependencies conflict')
        freeze = subprocess.run([sys.executable, '-m', 'pip', 'freeze'],
                                capture_output=True, text=True, timeout=60, check=True)
        (output / 'requirements.lock.txt').write_text(freeze.stdout, encoding='utf-8')

        # Deterministic, asymmetric 3D points: test a known, non-identity transform.
        rng = np.random.default_rng(20261014)
        points = rng.uniform(-0.07, 0.07, (4000, 3))
        points[:, 1] *= 0.7
        source = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
        expected = np.eye(4)
        expected[:3, :3] = o3d.geometry.get_rotation_matrix_from_xyz((0.02, -0.03, 0.04))
        expected[:3, 3] = (0.003, -0.004, 0.002)
        target = copy.deepcopy(source).transform(expected)
        reg = o3d.pipelines.registration
        alignment = reg.registration_icp(source, target, 0.025, np.eye(4),
            reg.TransformationEstimationPointToPoint(), reg.ICPConvergenceCriteria(max_iteration=80))
        error = float(np.max(np.abs(alignment.transformation - expected)))
        require(alignment.fitness > 0.99 and error < 1e-5,
                'ICP failed to recover the synthetic rigid transform')
        report['checks']['icp'] = dict(fitness=alignment.fitness, rmse=alignment.inlier_rmse,
                                      max_transform_error=error)

        information = reg.get_information_matrix_from_point_clouds(
            source, target, 0.025, alignment.transformation)
        graph = reg.PoseGraph()
        graph.nodes.append(reg.PoseGraphNode(np.eye(4)))
        graph.nodes.append(reg.PoseGraphNode(np.linalg.inv(alignment.transformation)))
        graph.edges.append(reg.PoseGraphEdge(0, 1, alignment.transformation, information, False))
        reg.global_optimization(graph, reg.GlobalOptimizationLevenbergMarquardt(),
            reg.GlobalOptimizationConvergenceCriteria(),
            reg.GlobalOptimizationOption(max_correspondence_distance=0.025, reference_node=0))
        graph_error = float(np.max(np.abs(graph.nodes[1].pose - np.linalg.inv(expected))))
        require(graph_error < 1e-5, 'Pose graph transform convention check failed')
        graph_path = output / 'synthetic_pose_graph.json'
        o3d.io.write_pose_graph(str(graph_path), graph)
        require(graph_path.is_file() and graph_path.stat().st_size > 0, 'Could not save pose graph')
        reloaded_graph = o3d.io.read_pose_graph(str(graph_path))
        require(len(reloaded_graph.nodes) == 2 and len(reloaded_graph.edges) == 1,
                'Pose graph round-trip lost nodes or constraints')
        report['checks']['pose_graph'] = dict(nodes=len(graph.nodes), max_transform_error=graph_error)

        # Raycast a box from 12 known viewpoints, then fuse its millimeter RGB-D.
        dimensions = np.array([0.10, 0.12, 0.08])
        box = o3d.geometry.TriangleMesh.create_box(*dimensions).translate(-dimensions / 2)
        scene = o3d.t.geometry.RaycastingScene()
        scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(box))
        width, height = 320, 240
        K = np.array([[280., 0., 159.5], [0., 280., 119.5], [0., 0., 1.]])
        intrinsic = o3d.camera.PinholeCameraIntrinsic(width, height, 280., 280., 159.5, 119.5)
        volume = o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=0.003,
            sdf_trunc=0.012, color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8)
        poses = []
        for index in range(12):
            angle = index * 2 * np.pi / 12
            eye = np.array([0.40 * np.sin(angle), 0.14 if index % 2 else -0.14, -0.40 * np.cos(angle)])
            forward = -eye / np.linalg.norm(eye)
            right = np.cross(forward, [0., 1., 0.])
            right /= np.linalg.norm(right)
            down = np.cross(forward, right)
            camera_to_model = np.eye(4)
            camera_to_model[:3, :3] = np.column_stack((right, down, forward))
            camera_to_model[:3, 3] = eye
            model_to_camera = np.linalg.inv(camera_to_model)
            rays = scene.create_rays_pinhole(o3d.core.Tensor(K),
                o3d.core.Tensor(model_to_camera), width, height)
            hits = scene.cast_rays(rays)['t_hit'].numpy()
            valid = np.isfinite(hits) & (hits > 0) & (hits < 1)
            depth = np.zeros((height, width), np.uint16)
            depth[valid] = np.rint(hits[valid] * 1000).astype(np.uint16)
            rgb = np.full((height, width, 3), (180, 120, 60), np.uint8)
            rgb[~valid] = 0
            if index == 0:
                Image.fromarray(rgb).save(output / 'synthetic_rgb.png')
                Image.fromarray(depth).save(output / 'synthetic_depth_mm.png')
                reread = cv2.imread(str(output / 'synthetic_depth_mm.png'), cv2.IMREAD_UNCHANGED)
                require(reread.dtype == np.uint16 and np.array_equal(reread, depth),
                        '16-bit PNG round-trip changed raw depth')
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                o3d.geometry.Image(rgb), o3d.geometry.Image(depth), depth_scale=1000.,
                depth_trunc=1., convert_rgb_to_intensity=False)
            cloud = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd, intrinsic)
            require(len(cloud.points) > 500, 'RGB-D point cloud is empty or unexpectedly small')
            volume.integrate(rgbd, intrinsic, model_to_camera)
            poses.append(camera_to_model.tolist())
        mesh = volume.extract_triangle_mesh()
        mesh.remove_degenerate_triangles().remove_duplicated_triangles().remove_unreferenced_vertices()
        mesh.compute_vertex_normals()
        require(len(mesh.triangles) > 100, 'TSDF mesh extraction returned no usable surface')
        extents = mesh.get_axis_aligned_bounding_box().get_extent()
        report['checks']['tsdf_geometry'] = dict(actual_extents_meters=extents.tolist(),
            expected_extents_meters=dimensions.tolist(), vertices=len(mesh.vertices), triangles=len(mesh.triangles))
        print(json.dumps(report['checks']['tsdf_geometry']), flush=True)
        require(o3d.io.write_triangle_mesh(str(output / 'synthetic_box.ply'), mesh), 'PLY export failed')
        require(o3d.io.write_triangle_mesh(str(output / 'synthetic_box.obj'), mesh,
            write_vertex_colors=False, write_triangle_uvs=False), 'OBJ export failed')
        # Bounding boxes include TSDF silhouette/frustum-edge artifacts. Check
        # actual surface error as well as a bound tied to the truncation band;
        # a fixed bounding-box tolerance alone is not a metric accuracy test.
        distance = scene.compute_distance(o3d.core.Tensor(np.asarray(mesh.vertices), dtype=o3d.core.Dtype.Float32)).numpy()
        surface_error_95 = float(np.percentile(distance, 95))
        report['checks']['tsdf_geometry']['surface_error_95_meters'] = surface_error_95
        require(surface_error_95 < 0.006, 'Synthetic TSDF surface error exceeds two voxels')
        require(np.max(np.abs(extents - dimensions)) < 2 * 0.012 + 2 * 0.003,
                'TSDF mesh bounds exceed the truncation band; check units and transforms')
        reloaded = trimesh.load(str(output / 'synthetic_box.obj'), force='mesh', process=False)
        require(len(reloaded.faces) == len(mesh.triangles), 'OBJ faces changed on reload')
        require(np.isfinite(reloaded.vertices).all() and np.max(np.abs(reloaded.extents - extents)) < 1e-6,
                'OBJ round-trip changed metric dimensions')
        report['checks']['tsdf_obj_roundtrip'] = dict(views=12, voxel_meters=0.003,
            expected_extents_meters=dimensions.tolist(), actual_extents_meters=reloaded.extents.tolist(),
            vertices=len(reloaded.vertices), triangles=len(reloaded.faces),
            obj='synthetic_box.obj', real_object=False, surface_error_95_meters=surface_error_95,
            bounds_tolerance_meters=0.030, bounds_scope='environment unit/convention check, not physical object QA')
        (output / 'synthetic_camera_to_model.json').write_text(json.dumps(poses, indent=2) + '\n', encoding='utf-8')
        if report['packages']['torch']:
            import torch
            require(torch.cuda.is_available(), 'Configured FoundationPose CUDA runtime is unavailable')
            tensor = torch.arange(16, dtype=torch.float32, device='cuda').reshape(4, 4)
            product = (tensor @ tensor.T).cpu().numpy()
            require(np.isfinite(product).all(), 'CUDA matrix calculation failed')
            report['checks']['cuda'] = dict(device=torch.cuda.get_device_name(0), torch=torch.__version__)
        report['artifacts'] = [dict(path=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                               for p in sorted(output.iterdir()) if p.is_file()]
        report['passed'] = True
    except Exception as exc:
        report['error'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
