#!/usr/bin/env python3
"""Offline FoundationPose initialization/tracking with a neural-field model.

Runs the existing GPU worker without camera access. The field-derived cached
surface/colors are rendered by FoundationPose; no per-frame neural ray marching.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import uuid

from cup_neural_pose_model import validate_neural_model


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');tmp.replace(path)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('/data/ZJC/foundationPos'))
    p.add_argument('--model-manifest',type=Path,required=True)
    p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--scene',type=Path,required=True)
    p.add_argument('--mask-dir',type=Path,help='Directory containing same-frame binary PNG masks; defaults to scene/masks')
    p.add_argument('--frame-ids',help='Comma-separated six-digit image IDs; defaults to the field-reserved views')
    p.add_argument('--mode',choices=['independent','sequence','repeat'],default='independent')
    p.add_argument('--repeat-count',type=int,default=20,help='Repeat mode is a static integration check, never real-camera FPS')
    p.add_argument('--output',type=Path)
    p.add_argument('--worker-backend', choices=('docker', 'native'), default='docker')
    p.add_argument('--native-runtime', type=Path)
    p.add_argument('--inference-timeout', type=float, default=180)
    p.add_argument('--handle-local-init', action='store_true', help='Validate initialization with visible handle-hole mask evidence')
    args=p.parse_args()
    if args.inference_timeout <= 0 or (args.worker_backend == 'native' and args.native_runtime is None):
        p.error('Positive inference timeout and native runtime path required')
    root=args.root.resolve(strict=True);data=(root/'foundationpose_data').resolve(strict=True)
    selection=validate_neural_model(args.model_manifest,args.manifest_sha256)
    mesh=Path(selection['path']);mesh.relative_to(data)
    output=(args.output or data/'derived'/('neural_pose_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])).resolve()
    output.relative_to(data);output.mkdir(parents=True,exist_ok=False)
    for name in ['frames','requests','responses','processing','worker_code']:(output/name).mkdir()
    report=dict(passed=False,status='starting',model=selection,mode=args.mode,
                pose_definition='T_camera_from_field_object_meters',pose_is_ground_truth=False,
                direct_neural_renderer=False,live_fps_validated=False,pose_accuracy_validated=False,
                input_pose_used_for_initialization=False,frames=[],errors=[],output=str(output),
                segmentation_source='Provided same-frame masks, not automatic detector',
                repeat_is_static_sanity_check=args.mode=='repeat')
    worker=None;log=None;started=time.monotonic()
    try:
        import numpy as np
        import cv2
        ids=args.frame_ids.split(',') if args.frame_ids else ['%06d'%i for i in selection['reserved_view_ids']]
        if not ids or any(len(s)!=6 or not s.isdigit() for s in ids):raise ValueError('Expected six-digit frame IDs')
        if len(set(ids))!=len(ids):raise ValueError('Duplicate source IDs; use repeat mode for static checks')
        if args.repeat_count<1:raise ValueError('Repeat count must be positive')
        if args.mode=='sequence' and not args.frame_ids:
            raise ValueError('Sequence mode requires explicit temporally ordered frame IDs; reserved views are independent photographs')
        if args.mode=='repeat':
            if len(ids)!=1:raise ValueError('Repeat mode requires exactly one source frame')
            ids=ids*args.repeat_count
        masks=args.mask_dir or args.scene/'masks'
        K=np.loadtxt(args.scene/'K.txt')
        scale=float((args.scene/'depth_scale.txt').read_text())
        if K.shape!=(3,3) or not np.isfinite(K).all() or min(K[0,0],K[1,1])<=0 or abs(scale-.001)>1e-10:
            raise ValueError('Require valid aligned RGB intrinsics and saved uint16 millimeter depth')
        # Check every selected input before loading the GPU worker.
        inputs=[]
        for s in sorted(set(ids)):
            paths=[args.scene/'rgb'/(s+'.png'),args.scene/'depth'/(s+'.png'),masks/(s+'.png')]
            rgb=cv2.imread(str(paths[0]),-1);depth=cv2.imread(str(paths[1]),-1);mask=cv2.imread(str(paths[2]),-1)
            if rgb is None or depth is None or mask is None:raise ValueError('Missing RGB-D/Mask '+s)
            if (rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3 or depth.dtype!=np.uint16
                or depth.shape!=rgb.shape[:2] or mask.shape!=depth.shape or not set(np.unique(mask))<={0,255}
                or np.count_nonzero((mask>0)&(depth>0))<100):raise ValueError('Invalid same-frame RGB-D/Mask '+s)
            inputs.extend(dict(path=str(q),sha256=sha(q)) for q in paths)
        inputs.append(dict(path=str(args.scene/'K.txt'),sha256=sha(args.scene/'K.txt')))
        report['source_inputs']=inputs;report['source_frame_ids']=ids
        names=['run_cup_live_worker.py','run_cup_mesh_inference.py','verify_demo.py',
               'cup_pose_quality.py','cup_reacquisition.py','cup_handle_yaw.py', 'cup_pose_reference.py',
               'cup_initialization_consensus.py','cup_handle_local_selection.py','cup_warp_batch.py','cup_low_memory.py']
        for name in names:shutil.copy2(root/'setup'/name,output/'worker_code'/name)
        shutil.copy2(Path(__file__),output/'worker_code'/Path(__file__).name)
        shutil.copy2(root/'setup/cup_neural_pose_model.py',output/'worker_code/cup_neural_pose_model.py')
        report['code_sha256']={q.name:sha(q) for q in (output/'worker_code').glob('*.py')}
        shutil.copy2(args.model_manifest,output/'neural_model_manifest.json')
        mapped='/data/'+output.relative_to(data).as_posix()
        command=['/usr/bin/python3',str(root/'setup/run_logged.py'),'--root',str(root),
                 '--label','neural_field_surface_pose_worker','--note','Neural field-derived metric surface/colors; official FP pretrained; no GT.',
                 '--','docker','exec','-w','/workspace/FoundationPose','foundationpose',
                 '/usr/bin/timeout','--signal=TERM','--kill-after=10s','1200s',
                 '/opt/conda/envs/my/bin/python','-B','-u',mapped+'/worker_code/run_cup_live_worker.py',
                 '--session',mapped,'--repo','/workspace/FoundationPose',
                 '--mesh','/data/'+mesh.relative_to(data).as_posix(),'--mesh-sha256',selection['sha256'],'--fast']
        if args.worker_backend == 'native':
            runtime = args.native_runtime.resolve(strict=True)
            command = [sys.executable, str(root/'setup/run_logged.py'), '--root', str(root),
                       '--label', 'neural_field_native_pose_worker', '--note', 'Saved RGB-D; field surface; no GT',
                       '--', str(runtime/'env/bin/python'), '-B', '-u', str(output/'worker_code/run_cup_live_worker.py'),
                       '--session', str(output), '--repo', str(runtime/'FoundationPose'),
                       '--source-manifest', str(runtime/'source_sha256.json'),
                       '--mesh', str(mesh), '--mesh-sha256', selection['sha256'],
                       '--fast', '--low-memory', '--warp-batch-limit', '1']
        if args.handle_local_init:
            command.append('--handle-local-init')
        report['worker_command']=command
        atomic_json(output/'report.json',report)
        log=(output/'worker_stdout.log').open('wb')
        worker=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+120
        while not (output/'ready.json').exists():
            if worker.poll() is not None:raise RuntimeError('GPU worker exited before ready; inspect worker_stdout.log')
            if time.monotonic()>deadline:raise TimeoutError('GPU worker load timeout')
            time.sleep(.05)
        initialized=False;epoch=0
        for index,source_id in enumerate(ids):
            identifier='%06d'%index;folder=output/'frames'/identifier;folder.mkdir()
            operation='register' if args.mode=='independent' or not initialized else 'track'
            if operation=='register':epoch+=1
            rgb=cv2.cvtColor(cv2.imread(str(args.scene/'rgb'/(source_id+'.png'))),cv2.COLOR_BGR2RGB)
            depth=cv2.imread(str(args.scene/'depth'/(source_id+'.png')),-1)
            np.save(str(folder/'rgb.npy'),rgb);np.save(str(folder/'depth.npy'),depth)
            shutil.copy2(masks/(source_id+'.png'),folder/'mask.png')
            atomic_json(folder/'aruco.json',dict(found=False,reference_accepted=False))
            atomic_json(folder/'capture.json',dict(source_frame=source_id,mode=args.mode,source_scene=str(args.scene),is_live=False))
            request=dict(frame=identifier,operation=operation,tracking_epoch=epoch,K=K.tolist(),
                         source='offline saved RGB-D; no measured pose input',
                         input_sha256={n:sha(folder/n) for n in ['rgb.npy','depth.npy','mask.png','aruco.json','capture.json']})
            submitted=time.monotonic();atomic_json(output/'requests'/(identifier+'.json'),request)
            response_path=output/'responses'/(identifier+'.json');deadline=time.monotonic()+args.inference_timeout
            while not response_path.exists():
                if worker.poll() is not None:raise RuntimeError('GPU worker exited before response')
                if time.monotonic()>deadline:raise TimeoutError('GPU inference timeout')
                time.sleep(.01)
            result=json.loads(response_path.read_text())
            result.update(source_frame=source_id,output_frame=identifier,bridge_seconds=time.monotonic()-submitted)
            initialized=bool(result.get('passed') and result.get('tracking_consistent'))
            if result.get('passed'):
                # Surface and field share the same origin/axes; this alias is exact.
                shutil.copy2(folder/'pose_camera_from_mesh.txt',folder/'pose_camera_from_field.txt')
            else:report['errors'].append(dict(frame=identifier,error=result.get('error')))
            report['frames'].append(result);report['status']='running'
            atomic_json(output/'report.json',report)
            print(json.dumps(dict(frame=source_id,operation=operation,passed=result.get('passed'),consistent=initialized,
                                  seconds=result.get('worker_seconds'))),flush=True)
        report['inputs_unchanged']=all(sha(e['path'])==e['sha256'] for e in inputs)
        if not report['inputs_unchanged']:raise ValueError('Saved source inputs changed during inference')
        validate_neural_model(args.model_manifest,args.manifest_sha256)
        report['status']='completed_inference_requires_visual_review'
    except Exception as error:
        report['errors'].append(dict(error=str(error),traceback=traceback.format_exc()));report['status']='failed';traceback.print_exc()
    finally:
        (output/'stop.flag').write_text('Offline neural pose run ended\n')
        if worker is not None:
            try:report['worker_exit_code']=worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                worker.terminate()
                try:report['worker_exit_code']=worker.wait(timeout=10)
                except subprocess.TimeoutExpired:worker.kill();report['worker_exit_code']=worker.wait(timeout=10)
                report['errors'].append(dict(error='Worker stop timeout'))
        if log:log.close()
        report['passed']=bool(report['frames']) and not report['errors'] and report.get('worker_exit_code')==0
        report['elapsed_seconds']=time.monotonic()-started
        report['consistent_frames']=sum(bool(f.get('passed') and f.get('tracking_consistent')) for f in report['frames'])
        atomic_json(output/'report.json',report)
    print(json.dumps(dict(passed=report['passed'],frames=len(report['frames']),consistent=report['consistent_frames'],
                          output=str(output),worker_exit_code=report.get('worker_exit_code'))),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
