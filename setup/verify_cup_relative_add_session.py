#!/usr/bin/env python3
"""Synthetic session tests: anchor direction, reinitialization, missing data, SHA."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    import trimesh
    scene=a.output/'synthetic_session';scene.mkdir()
    (scene/'frames').mkdir();(scene/'requests').mkdir()
    mesh=trimesh.creation.box(extents=[.02,.03,.04]);mesh.export(str(scene/'model.obj'))
    mesh_sha=sha(scene/'model.obj')
    marker_settings=dict(fixed_scene=True,dictionary='DICT_5X5_50',marker_id=6,measured_black_side_m=.03)
    write(scene/'session.json',dict(ended_utc='2026-11-04T00:00:00+00:00',passed=False,
          source='synthetic_numerical_test_not_physical_measurement',mesh_sha256=mesh_sha,
          mesh_path=str(scene/'model.obj'),aruco=marker_settings))
    write(scene/'worker_report.json',dict(source_mesh=str(scene/'model.obj'),mesh_sha256=mesh_sha))
    E0=np.eye(4);E0[:3,3]=[.1,.2,.5]
    M0=np.eye(4);M0[:3,3]=[-.1,.1,.6]
    K=[[600,0,1],[0,600,1],[0,0,1]]
    events=[]
    for i in range(5):
        frame='%06d'%i;folder=scene/'frames'/frame;folder.mkdir()
        theta=i*.3;G=np.eye(4);G[:3,:3]=[[np.cos(theta),-np.sin(theta),0],[np.sin(theta),np.cos(theta),0],[0,0,1]]
        G[:3,3]=[i*.02,-i*.01,i*.005]
        M=G@M0;E=G@E0
        if i==2:E[0,3]+=.004
        if i==3:E[0,3]+=.100
        np.save(folder/'rgb.npy',np.zeros((3,3,3),np.uint8));np.save(folder/'depth.npy',np.ones((3,3),np.uint16)*500)
        write(folder/'capture.json',dict(source='synthetic_test',received_monotonic=float(i)))
        write(folder/'aruco.json',dict(reference_accepted=i!=3,found=i!=3,dictionary='DICT_5X5_50',
              marker_id=6,measured_marker_length_m=.03,pose_camera_from_marker=M.tolist(),
              reason='synthetic test reference' if i!=3 else 'synthetic missing marker'))
        request=dict(frame=frame,operation='register' if i in [0,2] else 'track',K=K,
                     input_sha256={n:sha(folder/n) for n in ['rgb.npy','depth.npy','capture.json','aruco.json']})
        req=scene/'requests'/(frame+'.json');write(req,request)
        event=dict(frame=frame,operation=request['operation'],passed=i!=4,
                   accepted_for_tracking=i in [0,1],pose_confirmed=i in [0,1],
                   request_sha256=sha(req))
        if i!=4:
            np.savetxt(folder/'pose_camera_from_mesh.txt',E,fmt='%.12g')
            event.update(pose=E.tolist(),pose_sha256=sha(folder/'pose_camera_from_mesh.txt'))
        events.append(event)
    (scene/'frame_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    entry=Path(__file__).resolve().parent/'evaluate_cup_relative_add.py'
    checks=[]
    def run(label,source,expected_success=True):
        out=a.output/label
        r=subprocess.run([sys.executable,'-B',str(entry),'--session',str(source),'--mesh',str(scene/'model.obj'),
                          '--output',str(out),'--samples','500','--fixed-scene-confirmed'],capture_output=True,text=True)
        write(a.output/(label+'_process.json'),dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        if (r.returncode==0)!=expected_success:raise AssertionError(label+' unexpected exit: '+r.stdout+r.stderr)
        return json.loads((out/'report.json').read_text())
    report=run('valid_relative',scene)
    assert report['anchor_frame']=='000000' and report['paired_nonanchor_frames']==2
    stats=report['statistics']['all_numeric_estimates']['relative_add_mm']
    assert abs(stats['mean']-2)<1e-6 and abs(stats['max']-4)<1e-6
    assert report['statistics']['confirmed_tracking']['relative_add_mm']['max']<1e-6
    assert report['source_session_passed'] is False and report['inference_failed']==1
    checks+=['camera_transform_composition_correct','anchor_not_reset_by_registration','rejected_numeric_estimate_retained',
             'missing_marker_not_zero_filled','failed_capture_session_still_evaluated','anchor_zero_excluded']
    for label,edit,expected in [
        ('duplicate_frame',lambda s:(s/'frame_events.jsonl').open('a').write(json.dumps(events[1])+'\n'),'Duplicate'),
        ('tampered_input',lambda s:np.save(s/'frames/000001/rgb.npy',np.ones((3,3,3),np.uint8)),'Input evidence SHA'),
        ('no_confirmed_anchor',None,'No confirmed estimate')]:
        source=a.output/(label+'_source');shutil.copytree(scene,source)
        if edit:edit(source)
        else:
            changed=copy.deepcopy(events)
            for e in changed:e['pose_confirmed']=False
            (source/'frame_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in changed))
        invalid=run(label,source,False)
        assert expected in invalid['error'];checks.append(label+'_rejected')
    write(a.output/'verification.json',dict(passed=True,checks=checks,physical_accuracy_measured=False))
    print(json.dumps(dict(passed=True,checks=len(checks),scope='synthetic session invariants, not physical accuracy')),flush=True)


if __name__=='__main__':main()
