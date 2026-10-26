#!/usr/bin/env python3
"""Summarize a paused live new-mesh trial; static repeatability is not accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    info=json.loads((args.session/'session.json').read_text())
    events=[json.loads(line) for line in (args.session/'frame_events.jsonl').read_text().splitlines() if line.strip()]
    accepted=[e for e in events if e.get('pose_confirmed') and e.get('accepted_for_tracking')]
    poses=np.array([e['pose'] for e in accepted],np.float64)
    stats={}
    if len(poses):
        translation=np.linalg.norm(poses[:,:3,3]-poses[0,:3,3],axis=1)*1000
        rotation=[]
        def rigid(R):
            u,_,v=np.linalg.svd(R);return u@np.diag([1,1,np.linalg.det(u@v)])@v
        anchor=rigid(poses[0,:3,:3])
        for T in poses:
            rotation.append(np.degrees(np.arccos(np.clip((np.trace(rigid(T[:3,:3])@anchor.T)-1)/2,-1,1))))
        rotation=np.array(rotation)
        stats=dict(scope='Changes relative to first confirmed estimate; only static repeatability if physical scene and camera remained stationary; not 6D accuracy',
            first_confirmed_frame=accepted[0]['frame'],confirmed_frames=len(poses),
            translation_from_first_mm=dict(median=float(np.median(translation)),p95=float(np.percentile(translation,95)),max=float(translation.max())),
            rotation_from_first_deg=dict(median=float(np.median(rotation)),p95=float(np.percentile(rotation,95)),max=float(rotation.max())),
            translation_axis_std_mm=(poses[:,:3,3].std(axis=0)*1000).tolist())
    verified_inputs=0
    for e in events:
        folder=args.session/'frames'/e['frame']
        request=json.loads((args.session/'requests'/(e['frame']+'.json')).read_text())
        for name,digest in request['input_sha256'].items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:
                raise ValueError('Input SHA differs: '+str(folder/name))
            verified_inputs+=1
        if e.get('passed') and hashlib.sha256((folder/'pose_camera_from_mesh.txt').read_bytes()).hexdigest()!=e['pose_sha256']:
            raise ValueError('Pose SHA differs: '+e['frame'])
    references=[]
    for e in events:
        f=args.session/'frames'/e['frame']/'aruco.json'
        if f.exists():references.append(json.loads(f.read_text()))
    reg=[e for e in events if e.get('operation')=='register']
    initial={}
    if reg:
        frame=args.session/'frames'/reg[0]['frame']
        mask=cv2.imread(str(frame/'mask.png'),0)>0
        depth=np.load(frame/'depth.npy',allow_pickle=False)
        initial=dict(frame=reg[0]['frame'],mask_pixels=int(mask.sum()),
            raw_depth_nonzero_in_mask=float((depth[mask]>0).mean()),
            mask_sha256=hashlib.sha256((frame/'mask.png').read_bytes()).hexdigest(),
            candidate_selection=reg[0].get('candidate_selection'),
            inference_seconds=reg[0].get('inference_seconds'))
    for number in sorted(set([0,len(events)//2,max(0,len(events)-1)])):
        if not events:break
        e=events[number];folder=args.session/'frames'/e['frame']
        for name in ['overlay.jpg','capture.json','host_result.json']:
            source=folder/name
            if source.exists():(args.output/(e['frame']+'_'+name)).write_bytes(source.read_bytes())
    checks=[]
    f=args.session/'initialization_checks.jsonl'
    if f.exists():checks=[json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    report=dict(scope='Live new-mesh trial numeric and repeatability summary, not absolute physical accuracy',
        session=str(args.session),mesh_profile=info.get('mesh_profile'),mesh_sha256=info.get('mesh_sha256'),
        event_count=len(events),inference_passed=sum(bool(e.get('passed')) for e in events),
        input_files_sha256_verified=verified_inputs,
        accepted_for_tracking=sum(bool(e.get('accepted_for_tracking')) for e in events),
        inference_failed=sum(not e.get('passed',False) for e in events),
        reference_found=sum(bool(r.get('found')) for r in references),reference_accepted=sum(bool(r.get('reference_accepted')) for r in references),
        initial_frame=initial,initialization_checks=checks,static_estimate_changes=stats,
        bridge_latency_ms=dict(median=float(np.median([e['host_receive_to_result_seconds']*1000 for e in events])),
            p95=float(np.percentile([e['host_receive_to_result_seconds']*1000 for e in events],95))) if events else None,
        pose_accuracy_validated=False,reference_available=any(r.get('reference_accepted') for r in references),
        raw_data_modified=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
