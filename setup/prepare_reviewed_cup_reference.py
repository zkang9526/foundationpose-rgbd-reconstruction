"""Prepare a reviewed72 reference with explicit data-selected depth limits; originals unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import cv2
import numpy as np


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',type=Path,required=True)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--qa',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    qa=json.loads(args.qa.read_text(encoding='utf-8'))
    audit=json.loads((args.snapshot/'report.json').read_text())
    if (not qa['accepted_for_initial_reconstruction'] or not qa['visual_inspection_completed']
            or qa['audit_report_sha256']!=sha(args.snapshot/'report.json') or not audit['all_operation_replays_exact']
            or audit['human_confirmed_frames']!=72):
        raise ValueError('Reviewed audit evidence does not match')
    lo,hi=qa['derived_depth_range_mm_inclusive']
    if not 0<lo<hi<65536:raise ValueError('Expected explicit millimeter depth limits')
    meta=json.loads((args.scene/'metadata.json').read_text())
    if not meta['passed'] or not meta['pipeline_stopped'] or meta['saved_frames']!=72:
        raise ValueError('Capture must be complete and stopped')
    args.output.mkdir(parents=True,exist_ok=False)
    dest=args.output/args.scene.name
    for folder in ('rgb','depth','masks'):(dest/folder).mkdir(parents=True)
    record=dict(role='inverted_single_reference_ring',source_scene=str(args.scene),source_masks=str(args.snapshot),
                output_scene=dest.as_posix(),frames=[])
    for item in audit['frames']:
        f=item['frame'];name=f['frame']
        rgb,depth,mask=args.scene/'rgb'/name,args.scene/'depth'/name,args.snapshot/'masks'/name
        for path,key in ((rgb,'source_rgb_sha256'),(depth,'source_depth_sha256'),(mask,'mask_sha256')):
            if sha(path)!=f[key]:raise ValueError('Reviewed input SHA changed')
        d,m=cv2.imread(str(depth),-1),cv2.imread(str(mask),0)>0
        keep=m&(d>=lo)&(d<=hi)
        derived=np.where(keep,d,0).astype(np.uint16)
        if np.count_nonzero(keep)<100:raise ValueError('Insufficient prepared target depth')
        shutil.copy2(rgb,dest/'rgb'/name);shutil.copy2(mask,dest/'masks'/name)
        if not cv2.imwrite(str(dest/'depth'/name),derived):raise RuntimeError('Depth write failed')
        record['frames'].append(dict(frame=name,rgb_sha256=sha(rgb),mask_sha256=sha(mask),raw_depth_sha256=sha(depth),
            filtered_depth_sha256=sha(dest/'depth'/name),retained_target_percent=float(keep.sum()/m.sum()*100),
            rejected_positive_depth_pixels=int(((d>0)&m&~keep).sum())))
    for name in ('K.txt','cam_K.txt','depth_scale.txt','timestamps.csv','timestamps.json'):
        shutil.copy2(args.scene/name,dest/name)
    shutil.copy2(args.scene/'metadata.json',dest/'source_capture_metadata.json')
    shutil.copy2(args.qa,args.output/'mask_qa.json')
    report=dict(passed=True,status='complete',sequences=[record],depth_range_mm_inclusive=[lo,hi],
        raw_sources_modified=False,raw_human_masks_modified=False,interpolated_depth=False,
        mask_qa_sha256=sha(args.qa),source_audit_sha256=sha(args.snapshot/'report.json'),
        planned_angles_used_as_poses=False,geometry_validated=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,frames=72,video_dir=str(dest),range_mm=[lo,hi],
        retained_percent_mean=float(np.mean([v['retained_target_percent'] for v in record['frames']])))))


if __name__=='__main__':main()
