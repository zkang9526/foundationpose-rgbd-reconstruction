#!/usr/bin/env python3
"""Offline model-Z yaw sweep against one saved RGB-D/init mask, never pose GT."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np
import torch
import trimesh


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--mesh',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,'/workspace/FoundationPose')
    from Utils import make_mesh_tensors,nvdiffrast_render
    import nvdiffrast.torch as dr
    folder=args.session/'frames/000000'
    rgb=np.load(folder/'rgb.npy',allow_pickle=False);raw=np.load(folder/'depth.npy',allow_pickle=False)
    mask=cv2.imread(str(folder/'mask.png'),0)>0
    K=np.loadtxt(args.session/'K.txt');seed=np.loadtxt(folder/'pose_camera_from_mesh.txt')
    mesh=trimesh.load(str(args.mesh),force='mesh',process=False)
    tensors=make_mesh_tensors(mesh);context=dr.RasterizeCudaContext()
    opened=cv2.morphologyEx(mask.astype(np.uint8),cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(21,21)))
    core=cv2.dilate(opened,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))>0
    protrusion=mask&~core
    values=[];images=[]
    for degrees in range(-180,180,10):
        angle=np.deg2rad(degrees);rotation=np.eye(4)
        rotation[:2,:2]=[[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]]
        pose=seed@rotation
        _,depth,_=nvdiffrast_render(K=K,H=480,W=640,ob_in_cams=torch.as_tensor(pose,dtype=torch.float32,device='cuda')[None],
            mesh_tensors=tensors,glctx=context,extra={},use_light=False)
        predicted=depth[0].cpu().numpy();sil=predicted>0
        union=(sil|mask).sum();iou=float((sil&mask).sum()/max(1,union))
        recall=float((sil&protrusion).sum()/max(1,protrusion.sum()))
        common=sil&(raw>0);median=float(np.median(np.abs(predicted[common]-raw[common]*.001)))
        score=iou+.15*recall-min(.1,median*2)
        values.append(dict(yaw_degrees=degrees,iou=iou,observed_protrusion_recall=recall,median_depth_residual_mm=median*1000,
                           custom_score=score,pose=pose.tolist()))
        images.append(sil)
    baseline=next(i for i,x in enumerate(values) if x['yaw_degrees']==0)
    best=max(range(len(values)),key=lambda i:values[i]['custom_score'])
    panels=[]
    x,y,w,h=cv2.boundingRect(mask.astype(np.uint8));crop=(max(0,x-18),max(0,y-18),min(640,x+w+18),min(480,y+h+18))
    for label,index in [('Saved initial pose',baseline),('Custom yaw candidate',best)]:
        image=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
        cv2.drawContours(image,cv2.findContours(mask.astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(0,255,255),1)
        cv2.drawContours(image,cv2.findContours(images[index].astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(255,0,255),1)
        x0,y0,x1,y1=crop;image=cv2.resize(image[y0:y1,x0:x1],(480,440))
        panel=np.full((500,480,3),250,np.uint8);panel[60:]=image
        cv2.putText(panel,label,(6,20),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,0),1)
        cv2.putText(panel,'yaw %+d / IoU %.3f / protrusion %.3f'%(values[index]['yaw_degrees'],values[index]['iou'],values[index]['observed_protrusion_recall']),
            (6,45),cv2.FONT_HERSHEY_SIMPLEX,.43,(0,0,0),1)
        panels.append(panel)
    cv2.imwrite(str(args.output/'initial_pose_yaw_comparison.png'),np.concatenate(panels,axis=1))
    cv2.imwrite(str(args.output/'observed_protrusion.png'),protrusion.astype(np.uint8)*255)
    np.savetxt(args.output/'custom_candidate_pose.txt',values[best]['pose'],fmt='%.12g')
    report=dict(scope='Single saved-view silhouette/depth consistency experiment, not independent 6D/geometry accuracy',
        baseline=values[baseline],custom_candidate=values[best],observed_protrusion_pixels=int(protrusion.sum()),candidates=values,
        production_behavior_modified=False,model_geometry_modified=False,pose_is_ground_truth=False,
        source_sha256={n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ['rgb.npy','depth.npy','mask.png','pose_camera_from_mesh.txt']})
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='candidates'}),flush=True)


if __name__=='__main__':main()
