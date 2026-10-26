#!/usr/bin/env python3
"""Verify vertex RGB survives the installed FoundationPose renderer; no inference.

Use estimated reconstruction poses only to place the model for appearance review.
This is not a pose/mesh accuracy measurement or a change to the live mesh.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import cv2
import numpy as np
import torch
import trimesh


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path('/workspace/FoundationPose'))
    p.add_argument('--mesh',type=Path,required=True)
    p.add_argument('--scene',type=Path,required=True)
    p.add_argument('--poses',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(args.repo))
    from Utils import make_mesh_tensors,nvdiffrast_render
    import nvdiffrast.torch as dr
    mesh=trimesh.load(str(args.mesh),force='mesh',process=False)
    tensors=make_mesh_tensors(mesh)
    if 'vertex_color' not in tensors:raise ValueError('Expected vertex-color rendering branch')
    colors=tensors['vertex_color'].detach().cpu().numpy()
    if len(np.unique(colors,axis=0))<2:raise ValueError('Stored vertex appearance is unexpectedly uniform')
    K=np.loadtxt(args.scene/'K.txt')
    context=dr.RasterizeCudaContext()
    outputs=[]
    for number in (0,18,36):
        name='%06d'%number
        pose_path=args.poses/(name+'.txt')
        pose=np.linalg.inv(np.loadtxt(pose_path))
        pose_tensor=torch.as_tensor(pose,dtype=torch.float32,device='cuda')[None]
        rgb,depth,_=nvdiffrast_render(K=K,H=480,W=640,ob_in_cams=pose_tensor,
            context='cuda',glctx=context,mesh_tensors=tensors,use_light=False)
        image=np.clip(rgb[0].detach().cpu().numpy()*255,0,255).astype(np.uint8)
        depth_image=depth[0].detach().cpu().numpy()
        visible=depth_image>0
        if not np.any(visible) or len(np.unique(image[visible],axis=0))<2:
            raise ValueError('Render is empty or lacks varying surface color')
        render_path=args.output/(name+'_render_rgb.png')
        cv2.imwrite(str(render_path),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))
        observed=cv2.imread(str(args.scene/'rgb'/(name+'.png')))
        rendered=cv2.cvtColor(image,cv2.COLOR_RGB2BGR)
        rendered[~visible]=235
        comparison=np.concatenate([observed,rendered],axis=1)
        cv2.putText(comparison,'Observed RGB | FoundationPose renderer + estimated reconstruction pose',
            (8,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),2)
        cv2.imwrite(str(args.output/(name+'_observed_vs_render.png')),comparison)
        outputs.append(dict(frame=number,pose_sha256=sha(pose_path),visible_pixels=int(visible.sum()),
            rendered_unique_rgb=int(len(np.unique(image[visible],axis=0))),render_sha256=sha(render_path)))
    source=args.repo/'Utils.py'
    commit=subprocess.check_output(['git','-C',str(args.repo),'rev-parse','HEAD'],text=True).strip()
    report=dict(passed=True,scope='Installed FoundationPose vertex-color rasterization only; no pose estimation or accuracy acceptance',
        mesh_path=str(args.mesh),mesh_sha256=sha(args.mesh),visual_kind=mesh.visual.kind,
        mesh_tensor_keys=sorted(tensors),vertex_rgb_count=len(colors),unique_vertex_rgb=int(len(np.unique(colors,axis=0))),
        renderer_source=str(source),renderer_sha256=sha(source),foundationpose_commit=commit,
        torch_version=torch.__version__,trimesh_version=trimesh.__version__,outputs=outputs,
        production_mesh_changed=False,poses_are_ground_truth=False,uv_atlas_present=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
