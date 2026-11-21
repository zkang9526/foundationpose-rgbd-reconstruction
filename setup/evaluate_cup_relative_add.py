#!/usr/bin/env python3
"""Mesh-point drift after one ArUco/estimated-pose anchor; not absolute GT ADD."""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import traceback
import uuid


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(8*1024*1024),b''):h.update(part)
    return h.hexdigest()


def host_path(path,root):
    path=Path(path)
    if str(path).startswith('/data/') and not path.exists():
        return root/'foundationpose_data'/path.relative_to('/data')
    return path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('/data/ZJC/foundationPos'))
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--mesh',type=Path,help='Exact source mesh, same object coordinates and meters')
    p.add_argument('--output',type=Path)
    p.add_argument('--samples',type=int,default=10000)
    p.add_argument('--seed',type=int,default=0)
    p.add_argument('--fixed-scene-confirmed',action='store_true',
                   help='User confirms cup AND marker fixed; camera alone moves')
    p.add_argument('--plot',action='store_true')
    p.add_argument('--no-adds',action='store_true')
    args=p.parse_args()
    session=args.session.resolve(strict=True)
    output=args.output or session/('relative_add_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    output.mkdir(parents=True,exist_ok=False)
    report=dict(passed=False,status='validating',session=str(session),output=str(output),
                metric='first_frame_anchored_relative_ADD',absolute_pose_accuracy_validated=False,
                reference_is_ground_truth=False,reference_uncertainty_measured=False,
                initial_pose_bias_removed=True,anchor_reset_after_reinitialization=False,
                units='mm',error_magnitude_filtering=False)
    try:
        import numpy as np
        import trimesh
        from cup_add_metrics import (validated_transform,add_error,adds_error,pose_error_mm_deg,
                                     stats_mm,sample_mesh_surface)
        host=json.loads((session/'session.json').read_text())
        worker=json.loads((session/'worker_report.json').read_text())
        if not host.get('ended_utc'):raise ValueError('Wait for the session to stop before evaluating')
        if not args.fixed_scene_confirmed or not host.get('aruco',{}).get('fixed_scene'):
            raise ValueError('Relative ADD requires fixed CUP AND MARKER, moving only the camera')
        if args.samples<100 or args.samples>100000:raise ValueError('Use 100..100000 fixed surface points')
        expected=host['mesh_sha256']
        meshpath=args.mesh or host_path(host.get('mesh_path') or worker['source_mesh'],args.root)
        if sha(meshpath)!=expected or worker['mesh_sha256']!=expected:
            raise ValueError('Session, worker and evaluation mesh SHA must agree')
        mesh=trimesh.load(str(meshpath),force='mesh',process=False)
        if not isinstance(mesh,trimesh.Trimesh) or not len(mesh.faces):raise ValueError('Triangle mesh required')
        if not np.isfinite(mesh.vertices).all() or np.max(mesh.extents)>.5 or np.min(mesh.extents)<.001:
            raise ValueError('This cup evaluator requires the saved meter-scale model')
        points=sample_mesh_surface(np.asarray(mesh.vertices),np.asarray(mesh.faces),args.samples,args.seed)
        np.save(str(output/'model_surface_points_m.npy'),points,allow_pickle=False)
        events=[json.loads(line) for line in (session/'frame_events.jsonl').read_text().splitlines() if line.strip()]
        if not events:raise ValueError('Session has no inference events')
        seen=set();records=[];files_verified=0
        aruco_settings=host['aruco']
        allowed={'rgb.npy','depth.npy','mask.png','capture.json','aruco.json'}
        for e in events:
            frame=e['frame']
            if not re.fullmatch(r'[0-9]{6}',frame) or frame in seen:raise ValueError('Duplicate or invalid frame ID')
            seen.add(frame);folder=session/'frames'/frame
            request_path=session/'requests'/(frame+'.json')
            request=json.loads(request_path.read_text())
            if request.get('frame')!=frame:raise ValueError('Request/frame mismatch')
            if e.get('request_sha256') and sha(request_path)!=e['request_sha256']:
                raise ValueError('Request evidence SHA changed: '+frame)
            for name,digest in request['input_sha256'].items():
                if name not in allowed or sha(folder/name)!=digest:
                    raise ValueError('Input evidence SHA changed: '+frame+'/'+name)
                files_verified+=1
            if not {'rgb.npy','depth.npy','capture.json','aruco.json'}<=set(request['input_sha256']):
                raise ValueError('Missing same-frame RGB-D/capture/reference hashes')
            marker=json.loads((folder/'aruco.json').read_text())
            reference_ok=bool(marker.get('reference_accepted'))
            M=None;E=None
            if reference_ok:
                if (marker.get('dictionary')!=aruco_settings['dictionary']
                    or marker.get('marker_id')!=aruco_settings['marker_id']
                    or abs(marker.get('measured_marker_length_m',-1)-aruco_settings['measured_black_side_m'])>1e-10):
                    raise ValueError('Marker specification changed within session')
                M=validated_transform(np.asarray(marker['pose_camera_from_marker']))
            if e.get('passed'):
                posefile=folder/'pose_camera_from_mesh.txt'
                if sha(posefile)!=e['pose_sha256']:raise ValueError('Pose evidence SHA changed: '+frame)
                E=validated_transform(np.loadtxt(posefile))
                if not np.allclose(E,np.asarray(e['pose']),atol=1e-5,rtol=0):
                    raise ValueError('Saved/event pose mismatch')
            records.append(dict(event=e,marker=marker,E=E,M=M))
        # Same convention as the existing confirmed-pose anchor. No future reset
        # when target is lost, manually reinitialized, or automatically recovered.
        anchor=next((r for r in records if r['E'] is not None and r['M'] is not None
                     and r['event'].get('accepted_for_tracking') and r['event'].get('pose_confirmed')),None)
        if anchor is None:raise ValueError('No confirmed estimate with accepted same-frame marker; keep target/marker visible until tracking confirmation')
        anchor_id=anchor['event']['frame']
        marker_from_mesh=np.linalg.inv(anchor['M'])@anchor['E']
        anchor_info=dict(frame=anchor_id,estimated_camera_from_mesh=anchor['E'].tolist(),
                         measured_camera_from_marker=anchor['M'].tolist(),
                         anchored_marker_from_mesh=marker_from_mesh.tolist(),
                         is_independently_calibrated=False,
                         scope='Computed from one estimated pose; initial object pose bias cancels')
        (output/'anchor.json').write_text(json.dumps(anchor_info,indent=2))
        rows=[];matrices=[];matrix_ids=[]
        for index,r in enumerate(records):
            e=r['event'];frame=e['frame']
            row=dict(frame=frame,operation=e.get('operation'),inference_passed=bool(e.get('passed')),
                     accepted_for_tracking=bool(e.get('accepted_for_tracking')),pose_confirmed=bool(e.get('pose_confirmed')),
                     reference_accepted=r['M'] is not None,is_anchor=frame==anchor_id,
                     relative_add_mm=None,relative_adds_mm=None,translation_error_mm=None,rotation_error_deg=None,
                     reason=None,reference_reason=r['marker'].get('reason'))
            if r['E'] is None:row['reason']='inference_failed'
            elif r['M'] is None:row['reason']='no_accepted_same_frame_marker'
            else:
                reference=r['M']@marker_from_mesh
                row.update(relative_add_mm=add_error(points,r['E'],reference)*1000,
                           relative_adds_mm=None if args.no_adds else adds_error(points,r['E'],reference)*1000,
                           **pose_error_mm_deg(r['E'],reference))
                matrices.append(reference);matrix_ids.append(frame)
            rows.append(row)
            if (index+1)%200==0:print(json.dumps(dict(evaluated=index+1,total=len(records))),flush=True)
        if matrices:
            np.savez_compressed(output/'anchored_reference_poses_m.npz',frames=np.asarray(matrix_ids),poses=np.asarray(matrices))
        def summarize(selected):
            result=dict(count=len(selected))
            for name in ['relative_add_mm','relative_adds_mm','translation_error_mm']:
                values=[r[name]/1000 for r in selected if r[name] is not None]
                result[name]=stats_mm(values)
            values=np.asarray([r['rotation_error_deg'] for r in selected],float)
            result['rotation_error_deg']=dict(count=len(values),mean=float(np.mean(values)),median=float(np.median(values)),
                p95=float(np.percentile(values,95)),rmse=float(np.sqrt(np.mean(values**2))),max=float(np.max(values))) if len(values) else None
            return result
        usable=[r for r in rows if r['relative_add_mm'] is not None and not r['is_anchor']]
        subsets=dict(all_numeric_estimates=summarize(usable),
                     accepted_for_tracking=summarize([r for r in usable if r['accepted_for_tracking']]),
                     confirmed_tracking=summarize([r for r in usable if r['pose_confirmed']]))
        with (output/'relative_add.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        report.update(passed=True,status='relative_drift_evaluated_not_absolute_accuracy',
                      anchor_frame=anchor_id,attempts=len(rows),inference_failed=sum(not r['inference_passed'] for r in rows),
                      marker_accepted_frames=sum(r['reference_accepted'] for r in rows),
                      paired_nonanchor_frames=len(usable),paired_coverage=len(usable)/max(1,len(rows)-1),
                      rows_without_valid_reference=sum(r['inference_passed'] and not r['reference_accepted'] for r in rows),
                      anchor_excluded_from_statistics=True,statistics=subsets,
                      source_session_ended_utc=host['ended_utc'],source_session_passed=host.get('passed'),
                      source_live_or_replay=host.get('source'),model_file=str(meshpath),model_sha256=expected,
                      point_sampling=dict(count=len(points),seed=args.seed,method='area-weighted fixed uniform surface samples',
                                          points_sha256=sha(output/'model_surface_points_m.npy')),
                      frame_input_files_sha_verified=files_verified,aruco=aruco_settings,
                      formula='reference_t = T_camera_from_marker_t @ inverse(T_camera_from_marker_anchor) @ estimated_T_camera_from_mesh_anchor',
                      camera_motion_only_declared=True,reference_model_unit='m',adds_direction='reference surface points query nearest estimated points',
                      evidence_sha256={n:sha(session/n) for n in ['session.json','frame_events.jsonl','worker_report.json']},
                      limitations=['Initial estimate bias is removed, so this is NOT absolute ADD precision.',
                                   'Fixed cup/marker condition is a user declaration, not verified by this software.',
                                   'ArUco reference noise, flips, calibration and mesh geometry affect these values.',
                                   'No error-magnitude clipping; all numeric/accepted/confirmed subsets reported separately.'])
        if args.plot:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig,axes=plt.subplots(3,1,figsize=(10,8),sharex=True,constrained_layout=True)
            x=[int(r['frame']) for r in rows]
            for key,label in [('relative_add_mm','relative ADD'),('relative_adds_mm','relative ADD-S')]:
                if key=='relative_adds_mm' and args.no_adds:continue
                axes[0].plot(x,[np.nan if r[key] is None else r[key] for r in rows],'.-',ms=2,lw=.7,label=label)
            for ax,key,unit in [(axes[1],'translation_error_mm','mm'),(axes[2],'rotation_error_deg','degrees')]:
                ax.plot(x,[np.nan if r[key] is None else r[key] for r in rows],'.-',ms=2,lw=.7);ax.set_ylabel(unit)
            axes[0].set_ylabel('model-point drift (mm)');axes[0].legend()
            axes[0].set_title('One first-frame anchor, never reset; relative drift, NOT absolute pose accuracy')
            for ax in axes:ax.axvline(int(anchor_id),color='gray',ls=':');ax.grid(alpha=.3)
            axes[2].set_xlabel('processed frame ID')
            fig.savefig(output/'relative_add.png',dpi=160);plt.close(fig)
    except Exception as error:
        report.update(status='failed',error=str(error),traceback=traceback.format_exc());traceback.print_exc()
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:report.get(k) for k in ['passed','status','output','anchor_frame','paired_nonanchor_frames','statistics','error']}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
