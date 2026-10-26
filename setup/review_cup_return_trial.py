#!/usr/bin/env python3
"""Audit immutable SAM2 search masks, movement guards and registration cancellation."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    session=args.session
    events=[json.loads(x) for x in (session/'frame_events.jsonl').read_text().splitlines() if x.strip()]
    recovery=[json.loads(x) for x in (session/'recovery_events.jsonl').read_text().splitlines() if x.strip()]
    controls=[json.loads(x) for x in (session/'controls.jsonl').read_text().splitlines() if x.strip()]
    consumed={e.get('attempt'):e for e in recovery if e['event']=='search_consumed'}
    searches=[];checked=0;contact=[]
    for event in recovery:
        if event['event']!='search_result':continue
        metadata=event.get('metadata') or {};attempt=metadata.get('attempt')
        if not attempt:continue
        folder=session/attempt;result=json.loads((folder/'result.json').read_text())
        request=json.loads((folder/'request.json').read_text())
        for name,digest in [('rgb.npy',result['rgb_sha256']),('request.json',result['request_sha256']),
                (result['artifact'],result['artifact_sha256']),('capture.json',request['capture_sha256']),('depth.npy',request['depth_sha256'])]:
            assert sha(folder/name)==digest,'Search evidence changed: '+str(folder/name)
            checked+=1
        selection=event.get('selection') or {};selected=selection.get('selected')
        rgb=np.load(folder/'rgb.npy',allow_pickle=False);vis=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
        mask=None
        if selected is not None:
            with np.load(folder/'proposals.npz',allow_pickle=False) as archive:mask=archive['masks'][selected]>0
            vis[mask]=(vis[mask]*.65+np.array([0,220,255])*.35).astype(np.uint8)
            cv2.drawContours(vis,cv2.findContours(mask.astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[-2],-1,(0,220,255),1)
        consumption=consumed.get(attempt,{})
        row=dict(time_utc=event['time_utc'],attempt=attempt,matched=event.get('matched'),
            host_seconds=metadata.get('host_seconds'),selected=next((v for v in selection.get('candidates',[]) if v['index']==selected),None),
            motion=consumption.get('motion'),queued_for_registration=consumption.get('queued_for_registration'),
            source_rgb_sha256=result['rgb_sha256'],proposals_sha256=result['artifact_sha256'])
        name=folder.name+'_mask.jpg';row['panel']=name
        label='Matched candidate' if selected is not None else 'No matching candidate'
        flow=(row['motion'] or {}).get('median_flow_px')
        if flow is not None:label+=' | flow %.1fpx'%flow
        label+=' | queued '+str(row['queued_for_registration'])
        cv2.rectangle(vis,(0,0),(640,27),(240,240,240),-1)
        cv2.putText(vis,label,(6,18),cv2.FONT_HERSHEY_SIMPLEX,.44,(0,0,0),1,cv2.LINE_AA)
        cv2.imwrite(str(args.output/name),vis)
        searches.append(row);contact.append(cv2.resize(vis,(480,360)))
    while len(contact)%2:contact.append(np.full_like(contact[0],245))
    if contact:cv2.imwrite(str(args.output/'search_contact.jpg'),np.concatenate([np.concatenate(contact[i:i+2],axis=1) for i in range(0,len(contact),2)],axis=0))
    fields=['frame','operation','accepted_for_tracking','pose_confirmed','state_revision_current','drained_after_stop',
        'initialization_current_frame_check','initialization_marker_movement_check','registration_selection','depth_quality','host_receive_to_result_seconds']
    registrations=[{k:e[k] for k in fields if k in e} for e in events if e['operation']=='register']
    def times(event):
        capture=json.loads((session/'frames'/event['frame']/'capture.json').read_text())
        received=datetime.fromisoformat(capture['received_utc'])
        completed=received+timedelta(seconds=event['host_receive_to_result_seconds'])
        return received,completed
    episodes=[]
    for index,event in enumerate(events):
        if event['operation']!='register' or index==0:continue
        epoch=event.get('tracking_epoch')
        losses=[e for e in events[:index] if e['operation']=='track' and not e.get('tracking_consistent')]
        confirmed=[e for e in events[index:] if e.get('tracking_epoch')==epoch and e.get('pose_confirmed')]
        item=dict(registration_frame=event['frame'],epoch=epoch,registration_accepted=event.get('accepted_for_tracking'),
                  confirmed_frames=len(confirmed),first_confirmed_frame=confirmed[0]['frame'] if confirmed else None,
                  registration_input_utc=times(event)[0].isoformat(),registration_result_utc=times(event)[1].isoformat(),
                  time_scope='Host completion reconstructed from saved input receive UTC plus saved host latency; not sensor exposure time')
        if confirmed:
            received,completed=times(confirmed[0]);last=times(confirmed[-1])
            item.update(first_confirmed_input_utc=received.isoformat(),first_confirmed_result_utc=completed.isoformat(),
                confirmation_after_registration_result_seconds=(completed-times(event)[1]).total_seconds(),
                confirmed_tracking_span_seconds=(last[1]-completed).total_seconds())
            if losses:
                loss=losses[-1];item.update(loss_frame=loss['frame'],loss_result_utc=times(loss)[1].isoformat(),
                    loss_to_first_confirmed_result_seconds=(completed-times(loss)[1]).total_seconds())
        episodes.append(item)
    report=dict(session=str(session),frames=len(events),registrations=registrations,searches=searches,
        search_count=len(searches),matching_candidates=sum(bool(r['matched']) for r in searches),
        motion_rejected_matching_candidates=sum(bool(r['matched']) and not r['queued_for_registration'] for r in searches),
        queued=sum(bool(r['queued_for_registration']) for r in searches),controls=controls,recovery_episodes=episodes,
        verified_search_files=checked,raw_sources_modified=False,
        live_recovery_confirmed_in_saved_results=any(e['registration_accepted'] and e['confirmed_frames']>=3 for e in episodes),
        physical_pose_accuracy_validated=False,
        cancellation_scope='A valid offline pose whose host control revision changed is not a confirmed live recovery',
        evidence_sha256={n:sha(session/n) for n in ['session.json','frame_events.jsonl','recovery_events.jsonl','controls.jsonl']})
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['searches','controls','evidence_sha256','registrations']},indent=2),flush=True)


if __name__=='__main__':main()
