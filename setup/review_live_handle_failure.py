#!/usr/bin/env python3
"""Inspect saved live handle/mask/projection without treating moving markers as GT."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--mesh',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    events=[json.loads(s) for s in (args.session/'frame_events.jsonl').read_text().splitlines() if s.strip()]
    host=json.loads((args.session/'session.json').read_text())
    K=np.loadtxt(args.session/'K.txt')
    vertices=[];faces=[]
    for line in args.mesh.read_text().splitlines():
        f=line.split()
        if f and f[0]=='v':vertices.append([float(v) for v in f[1:4]])
        elif f and f[0]=='f':faces.append([int(x.split('/')[0])-1 for x in f[1:4]])
    vertices=np.array(vertices);faces=np.array(faces)
    # Spatial protrusion, only a diagnostic region: not independent semantic handle GT.
    handle_faces=faces[np.any(vertices[faces,0]<-.046,axis=1)]
    chosen=sorted(set([0,3,30,200,600,len(events)//2, max(0,len(events)-1)]))
    stats=[];sources=[]
    for index in chosen:
        e=events[index];folder=args.session/'frames'/e['frame']
        rgb=np.load(folder/'rgb.npy',allow_pickle=False)
        depth=np.load(folder/'depth.npy',allow_pickle=False)
        observed=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
        overlay=cv2.imread(str(folder/e['overlay_file']))
        mask_path=folder/'mask.png'
        mask=cv2.imread(str(mask_path),0)>0 if mask_path.exists() else None
        diagnostic=observed.copy()
        if mask is not None:
            cv2.drawContours(diagnostic,cv2.findContours(mask.astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(0,255,255),1)
            diagnostic[mask&(depth==0)]=(255,60,60)
        pose=np.array(e['pose']);camera=vertices@pose[:3,:3].T+pose[:3,3]
        points=camera@K.T;xy=np.rint(points[:,:2]/points[:,2:3]).astype(np.int32)
        projected=np.zeros(depth.shape,np.uint8)
        for triangle in handle_faces:
            if np.all(camera[triangle,2]>.05):cv2.fillConvexPoly(projected,xy[triangle],255)
        cv2.drawContours(diagnostic,cv2.findContours(projected,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(0,100,255),1)
        for image,label in [(observed,'Original RGB'),(overlay,'Actual saved mesh projection'),(diagnostic,'Yellow: init mask; blue: zero depth; orange: mesh protrusion')]:
            cv2.rectangle(image,(0,0),(640,25),(245,245,245),-1)
            cv2.putText(image,label,(5,18),cv2.FONT_HERSHEY_SIMPLEX,.43,(0,0,0),1,cv2.LINE_AA)
        panel=np.concatenate([observed,overlay,diagnostic],axis=1)
        cv2.imwrite(str(args.output/(e['frame']+'_panel.png')),panel)
        cv2.imwrite(str(args.output/(e['frame']+'_rgb.png')),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
        if mask is not None:cv2.imwrite(str(args.output/(e['frame']+'_mask.png')),mask.astype(np.uint8)*255)
        item=dict(frame=e['frame'],operation=e['operation'],registration_selection=e.get('registration_selection'),
                  depth_quality=e.get('depth_quality'),accepted_for_tracking=e.get('accepted_for_tracking'),
                  inference_seconds=e.get('inference_seconds'))
        if mask is not None:item.update(mask_pixels=int(mask.sum()),masked_depth_nonzero=float((depth[mask]>0).mean()))
        stats.append(item)
        request=json.loads((args.session/'requests'/(e['frame']+'.json')).read_text())
        for name,digest in request['input_sha256'].items():
            if sha(folder/name)!=digest:raise ValueError('Input SHA mismatch: '+name)
            sources.append(dict(path=str(folder/name),sha256=digest))
        if mask_path.exists():
            f=folder/'registration_candidates.json'
            if f.exists():(args.output/'registration_candidates.json').write_bytes(f.read_bytes())
    controls=[json.loads(s) for s in (args.session/'controls.jsonl').read_text().splitlines() if s.strip()]
    report=dict(scope='Saved raw RGB, actual initialized mask, original mesh projection and depth audit; no pose GT',
        session=str(args.session),source_session_status=host.get('status'),event_count=len(events),sampled_frames=stats,
        mesh_sha256=sha(args.mesh),spatial_protrusion_faces=len(handle_faces),
        spatial_region_definition='faces with any model vertex x < -46mm; approximate protrusion only, not semantic GT',
        source_files=sources,controls=controls,
        user_reported_cup_or_marker_relative_position_changed=True,
        fixed_scene_protocol_valid=False,aruco_statistics_interpretable_as_pose_error=False,
        previous_raw_aruco_statistics_retained=True,raw_sources_modified=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['source_files','controls']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
