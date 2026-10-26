#!/usr/bin/env python3
"""FoundationPose GPU worker for saved latest-frame requests; no USB or pose GT."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--mesh', type=Path, required=True)
    p.add_argument('--mesh-sha256', required=True)
    p.add_argument('--fast', action='store_true', help='Lossless NPY input and original-mesh GPU contour/depth guard')
    p.add_argument('--cup-yaw-init', action='store_true', help='Experimental redcup72 model-Z yaw search using the initialization mask')
    args = p.parse_args()
    session, repo, meshfile = args.session.resolve(), args.repo.resolve(), args.mesh.resolve()
    report = dict(passed=False, status='loading', frames_completed=0, frames_failed=0,
                  pose_is_ground_truth=False, pose_accuracy_validated=False,
                  source_mesh=str(meshfile), mesh_sha256=sha(meshfile))
    try:
        if report['mesh_sha256'] != args.mesh_sha256:
            raise ValueError('Mesh differs from the selected metric candidate')
        from run_cup_mesh_inference import EXPECTED_PIN, inspect_pose, loaded_weight_info
        commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        if commit != EXPECTED_PIN:
            raise ValueError('FoundationPose checkout differs from validated pin')
        report['repo_commit'] = commit
        report['upstream_sha256'] = {name: sha(repo / name) for name in ('estimater.py', 'Utils.py')}
        os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
        sys.path.insert(0, str(repo))
        os.chdir(str(repo))
        import cv2
        import numpy as np
        import torch
        import trimesh
        import nvdiffrast.torch as dr
        from estimater import FoundationPose, PoseRefinePredictor, ScorePredictor
        from Utils import draw_posed_3d_box, draw_xyz_axis, set_logging_format, set_seed
        if args.fast:
            from cup_pose_quality import MeshProjection, depth_consistency
            from cup_reacquisition import mask_overlap, color_distance
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable')
        set_logging_format()
        set_seed(0)
        mesh = trimesh.load(str(meshfile), force='mesh', process=False)
        if not isinstance(mesh, trimesh.Trimesh) or not np.isfinite(mesh.vertices).all():
            raise ValueError('Expected finite metric triangle mesh')
        # Input is already meters. Keep original object origin and axes.
        vertices, faces = np.asarray(mesh.vertices).copy(), np.asarray(mesh.faces).copy()
        origin, extents = trimesh.bounds.oriented_bounds(mesh)
        np.savetxt(session / 'mesh_metric_to_obb.txt', origin, fmt='%.12g')
        bbox = np.stack([-extents / 2, extents / 2])
        context = dr.RasterizeCudaContext()
        projection = MeshProjection(mesh, context) if args.fast else None
        scorer, refiner = ScorePredictor(), PoseRefinePredictor()
        report['weights'] = {name: loaded_weight_info(model, repo)
                             for name, model in (('scorer', scorer), ('refiner', refiner))}
        report.update(gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
                      torch_cuda=torch.version.cuda, mesh_unit='m', mesh_extents_m=mesh.extents.tolist(),
                      mesh_visual_kind=mesh.visual.kind,
                      pose_definition='T_camera_from_original_mesh_meters',
                      obb_display_frame_only=True)
        estimator = FoundationPose(model_pts=mesh.vertices, model_normals=mesh.vertex_normals,
                                   mesh=mesh, scorer=scorer, refiner=refiner,
                                   glctx=context, debug=0,
                                   debug_dir=str(session / 'internal'))
        estimator.pose_last = None
        report.update(fast_mode=args.fast, tracking_iterations=2, registration_iterations=5,
                      guard_scope='depth consistency heuristic, not pose accuracy' if args.fast else 'numeric only')
        atomic_json(session / 'worker_report.json', report)
        atomic_json(session / 'ready.json', dict(ready=True, gpu=report['gpu']))
        processed, previous_K, active_epoch = set(), None, None
        while not (session / 'stop.flag').exists():
            pending = [f for f in sorted((session / 'requests').glob('*.json')) if f.stem not in processed]
            if not pending:
                time.sleep(0.001 if args.fast else 0.01)
                continue
            requestfile = pending[0]
            identifier = requestfile.stem
            processed.add(identifier)
            started = time.monotonic()
            response = dict(frame=identifier, passed=False, pose_is_ground_truth=False,
                            pose_accuracy_validated=False)
            try:
                request = json.loads(requestfile.read_text(encoding='utf-8'))
                folder = session / 'frames' / identifier
                allowed = ('rgb.npy', 'depth.npy', 'mask.png', 'capture.json', 'aruco.json') if args.fast else ('rgb.png', 'depth.png', 'mask.png', 'capture.json')
                for name, digest in request['input_sha256'].items():
                    if name not in allowed or sha(folder / name) != digest:
                        raise ValueError('Saved inference input SHA mismatch')
                if args.fast:
                    color = np.load(str(folder / 'rgb.npy'), allow_pickle=False)
                    raw = np.load(str(folder / 'depth.npy'), allow_pickle=False)
                else:
                    color = cv2.imread(str(folder / 'rgb.png'), cv2.IMREAD_COLOR)
                    raw = cv2.imread(str(folder / 'depth.png'), cv2.IMREAD_UNCHANGED)
                    if color is not None:
                        color = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
                if (color is None or raw is None or raw.dtype != np.uint16 or color.dtype != np.uint8
                        or color.ndim != 3 or color.shape[2] != 3 or color.shape[:2] != raw.shape):
                    raise ValueError('Require matching native RGB and uint16 millimeter depth')
                depth = raw.astype(np.float32) * 0.001
                K = np.asarray(request['K'], dtype=np.float64)
                if K.shape != (3, 3) or not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0:
                    raise ValueError('Invalid native camera matrix')
                if previous_K is not None and not np.allclose(K, previous_K, atol=1e-7, rtol=0):
                    raise ValueError('Camera intrinsics changed within session; start a new session')
                previous_K = K.copy()
                operation = request['operation']
                epoch = request.get('tracking_epoch', 0)
                response.update(operation=operation, tracking_epoch=epoch)
                identity = request.get('target_reference')
                atomic_json(session / 'processing' / (identifier + '.json'),
                            dict(frame=identifier, operation=operation, started_monotonic=time.monotonic()))
                inference_started = time.monotonic()
                if operation == 'register':
                    mask_raw = cv2.imread(str(folder / 'mask.png'), cv2.IMREAD_UNCHANGED)
                    if mask_raw is None or mask_raw.shape != raw.shape or not set(np.unique(mask_raw)).issubset({0, 255}):
                        raise ValueError('Registration requires a same-frame binary mask')
                    mask = mask_raw > 0
                    if np.count_nonzero(mask & (raw > 0)) < 100:
                        raise ValueError('Insufficient measured depth inside initialization mask')
                    response['masked_nonzero_depth_ratio'] = float(np.mean(raw[mask] > 0))
                    estimator.pose_last = None
                    active_epoch = None
                    pose = estimator.register(K=K, rgb=color, depth=depth, ob_mask=mask, iteration=5)
                    if estimator.pose_last is None:
                        raise RuntimeError('Registration returned before neural inference')
                    if args.fast:
                        official_pose = np.asarray(pose).copy()
                        np.savetxt(folder / 'official_top1_pose.txt', official_pose, fmt='%.12g')
                        transform = estimator.get_tf_to_centered_mesh()
                        candidates = []
                        for rank in range(min(8, len(estimator.poses))):
                            candidate = (estimator.poses[rank] @ transform).detach().cpu().numpy()
                            rendered = projection.render_depth(candidate, K, raw.shape)
                            overlap = mask_overlap(rendered, mask)
                            quality = depth_consistency(rendered, raw)
                            metric = overlap['iou'] - min(.1, (quality['median_abs_depth_residual_m'] or .1) * 2)
                            candidates.append(dict(rank=rank, pose=candidate.tolist(), overlap=overlap,
                                depth_quality=quality, official_score=float(estimator.scores[rank]), selection_metric=metric))
                        eligible = [c for c in candidates if c['overlap']['consistent'] and c['depth_quality']['heuristic_consistent']]
                        selected = max(eligible, key=lambda c: c['selection_metric']) if eligible else candidates[0]
                        if candidates[0] in eligible and selected['selection_metric'] - candidates[0]['selection_metric'] < .015:
                            selected = candidates[0]
                        pose = np.array(selected['pose'])
                        estimator.pose_last = estimator.poses[selected['rank']].clone()
                        response['registration_selection'] = dict(official_top1_preserved=True,
                            method='custom top8 silhouette/depth validation; official score order breaks near ties',
                            selected_rank=selected['rank'], selected_overlap=selected['overlap'], pose_accuracy_validated=False)
                        atomic_json(folder / 'registration_candidates.json', dict(candidates=candidates, **response['registration_selection']))
                        if args.cup_yaw_init:
                            if args.mesh_sha256 != '88e127e4cd4388bedcd77e7a0fb2cd5bde31c0557f861a7b60f8250bdac32f53':
                                raise ValueError('Cup yaw initialization requires the reviewed redcup72 mesh axes')
                            from cup_handle_yaw import select_cup_yaw
                            pose,yaw_selection=select_cup_yaw(pose,mask,raw,K,projection)
                            atomic_json(folder/'registration_yaw_candidates.json',yaw_selection)
                            transform_numpy=transform.detach().cpu().numpy() if hasattr(transform,'detach') else np.asarray(transform)
                            estimator.pose_last=torch.as_tensor(pose@np.linalg.inv(transform_numpy),
                                dtype=estimator.pose_last.dtype,device=estimator.pose_last.device)
                            response['registration_selection']['yaw_validation']=dict(
                                changed=yaw_selection['changed'],yaw_degrees=yaw_selection['selected']['yaw_degrees'],
                                protrusion_recall=yaw_selection['selected']['observed_protrusion_recall'],
                                iou=yaw_selection['selected']['iou'],pose_accuracy_validated=False)
                            response['registration_selection']['pre_yaw_overlap']=response['registration_selection']['selected_overlap']
                            response['registration_selection']['selected_overlap']=yaw_selection['selected']['overlap']
                elif operation == 'track':
                    if estimator.pose_last is None:
                        raise RuntimeError('Tracking requires a successful initialization')
                    if args.fast and epoch != active_epoch:
                        raise RuntimeError('Tracking epoch mismatch; registration required')
                    pose = estimator.track_one(rgb=color, depth=depth, K=K, iteration=2)
                else:
                    raise ValueError('Unknown requested operation')
                torch.cuda.synchronize()
                response['inference_seconds'] = time.monotonic() - inference_started
                pose, validation = inspect_pose(pose, np)
                response['validation'] = validation
                points = vertices @ pose[:3, :3].T + pose[:3, 3]
                if not validation['passed'] or pose[2, 3] <= 0 or points[:, 2].min() <= 0:
                    raise ValueError('Invalid rigid pose or mesh behind camera')
                posepath = folder / 'pose_camera_from_mesh.txt'
                np.savetxt(posepath, pose, fmt='%.12g')
                obb_pose = pose @ np.linalg.inv(origin)
                np.savetxt(folder / 'pose_camera_from_display_obb.txt', obb_pose, fmt='%.12g')
                vis = draw_posed_3d_box(K, img=color.copy(), ob_in_cam=obb_pose, bbox=bbox)
                vis = draw_xyz_axis(vis, ob_in_cam=obb_pose, K=K, scale=float(np.max(extents) * 0.5),
                                    thickness=2, transparency=0, is_input_rgb=True)
                # Project the full original mesh, so wrong handle orientation is visible.
                render_started = time.monotonic()
                if args.fast:
                    predicted = projection.render_depth(pose, K, raw.shape)
                    silhouette = (predicted > 0).astype(np.uint8) * 255
                    response['depth_quality'] = depth_consistency(predicted, raw)
                    response['tracking_consistent'] = response['depth_quality']['heuristic_consistent']
                    if operation == 'register':
                        response['tracking_consistent'] &= response['registration_selection']['selected_overlap']['consistent']
                    if identity is not None and int(np.count_nonzero(silhouette)) >= 100:
                        distance = color_distance(identity['color_hist'], color, silhouette)
                        response['appearance_quality'] = dict(distance=distance, threshold=.55, consistent=distance <= .55,
                                                              scope='initial target color consistency, not unique identity')
                        response['tracking_consistent'] &= distance <= .55
                    if not response['tracking_consistent']:
                        estimator.pose_last = None
                        active_epoch = None
                    elif operation == 'register':
                        active_epoch = epoch
                else:
                    xy = points @ K.T
                    xy = np.rint(np.clip(xy[:, :2] / xy[:, 2:3], -1e6, 1e6)).astype(np.int32)
                    silhouette = np.zeros(raw.shape, np.uint8)
                    for triangle in xy[faces]:
                        cv2.fillConvexPoly(silhouette, triangle, 255)
                response['render_quality_seconds'] = time.monotonic() - render_started
                contours = cv2.findContours(silhouette, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
                cv2.drawContours(vis, contours, -1, (255, 0, 255), 1)
                if args.fast:
                    reference = json.loads((folder / 'aruco.json').read_text(encoding='utf-8'))
                    if reference.get('found') and reference.get('corners_px'):
                        corners = np.rint(reference['corners_px']).astype(np.int32)
                        color_ref = (0, 255, 0) if reference.get('reference_accepted') else (255, 160, 0)
                        cv2.polylines(vis, [corners], True, color_ref, 2)
                        if reference.get('reference_accepted'):
                            vis = draw_xyz_axis(vis, ob_in_cam=np.array(reference['pose_camera_from_marker']), K=K,
                                                scale=reference['measured_marker_length_m'] * .5,
                                                thickness=2, transparency=0, is_input_rgb=True)
                cv2.putText(vis, 'Estimated mesh/pose; accuracy NOT validated', (7, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 0), 1, cv2.LINE_AA)
                overlay_name = 'overlay.jpg' if args.fast else 'overlay.png'
                encoding = [cv2.IMWRITE_JPEG_QUALITY, 85] if args.fast else []
                if not cv2.imwrite(str(folder / overlay_name), cv2.cvtColor(vis, cv2.COLOR_RGB2BGR), encoding):
                    raise RuntimeError('Overlay write failed')
                response.update(passed=True, operation=operation, pose=pose.tolist(),
                                pose_sha256=sha(posepath), overlay_sha256=sha(folder / overlay_name), overlay_file=overlay_name,
                                state='tracking_estimate_unverified')
                report['frames_completed'] += 1
            except Exception as error:
                estimator.pose_last = None
                active_epoch = None
                report['frames_failed'] += 1
                response.update(state='needs_reinitialization', error=str(error), traceback=traceback.format_exc())
                traceback.print_exc()
            response['worker_seconds'] = time.monotonic() - started
            response['request_sha256'] = sha(requestfile)
            atomic_json(folder / 'result.json', response)
            # Publishing the response is the final commit for this immutable frame.
            atomic_json(session / 'responses' / (identifier + '.json'), response)
            with (session / 'worker_events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(response, allow_nan=False) + '\n')
            if not args.fast or len(processed) % 30 == 0 or not response['passed']:
                atomic_json(session / 'worker_report.json', report)
            print(json.dumps(dict(frame=identifier, operation=response.get('operation'),
                                  passed=response['passed'], seconds=response['worker_seconds'])), flush=True)
        report.update(passed=report['frames_completed'] > 0 and report['frames_failed'] == 0, status='stopped')
        if sha(meshfile) != args.mesh_sha256:
            raise ValueError('Mesh changed during inference')
        for name, digest in report['upstream_sha256'].items():
            if sha(repo / name) != digest:
                raise ValueError('Official source changed during inference')
        for model in report['weights'].values():
            for name in ('checkpoint', 'config'):
                if sha(Path(model[name]['path'])) != model[name]['sha256']:
                    raise ValueError('Official weights changed during inference')
        atomic_json(session / 'worker_report.json', report)
        return 0 if report['passed'] else 2
    except Exception as error:
        report.update(passed=False, status='failed', error=str(error), traceback=traceback.format_exc())
        atomic_json(session / 'worker_report.json', report)
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
