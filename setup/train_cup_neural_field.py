#!/usr/bin/env python3
"""Fit the official neural object field to saved RGB-D and estimated ICP poses.

This adapter does not train the FoundationPose refiner/scorer. It does not read
the existing mesh, infer poses from planned angles, or overwrite source data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--poses', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=1500)
    p.add_argument('--rays', type=int, default=512)
    p.add_argument('--memory-fraction', type=float, default=0.23)
    p.add_argument('--netchunk', type=int, default=32768)
    p.add_argument('--hole-ray-fraction', type=float, default=0., help='Opt-in verified mask-hole background ray fraction per batch')
    a = p.parse_args()
    if a.steps < 1 or a.rays < 1 or a.netchunk < 1 or not 0 < a.memory_fraction <= 1:
        p.error('Positive steps/rays/netchunk and memory fraction in (0,1] required')
    if not 0 <= a.hole_ray_fraction <= .5:
        p.error('Hole ray fraction must be in [0,.5]')
    if a.hole_ray_fraction and a.rays < 2:
        p.error('Hole sampling requires at least2 rays per batch')
    a.output.mkdir(parents=True, exist_ok=False)
    report = dict(status='validating', passed=False, estimated_poses_are_gt=False,
                  existing_mesh_used=False, pose_optimization=False,
                  representation='FoundationPose neural object field: hash encoding + SDF/color MLP',
                  limitations=['Single side ring lacks rim interior and contact surface.',
                               'Estimated ICP poses include interpolated handle directions.',
                               'Held-out views share the capture session and pose estimation pipeline; no independent geometric GT.'])
    start = time.monotonic()

    def save():
        report['elapsed_seconds'] = time.monotonic()-start
        (a.output/'report.json').write_text(json.dumps(report, indent=2))

    try:
        sys.path[:0] = [str(a.repo/'bundlesdf'), str(a.repo)]
        import numpy as np
        import cv2
        import torch
        import yaml
        from cup_neural_runtime import install_neural_cuda_aliases
        report['cuda_module_binding'] = install_neural_cuda_aliases()
        import run_nerf as api
        torch.cuda.set_per_process_memory_fraction(a.memory_fraction)
        torch.set_num_threads(2)
        api.set_seed(0)
        K = np.loadtxt(a.scene/'K.txt')
        assert K.shape == (3,3) and np.isfinite(K).all()
        rgbs, depths, masks, poses, evidence = [], [], [], [], []
        for i in range(72):
            stem = '%06d'%i
            paths = [a.scene/'rgb'/(stem+'.png'), a.scene/'depth'/(stem+'.png'),
                     a.scene/'masks'/(stem+'.png'), a.poses/(stem+'.txt')]
            rgb = cv2.cvtColor(cv2.imread(str(paths[0])), cv2.COLOR_BGR2RGB)
            depth = cv2.imread(str(paths[1]), cv2.IMREAD_UNCHANGED)
            mask = cv2.imread(str(paths[2]), cv2.IMREAD_UNCHANGED)
            T = np.loadtxt(paths[3])
            assert rgb.shape == (480,640,3) and depth.shape == mask.shape == (480,640)
            assert depth.dtype == np.uint16 and set(np.unique(mask)) <= {0,255}
            assert T.shape == (4,4) and np.isfinite(T).all()
            assert np.allclose(T[3], [0,0,0,1], atol=1e-8)
            assert np.allclose(T[:3,:3].T@T[:3,:3], np.eye(3), atol=1e-5)
            assert abs(np.linalg.det(T[:3,:3])-1)<1e-5
            depth = depth.astype(np.float32)/1000
            depth[mask==0] = 0
            assert np.count_nonzero(depth) > 1000
            rgbs.append(rgb); depths.append(depth); masks.append(mask); poses.append(T)
            evidence.extend(dict(path=str(q), sha256=digest(q)) for q in paths)
        evidence.append(dict(path=str(a.scene/'K.txt'), sha256=digest(a.scene/'K.txt')))
        (a.output/'inputs.json').write_text(json.dumps(evidence, indent=2))
        rgbs=np.asarray(rgbs); depths=np.asarray(depths); masks=np.asarray(masks); poses=np.asarray(poses)
        val_ids=[i for i in range(72) if i%6==3]
        train_ids=[i for i in range(72) if i not in val_ids]
        report.update(train_ids=train_ids, validation_ids=val_ids, depth_units='meters',
                      pose_convention='T_model_from_camera, OpenCV; converted to GL for neural field',
                      script_sha256=digest(Path(__file__)), input_files=len(evidence))
        cfg=yaml.safe_load((a.repo/'bundlesdf/config_ycbv.yml').read_text())
        overrides=dict(n_step=a.steps, N_rand=a.rays, chunk=a.rays, netchunk=a.netchunk,
                       optimize_poses=0, lrate_pose=0, frame_features=0,
                       i_print=100, i_weights=100000000, i_img=100000000,
                       i_mesh=100000000, i_pose=100000000,
                       mesh_resolution=0.0015, save_dir=str(a.output), n_train_image=len(train_ids))
        cfg.update(overrides)
        report['config_overrides']=overrides
        train_gl=poses[train_ids]@api.glcam_in_cvcam
        sc, translation, pcd_metric, pcd_normal=api.compute_scene_bounds(
            None, train_gl, K, use_mask=True, base_dir=str(a.output), rgbs=rgbs[train_ids],
            depths=depths[train_ids], masks=masks[train_ids], eps=cfg['dbscan_eps'],
            min_samples=cfg['dbscan_eps_min_samples'])
        cfg.update(sc_factor=float(sc), translation=np.asarray(translation).tolist())
        (a.output/'config.yml').write_text(yaml.safe_dump(cfg))
        api.o3d.io.write_point_cloud(str(a.output/'pcd_normalized.ply'), pcd_normal)
        arrays=api.preprocess_data(rgbs[train_ids].copy(), depths[train_ids].copy(),
                                  masks[train_ids].copy(), None, train_gl.copy(), sc, translation)
        report.update(status='building_neural_field', normalization=dict(scale=float(sc), translation=np.asarray(translation).tolist()))
        save()
        nerf=api.NerfRunner(cfg, *arrays[:3], normal_maps=None, poses=arrays[4], K=K,
                            occ_masks=None, build_octree_pcd=pcd_normal)
        if a.hole_ray_fraction:
            from cup_neural_sampling import HoleRayLoader
            manifest=json.loads((a.scene/'source_manifest.json').read_text())
            raw_scene=Path(manifest['source_scene'])
            expected={entry['path']:entry['sha256'] for entry in manifest['source_files']}
            raw_depths=[]
            for frame in train_ids:
                path=raw_scene/'depth'/('%06d.png'%frame)
                if str(path) not in expected or digest(path)!=expected[str(path)]:
                    raise ValueError('Raw background-depth provenance mismatch')
                raw=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
                if raw is None or raw.dtype!=np.uint16 or raw.shape!=(480,640):
                    raise ValueError('Invalid raw background depth')
                raw_depths.append(raw)
                evidence.append(dict(path=str(path),sha256=expected[str(path)]))
            nerf.data_loader=HoleRayLoader(nerf,raw_depths,a.hole_ray_fraction)
            report['hole_ray_sampling']=nerf.data_loader.report
            report['hole_ray_sampling']['original_frame_ids']=train_ids
            (a.output/'inputs.json').write_text(json.dumps(evidence,indent=2))
        report.update(status='training', training_rays=len(nerf.rays)); save()
        with (a.output/'progress.jsonl').open('w') as progress:
            for step in range(a.steps):
                batch=next(nerf.data_loader)
                nerf.train_loop(batch.cuda())
                nerf.global_step+=1
                if a.hole_ray_fraction and (step+1)%100==0:
                    gradients=[parameter.grad for model in nerf.models.values() if model is not None
                               for parameter in model.parameters() if parameter.grad is not None]
                    finite=bool(gradients) and all(bool(torch.isfinite(value).all()) for value in gradients)
                    report['hole_ray_sampling']['last_gradient_check_step']=step+1
                    report['hole_ray_sampling']['last_gradients_finite']=finite
                    if not finite:
                        raise RuntimeError('Missing or nonfinite neural-field training gradients')
                if (step+1)%100==0:
                    entry=dict(step=step+1, elapsed_seconds=time.monotonic()-start,
                               peak_allocated_mb=torch.cuda.max_memory_allocated()/1024**2)
                    progress.write(json.dumps(entry)+'\n');progress.flush()
                    print('PROGRESS',json.dumps(entry),flush=True)
                if (step+1)%500==0:
                    nerf.save_weights(str(a.output/'model_latest.pth'), nerf.models)
        nerf.save_weights(str(a.output/'model_latest.pth'), nerf.models)
        report.update(status='extracting_surface', training_steps=nerf.global_step);save()
        with torch.no_grad():
            mesh=nerf.extract_mesh(isolevel=0, voxel_size=cfg['mesh_resolution'])
        if mesh is None or not len(mesh.faces): raise RuntimeError('No SDF zero surface extracted')
        mesh.export(str(a.output/'surface_normalized.obj'))
        mesh=api.mesh_to_real_world(mesh, np.eye(4), translation, sc)
        mesh.export(str(a.output/'surface_metric.obj'))
        report.update(mesh_vertices=len(mesh.vertices), mesh_faces=len(mesh.faces),
                      mesh_extents_mm=(mesh.extents*1000).tolist(),
                      field_checkpoint=dict(path='model_latest.pth',sha256=digest(a.output/'model_latest.pth')))
        # Validation is a separate reload/query step. Upstream raw2outputs
        # requires observed depth and must not be used for depth-free preview.
        report.update(passed=True,status='field_and_surface_exported_validation_pending',
                      validation_entry='setup/render_cup_neural_field.py',
                      peak_allocated_mb=torch.cuda.max_memory_allocated()/1024**2,
                      training_inputs_unchanged=all(digest(Path(e['path']))==e['sha256'] for e in evidence))
        assert report['training_inputs_unchanged']
    except BaseException as e:
        report.update(status='failed', error=dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc()))
        traceback.print_exc()
    finally:
        save()
    print(json.dumps(report),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
