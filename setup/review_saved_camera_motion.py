#!/usr/bin/env python3
"""Recompute fixed-scene drift from immutable same-frame records after user confirmation."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--user-confirmed-fixed-scene', action='store_true', required=True)
    args = p.parse_args()
    session = args.session.resolve(strict=True)
    sys.path.insert(0, str(session.parents[2]/'setup'))
    from cup_aruco_reference import ArucoReference, rigid_error
    from summarize_cup_aruco_session import stats
    args.output.mkdir(parents=True, exist_ok=False)
    host = json.loads((session/'session.json').read_text())
    settings = host['aruco']
    events = [json.loads(x) for x in (session/'frame_events.jsonl').read_text().splitlines() if x.strip()]
    # Do not alter the original tracking-only report or enable errors retroactively in it.
    evaluator = ArucoReference(.030, 6, 'DICT_5X5_50', fixed_scene=True)
    rows, captures, markers, verified = [], {}, {}, 0
    rejection_reasons = Counter()
    epochs = Counter()
    for event in events:
        frame = event['frame']; folder = session/'frames'/frame
        request = json.loads((session/'requests'/(frame+'.json')).read_text())
        for name, digest in request['input_sha256'].items():
            if sha(folder/name) != digest:
                raise ValueError('Input SHA mismatch: '+str(folder/name))
            verified += 1
        if event['passed']:
            if sha(folder/'pose_camera_from_mesh.txt') != event['pose_sha256']:
                raise ValueError('Pose SHA mismatch: '+frame)
            if sha(folder/event['overlay_file']) != event['overlay_sha256']:
                raise ValueError('Overlay SHA mismatch: '+frame)
        capture = json.loads((folder/'capture.json').read_text())
        marker = json.loads((folder/'aruco.json').read_text())
        captures[frame] = capture; markers[frame] = marker
        if not marker.get('reference_accepted'):
            rejection_reasons[marker.get('reason', 'unknown')] += 1
        confirmed = (event.get('passed') and event.get('accepted_for_tracking') and event.get('pose_confirmed')
                     and not event.get('drained_after_stop'))
        evaluation = evaluator.evaluate(np.array(event['pose']), marker, frame, bool(confirmed)) if event.get('passed') else {}
        if evaluation.get('anchored_object_errors') is not None:
            rows.append(dict(frame=frame, tracking_epoch=event.get('tracking_epoch'), anchor_frame=evaluation['anchor_frame'],
                received_monotonic=capture['received_monotonic'], received_utc=capture['received_utc'],
                min_edge_pixels=marker.get('min_edge_pixels'), reprojection_rms_px=marker.get('reprojection_rms_px'),
                **evaluation['anchored_object_errors']))
        epochs[event.get('tracking_epoch')] += 1
    nonanchor = [r for r in rows if r['frame'] != r['anchor_frame']]
    def errors(values):
        return dict(count=len(values), translation_mm=stats([r['translation_error_mm'] for r in values]),
                    rotation_deg=stats([r['rotation_error_deg'] for r in values]))
    recovery_path = session/'recovery_events.jsonl'
    recovery = [json.loads(x) for x in recovery_path.read_text().splitlines() if x.strip()] if recovery_path.exists() else []
    # Compare close consecutive accepted reference frames with the independently saved estimator.
    # This does not delete errors or prove either estimator correct; it locates reference discontinuities.
    reference_steps=[]
    for previous,event in zip(events,events[1:]):
        a,b=previous['frame'],event['frame']
        if not (markers[a].get('reference_accepted') and markers[b].get('reference_accepted')):continue
        dt=captures[b]['received_monotonic']-captures[a]['received_monotonic']
        if not 0 < dt <= .15:continue
        marker_step=rigid_error(np.array(markers[b]['pose_camera_from_marker']),np.array(markers[a]['pose_camera_from_marker']))
        pose_step=rigid_error(np.array(event['pose']),np.array(previous['pose']))
        corner_step=float(np.median(np.linalg.norm(np.array(markers[b]['corners_px'])-np.array(markers[a]['corners_px']),axis=1)))
        reference_steps.append(dict(previous=a,frame=b,seconds=dt,marker_step=marker_step,estimated_object_step=pose_step,median_marker_corner_displacement_px=corner_step))
    suspicious=[r for r in reference_steps if r['marker_step']['rotation_error_deg']>20 and r['estimated_object_step']['rotation_error_deg']<5 and r['median_marker_corner_displacement_px']<3]
    report = dict(passed=True, session=str(session), original_session_fixed_scene=settings.get('fixed_scene'),
        offline_protocol_source='User confirmed on 2026-10-18: only camera moved; cup and marker remained fixed',
        original_sources_modified=False, original_online_error_report_retained=True,
        scope='Object-origin drift from first accepted confirmed same-frame estimate; initial bias removed; global anchor retained across recovery',
        absolute_pose_accuracy_validated=False, reference_uncertainty_measured=False,
        marker_length_m=.030, marker_id=6, dictionary='DICT_5X5_50',
        frames=len(events), inference_failed=sum(not e['passed'] for e in events),
        pose_confirmed=sum(bool(e.get('pose_confirmed')) for e in events),
        tracking_rejected=sum(bool(e.get('passed')) and not e.get('accepted_for_tracking') for e in events),
        registrations=[dict(frame=e['frame'], tracking_epoch=e.get('tracking_epoch'), selection=e.get('registration_selection')) for e in events if e['operation']=='register'],
        anchor_frame=evaluator.anchor_frame, paired_frames=len(rows), paired_coverage=len(rows)/len(events),
        marker_reference_accepted=sum(bool(m.get('reference_accepted')) for m in markers.values()),
        marker_found=sum(bool(m.get('found')) for m in markers.values()), marker_rejections=dict(rejection_reasons),
        accepted_marker_min_edge_px=stats([m['min_edge_pixels'] for m in markers.values() if m.get('reference_accepted')]),
        all_accepted_pairs_nonanchor=errors(nonanchor),
        epochs_with_global_anchor={str(epoch):dict(processed_frames=count, **errors([r for r in nonanchor if r['tracking_epoch']==epoch])) for epoch,count in epochs.items()},
        marker_40px_subset_nonanchor=errors([r for r in nonanchor if r['min_edge_pixels']>=40]),
        close_consecutive_reference_pairs=len(reference_steps),
        large_marker_rotation_with_small_image_and_object_motion=len(suspicious),
        reference_discontinuity_examples=sorted(suspicious,key=lambda r:r['marker_step']['rotation_error_deg'],reverse=True)[:10],
        steady_processing_fps=host.get('steady_processing_fps'),
        tracking_latency_ms=stats([e['host_receive_to_result_seconds']*1000 for e in events if e['operation']=='track']),
        rgb_depth_timestamp_gap_ms=stats([abs(c['rgb_depth_timestamp_gap_ms']) for c in captures.values()]),
        input_files_sha256_verified=verified, pose_and_overlay_sha256_verified=sum(e['passed'] for e in events)*2,
        recovery_event_counts=dict(Counter(r['event'] for r in recovery)),
        recovery_events=[{k:v for k,v in r.items() if k in ['event','time_utc','revision','source_sequence','matched','attempt','queued_for_registration','motion','error']} for r in recovery],
        control_events=[json.loads(x) for x in (session/'controls.jsonl').read_text().splitlines() if x.strip()],
        evidence_sha256={n:sha(session/n) for n in ['session.json','frame_events.jsonl','controls.jsonl','K.txt','recovery_events.jsonl']},
        paired_errors=rows)
    # No filtering by measured error. Show all original quality-gated pairs and any high-resolution subset explicitly.
    with (args.output/'relative_drift.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['frame'])
        writer.writeheader();writer.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    t0=captures[events[0]['frame']]['received_monotonic']
    fig,axes=plt.subplots(3,1,figsize=(10,8),constrained_layout=True)
    for epoch in epochs:
        selected=[r for r in rows if r['tracking_epoch']==epoch]
        for ax,key in zip(axes[:2],['translation_error_mm','rotation_error_deg']):
            ax.plot([r['received_monotonic']-t0 for r in selected],[r[key] for r in selected],'.',ms=2,label='Epoch '+str(epoch))
    axes[0].set_title('Fixed-scene drift relative to first accepted pose; initial bias removed')
    axes[0].set_ylabel('Translation (mm)');axes[1].set_ylabel('Rotation (degrees)')
    axes[2].plot([captures[e['frame']]['received_monotonic']-t0 for e in events],
                 [markers[e['frame']].get('min_edge_pixels',np.nan) for e in events],'.',ms=2)
    axes[2].axhline(25,color='orange',ls='--',label='Existing reference gate 25px')
    axes[2].axhline(40,color='green',ls='--',label='Recommended 40px')
    axes[2].set_ylabel('Marker short edge (px)');axes[2].set_xlabel('Captured time from first frozen image (s)')
    for ax in axes:ax.grid(alpha=.3);ax.legend(loc='upper left',fontsize=8)
    fig.savefig(args.output/'camera_motion_drift.png',dpi=160);plt.close(fig)
    samples={0,3,len(events)//4,len(events)//2,3*len(events)//4,len(events)-1}
    for index,e in enumerate(events):
        if e['operation']=='register':samples.update([max(0,index-1),index,min(len(events)-1,index+3)])
    for key in ['translation_error_mm','rotation_error_deg']:
        if nonanchor:samples.add(int(max(nonanchor,key=lambda r:r[key])['frame']))
    panels=[]
    for index in sorted(samples):
        e=events[index];frame=e['frame'];folder=session/'frames'/frame
        rgb=cv2.cvtColor(np.load(folder/'rgb.npy',allow_pickle=False),cv2.COLOR_RGB2BGR)
        overlay=cv2.imread(str(folder/e['overlay_file']))
        marker=markers[frame]
        if marker.get('found'):
            corners=np.rint(marker['corners_px']).astype(np.int32)
            cv2.polylines(rgb,[corners],True,(0,190,0) if marker.get('reference_accepted') else (0,150,255),1)
        row=next((r for r in rows if r['frame']==frame),None)
        label=f"Frame {frame} | epoch {e.get('tracking_epoch')} | {e['operation']}"
        if row:label+=f" | {row['translation_error_mm']:.1f}mm {row['rotation_error_deg']:.1f}deg"
        for im in [rgb,overlay]:
            cv2.rectangle(im,(0,0),(640,27),(245,245,245),-1)
            cv2.putText(im,label,(5,18),cv2.FONT_HERSHEY_SIMPLEX,.40,(0,0,0),1,cv2.LINE_AA)
        panel=np.concatenate([rgb,overlay],axis=1)
        name=frame+'_comparison.jpg';cv2.imwrite(str(args.output/name),panel)
        panels.append(dict(frame=frame,file=name,errors=row,tracking_consistent=e.get('tracking_consistent')))
    report['visual_samples']=panels
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['paired_errors','recovery_events','control_events','visual_samples','evidence_sha256']},indent=2),flush=True)


if __name__=='__main__':main()
