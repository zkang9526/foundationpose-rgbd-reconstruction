#!/usr/bin/env python3
"""Capture fixed-cup/marker tracking, then compute first-frame relative ADD."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    from cup_mesh_selection import add_mesh_arguments,resolve_mesh
    p=argparse.ArgumentParser(description=__doc__,
        epilog='Keep CUP and marker rigidly fixed; move only the camera. Relative ADD removes initial pose bias and is not absolute accuracy.')
    p.add_argument('--root',type=Path,default=Path('/data/ZJC/foundationPos'))
    add_mesh_arguments(p);p.set_defaults(mesh_profile='redcup72')
    p.add_argument('--duration-seconds',type=float,default=600)
    p.add_argument('--max-frames',type=int,default=3000)
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--output',type=Path)
    p.add_argument('--samples',type=int,default=10000)
    p.add_argument('--seed',type=int,default=0)
    p.add_argument('--no-adds',action='store_true')
    p.add_argument('--no-cup-yaw-init',action='store_true')
    p.add_argument('--mask-backend',choices=['sam','sam2','grabcut'],default='sam2')
    p.add_argument('--marker-length-m',type=float,default=.030,help='Measured BLACK outer square side')
    p.add_argument('--marker-id',type=int,default=6)
    p.add_argument('--marker-dictionary',choices=['DICT_4X4_50','DICT_5X5_50','DICT_6X6_50','DICT_7X7_50'],default='DICT_5X5_50')
    p.add_argument('--evaluation-python',type=Path,default=Path('/home/YOUR_USER/anaconda3/envs/foundationpose/bin/python'))
    p.add_argument('--check',action='store_true',help='Check model, evaluator and CLI without opening the camera')
    args=p.parse_args()
    if not (0<args.marker_length_m<1 and args.duration_seconds>0 and args.max_frames>0
            and 1<=args.port<=65535 and 100<=args.samples<=100000 and 0<=args.marker_id<50):
        p.error('Invalid marker, duration, port, frame count or sample count')
    root=args.root.resolve(strict=True);data=(root/'foundationpose_data').resolve(strict=True)
    selection=resolve_mesh(data,args.mesh_profile)
    check=subprocess.run([str(args.evaluation_python),'-B','-c',
                          'import numpy, scipy, trimesh, matplotlib;print("Relative ADD CPU dependencies ready")'],check=False)
    if check.returncode:raise RuntimeError('Evaluation environment unavailable; no camera opened')
    if args.check:
        print(json.dumps(dict(passed=True,camera_opened=False,model=selection,
                              reference='single fixed first-confirmed ArUco/pose anchor; NOT absolute GT')),flush=True)
        return 0
    identifier='mesh_add_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    output=(args.output or data/'live_sessions'/identifier).resolve()
    output.relative_to(data)
    if output.exists():raise FileExistsError('Use a new capture directory')
    output.parent.mkdir(parents=True,exist_ok=True)
    protocol=output.with_name(output.name+'_protocol');protocol.mkdir(exist_ok=False)
    shutil.copy2(selection['path'],protocol/'model.obj')
    if sha(protocol/'model.obj')!=selection['sha256']:raise ValueError('Model snapshot SHA differs')
    for name in ['run_cup_mesh_add.py','evaluate_cup_relative_add.py','cup_add_metrics.py','run_cup_mesh_add.sh']:
        shutil.copy2(root/'setup'/name,protocol/name)
    metadata=dict(scope='first-frame anchored model-point drift, not absolute ADD accuracy',
                  fixed_cup_and_marker_declared=True,camera_only_motion_declared=True,
                  physical_conditions_verified_by_software=False,mesh=selection,session=str(output),
                  same_anchor_retained_after_relocalization=True,samples=args.samples,seed=args.seed,
                  marker=dict(id=args.marker_id,dictionary=args.marker_dictionary,black_side_m=args.marker_length_m))
    (protocol/'measurement_protocol.json').write_text(json.dumps(metadata,indent=2))
    capture=['bash',str(root/'setup/run_cup_live_fast.sh'),'--root',str(root),'--output',str(output),
             '--mesh-profile',args.mesh_profile,'--mask-backend',args.mask_backend,'--auto-reacquire',
             '--duration-seconds',str(args.duration_seconds),'--max-frames',str(args.max_frames),'--port',str(args.port),
             '--aruco-id',str(args.marker_id),'--aruco-dictionary',args.marker_dictionary,
             '--aruco-marker-length-m',str(args.marker_length_m),'--aruco-fixed-scene']
    if args.mesh_profile=='redcup72' and not args.no_cup_yaw_init:capture.append('--cup-yaw-init')
    print('Keep cup AND marker fixed; move ONLY camera. Relative ADD is not absolute pose accuracy.',flush=True)
    print('Capture session: '+str(output),flush=True)
    child=subprocess.Popen(capture)
    try:capture_exit=child.wait()
    except KeyboardInterrupt:
        print('Waiting for capture to finish saving records...',flush=True)
        capture_exit=child.wait(timeout=180)
    metadata['capture_exit_code']=capture_exit
    evaluation_exit=None
    if (output/'session.json').exists() and (output/'frame_events.jsonl').exists():
        command=['/usr/bin/python3',str(root/'setup/run_logged.py'),'--root',str(root),
                 '--label','cup_mesh_relative_add_summary',
                 '--note','Fixed cup/marker; first confirmed estimated pose anchor, never reset; relative model-point drift, no GT.',
                 '--',str(args.evaluation_python),'-B',str(protocol/'evaluate_cup_relative_add.py'),
                 '--root',str(root),'--session',str(output),'--mesh',str(protocol/'model.obj'),
                 '--output',str(output/'relative_add'),'--fixed-scene-confirmed',
                 '--samples',str(args.samples),'--seed',str(args.seed),'--plot']
        if args.no_adds:command.append('--no-adds')
        evaluation_exit=subprocess.run(command,check=False).returncode
    metadata.update(evaluation_exit_code=evaluation_exit,
                    relative_add_report=str(output/'relative_add/report.json'),
                    relative_add_csv=str(output/'relative_add/relative_add.csv'),
                    relative_add_plot=str(output/'relative_add/relative_add.png'))
    (protocol/'completion.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(dict(capture_exit_code=capture_exit,evaluation_exit_code=evaluation_exit,
                          session=str(output),report=str(output/'relative_add/report.json'),
                          absolute_pose_accuracy_validated=False)),flush=True)
    return 0 if capture_exit==0 and evaluation_exit==0 else 1


if __name__=='__main__':raise SystemExit(main())
