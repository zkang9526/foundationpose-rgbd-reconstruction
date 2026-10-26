#!/usr/bin/env python3
"""Run actual GPU worker with corrected cup init and repeated saved RGB-D frames.

This is an integration/initialization stability check, never a moving-camera test.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-session',type=Path,required=True)
    p.add_argument('--code-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output
    out.mkdir(parents=True,exist_ok=False)
    for name in ['frames','requests','responses','processing']:(out/name).mkdir()
    shutil.copytree(args.source_session/'worker_code',out/'worker_code')
    for name in ['run_cup_live_worker.py','cup_handle_yaw.py']:
        shutil.copy2(args.code_dir/name,out/'worker_code'/name)
    initial=json.loads((args.source_session/'requests/000000.json').read_text())
    source=args.source_session/'frames/000000'
    def submit(index):
        identifier='%06d'%index;folder=out/'frames'/identifier;folder.mkdir()
        request=dict(initial,frame=identifier,operation='register' if index==0 else 'track',
                     source='offline repeated saved frame; not live FPS or physical accuracy')
        for name in request['input_sha256']:shutil.copy2(source/name,folder/name)
        (out/'requests'/(identifier+'.json')).write_text(json.dumps(request)+'\n')
    submit(0)
    command=[sys.executable,'-B','-u',str(out/'worker_code/run_cup_live_worker.py'),'--session',str(out),
        '--repo','/workspace/FoundationPose','--mesh','/data/derived/redcup_geometric_clean_v1_20261017_2050/cup_clean.obj',
        '--mesh-sha256','88e127e4cd4388bedcd77e7a0fb2cd5bde31c0557f861a7b60f8250bdac32f53','--fast','--cup-yaw-init']
    log=(out/'worker_stdout.log').open('wb');worker=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
    responses=[]
    try:
        for index in range(25):
            path=out/'responses'/('%06d.json'%index);deadline=time.monotonic()+100
            while not path.exists():
                if worker.poll() is not None:raise RuntimeError('GPU worker exited before response')
                if time.monotonic()>deadline:raise TimeoutError('Worker response deadline')
                time.sleep(.01)
            response=json.loads(path.read_text());responses.append(response)
            if not response['passed']:raise RuntimeError(response.get('error','Worker inference failed'))
            if index<24:submit(index+1)
    finally:
        (out/'stop.flag').write_text('Offline worker integration test ended\n')
        try:code=worker.wait(timeout=30)
        except subprocess.TimeoutExpired:worker.terminate();code=worker.wait(timeout=10)
        log.close()
    first=np.array(responses[0]['pose']);last=np.array(responses[-1]['pose'])
    u,_,v=np.linalg.svd(last[:3,:3]@first[:3,:3].T);R=u@np.diag([1,1,np.linalg.det(u@v)])@v
    angle=float(np.degrees(np.arccos(np.clip((np.trace(R)-1)/2,-1,1))))
    change=float(np.linalg.norm(last[:3,3]-first[:3,3])*1000)
    yaw=responses[0]['registration_selection']['yaw_validation']
    passed=code==0 and yaw['changed'] and yaw['protrusion_recall']>.8 and angle<15
    for identifier in ['000000','000024']:
        shutil.copy2(out/'frames'/identifier/'overlay.jpg',out/(identifier+'_overlay.jpg'))
    report=dict(passed=passed,scope='Actual FoundationPose GPU worker on 25 repeats of one saved RGB-D; not independent 6D or moving-target accuracy',
        inference_frames=len(responses),worker_exit_code=code,yaw_initialization=yaw,
        rotation_change_from_corrected_init_deg=angle,translation_change_mm=change,
        final_tracking_consistent=responses[-1].get('tracking_consistent'),
        official_top1_preserved=(out/'frames/000000/official_top1_pose.txt').is_file(),
        original_top8_preserved=(out/'frames/000000/registration_candidates.json').is_file(),
        custom_yaw_candidates_preserved=(out/'frames/000000/registration_yaw_candidates.json').is_file(),
        live_fps_validated=False,pose_accuracy_validated=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
