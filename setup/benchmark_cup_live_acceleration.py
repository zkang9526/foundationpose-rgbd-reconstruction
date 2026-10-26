#!/usr/bin/env python3
"""Profile actual FoundationPose stages and compare CPU/GPU overlays on same inputs."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--segment',type=Path,required=True)
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--mesh',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frames',type=int,default=60)
    args=p.parse_args()
    if args.output.exists():p.error('Output must be new')
    args.output.mkdir(parents=True,exist_ok=False)
    report=dict(passed=False,source='offline same saved live RGB-D',live_fps_measured=False,
                pose_accuracy_validated=False,model_sha256=sha(args.mesh),variants={})
    try:
        import cv2
        import numpy as np
        os.environ.setdefault('PYOPENGL_PLATFORM','egl')
        sys.path.insert(0,str(args.repo.resolve()))
        os.chdir(str(args.repo))
        import torch
        import trimesh
        import nvdiffrast.torch as dr
        from estimater import FoundationPose,ScorePredictor,PoseRefinePredictor
        from Utils import draw_posed_3d_box,draw_xyz_axis,set_seed
        from cup_pose_quality import MeshProjection,depth_consistency,image_change
        from run_cup_mesh_inference import EXPECTED_PIN,loaded_weight_info
        assert subprocess.check_output(['git','-C',str(args.repo),'rev-parse','HEAD'],text=True).strip()==EXPECTED_PIN
        logging.getLogger().setLevel(logging.WARNING)
        set_seed(0)
        mesh=trimesh.load(str(args.mesh),force='mesh',process=False)
        vertices,faces=np.array(mesh.vertices).copy(),np.array(mesh.faces).copy()
        origin,extents=trimesh.bounds.oriented_bounds(mesh)
        box=np.stack([-extents/2,extents/2])
        K=np.array(json.loads((args.original/'session.json').read_text())['K'])
        scorer,refiner=ScorePredictor(),PoseRefinePredictor()
        context=dr.RasterizeCudaContext()
        estimator=FoundationPose(model_pts=mesh.vertices,model_normals=mesh.vertex_normals,mesh=mesh,
            scorer=scorer,refiner=refiner,glctx=context,debug=0,debug_dir=str(args.output/'internal'))
        projection=MeshProjection(mesh,context)
        report.update(gpu=torch.cuda.get_device_name(0),torch=torch.__version__,
                      existing_mixed_precision=bool(refiner.cfg.get('enable_amp',False)),
                      weights={name:loaded_weight_info(obj,args.repo) for name,obj in [('scorer',scorer),('refiner',refiner)]})
        ids=sorted(f.stem for f in (args.segment/'requests').glob('*.json'))[:args.frames]
        assert len(ids)==args.frames
        inputs=[]
        for stem in ids:
            folder=args.segment/'frames'/stem
            req=json.loads((args.segment/'requests'/(stem+'.json')).read_text())
            for name,digest in req['input_sha256'].items():assert sha(folder/name)==digest
            inputs.append((stem,folder))
        old=cv2.cvtColor(cv2.imread(str(args.original/'frames/000000/rgb.png')),cv2.COLOR_BGR2RGB)
        new=cv2.cvtColor(cv2.imread(str(inputs[0][1]/'rgb.png')),cv2.COLOR_BGR2RGB)
        oldmask=cv2.imread(str(args.original/'frames/000000/mask.png'),0)
        report['initial_stale_image_check']=image_change(old,new,oldmask)
        baseline_poses={}
        for label,gpu_overlay,iterations in [('baseline_cpu_2iter',False,2),('gpu_overlay_2iter',True,2),('gpu_overlay_1iter_experimental',True,1)]:
            out=args.output/label;out.mkdir()
            estimator.pose_last=None
            metrics=[];deltas=[];old_quality=[]
            for index,(stem,folder) in enumerate(inputs):
                total=time.perf_counter()
                color=cv2.cvtColor(cv2.imread(str(folder/'rgb.png')),cv2.COLOR_BGR2RGB)
                raw=cv2.imread(str(folder/'depth.png'),-1)
                depth=raw.astype(np.float32)*.001
                after_read=time.perf_counter()
                if index==0:
                    mask=cv2.imread(str(folder/'mask.png'),0)>0
                    pose=estimator.register(K=K,rgb=color,depth=depth,ob_mask=mask,iteration=5)
                else:
                    pose=estimator.track_one(K=K,rgb=color,depth=depth,iteration=iterations)
                torch.cuda.synchronize()
                after_inference=time.perf_counter()
                vis=draw_posed_3d_box(K,img=color.copy(),ob_in_cam=pose@np.linalg.inv(origin),bbox=box)
                vis=draw_xyz_axis(vis,ob_in_cam=pose@np.linalg.inv(origin),K=K,scale=float(np.max(extents)*.5),
                                  thickness=2,transparency=0,is_input_rgb=True)
                if gpu_overlay:
                    predicted=projection.render_depth(pose,K,raw.shape)
                    silhouette=(predicted>0).astype(np.uint8)*255
                    quality=depth_consistency(predicted,raw)
                else:
                    points=vertices@pose[:3,:3].T+pose[:3,3]
                    xy=points@K.T
                    xy=np.rint(np.clip(xy[:,:2]/xy[:,2:3],-1e6,1e6)).astype(np.int32)
                    silhouette=np.zeros(raw.shape,np.uint8)
                    for triangle in xy[faces]:cv2.fillConvexPoly(silhouette,triangle,255)
                    quality=None
                contours=cv2.findContours(silhouette,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[-2]
                cv2.drawContours(vis,contours,-1,(255,0,255),1)
                after_render=time.perf_counter()
                np.savetxt(out/(stem+'.txt'),pose,fmt='%.12g')
                cv2.imwrite(str(out/(stem+'.png')),cv2.cvtColor(vis,cv2.COLOR_RGB2BGR))
                after_write=time.perf_counter()
                if label=='baseline_cpu_2iter':baseline_poses[stem]=pose.copy()
                else:
                    before=baseline_poses[stem]
                    angle=np.degrees(np.arccos(np.clip((np.trace(pose[:3,:3]@before[:3,:3].T)-1)*.5,-1,1)))
                    deltas.append(dict(frame=stem,translation_difference_mm=float(np.linalg.norm(pose[:3,3]-before[:3,3])*1000),
                                       rotation_difference_deg=float(angle),difference_is_not_accuracy=True))
                metrics.append(dict(frame=stem,operation='register' if index==0 else 'track',
                    read_ms=(after_read-total)*1000,inference_ms=(after_inference-after_read)*1000,
                    render_ms=(after_render-after_inference)*1000,write_ms=(after_write-after_render)*1000,
                    total_ms=(after_write-total)*1000,quality=quality))
                if label=='gpu_overlay_2iter':
                    original_pose=np.loadtxt(args.original/'frames'/stem/'pose_camera_from_mesh.txt')
                    old_quality.append(dict(frame=stem,**depth_consistency(projection.render_depth(original_pose,K,raw.shape),raw)))
            timed=metrics[5:]
            summary={name:dict(median=float(np.median([m[name] for m in timed])),p95=float(np.percentile([m[name] for m in timed],95)))
                     for name in ('read_ms','inference_ms','render_ms','write_ms','total_ms')}
            report['variants'][label]=dict(track_iterations=iterations,metrics=metrics,stage_ms=summary,
                worker_only_fps=1000/np.mean([m['total_ms'] for m in timed]),pose_difference_to_baseline=deltas,
                original_drift_depth_quality=old_quality)
            print(json.dumps(dict(variant=label,stage_ms=summary,worker_only_fps=report['variants'][label]['worker_only_fps'])),flush=True)
        report['passed']=True
    except Exception as error:
        report.update(error=str(error),traceback=traceback.format_exc());traceback.print_exc()
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],output=str(args.output),live_fps_measured=False)))
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
