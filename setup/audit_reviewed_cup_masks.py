"""Read-only audit and immutable snapshot of a fully human-reviewed RGB-D mask ring."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import cv2
import numpy as np
from PIL import Image, ImageDraw
from manual_mask_editor import render_mask, mask_bytes


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def stats(values):
    v=np.asarray(values,float)
    return dict(minimum=float(v.min()),mean=float(v.mean()),median=float(np.median(v)),maximum=float(v.max()))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',type=Path,required=True)
    p.add_argument('--masks',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    scene,masks,output=args.scene.resolve(strict=True),args.masks.resolve(strict=True),args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('masks','annotations','proposal_masks','contact'):
        (output/folder).mkdir()
    source_report=read(masks/'report.json')
    source_sha=sha(masks/'report.json')
    state=read(masks/'state.json')
    state_sha=sha(masks/'state.json')
    if (source_report['source_scene']!=str(scene) or not source_report['all_frames_human_confirmed']
            or source_report['total_frames']!=72 or source_report['confirmed_frames']!=72 or len(state)!=72):
        raise ValueError('Expected72 confirmed masks for this exact source scene')
    proposals=read(masks/'proposals'/'index.json') if (masks/'proposals'/'index.json').exists() else dict(frames=[])
    proposal_map={x['proposal_id']:x for x in proposals['frames']}
    rows,thumbs,pooled=[],[],[]
    for i,frame in enumerate(source_report['frames']):
        name='%06d.png'%i
        if frame['frame']!=name or not frame['confirmed'] or state[name]!=frame['latest_revision']:
            raise ValueError('Mask state/report order changed')
        rgb_path,depth_path,mask_path=scene/'rgb'/name,scene/'depth'/name,masks/'masks'/name
        for path,key in ((rgb_path,'source_rgb_sha256'),(depth_path,'source_depth_sha256'),(mask_path,'mask_sha256')):
            if sha(path)!=frame[key]:raise ValueError('Source SHA changed: '+str(path))
        rev=masks/'revisions'/state[name]
        annotation=read(rev/'annotation.json')
        if (annotation['confirmed_by']!='human_browser_action' or annotation['mask_sha256']!=frame['mask_sha256']
                or annotation['confirmed_preview_sha256']!=frame['mask_sha256'] or sha(rev/'mask.png')!=frame['mask_sha256']
                or any(annotation['frame'][key]!=frame[key] for key in ('frame','source_rgb_sha256','source_depth_sha256'))):
            raise ValueError('Human revision provenance mismatch')
        def resolve(key):
            item=proposal_map[key]
            path=masks/'proposals'/'masks'/name
            if (item['frame']!=name or sha(path)!=item['mask_sha256']
                    or item['source_rgb_sha256']!=frame['source_rgb_sha256']):
                raise ValueError('Proposal source differs')
            if not (output/'proposal_masks'/name).exists():shutil.copy2(path,output/'proposal_masks'/name)
            with Image.open(path) as im:return im.copy()
        replay=mask_bytes(render_mask(frame['size'],annotation['operations'],resolve))
        if hashlib.sha256(replay).hexdigest()!=frame['mask_sha256']:
            raise ValueError('Operations do not reproduce confirmed binary Mask')
        rgb=cv2.imread(str(rgb_path))
        depth=cv2.imread(str(depth_path),-1)
        binary=cv2.imread(str(mask_path),-1)
        if (binary is None or binary.shape!=(480,640) or binary.dtype!=np.uint8
                or not set(np.unique(binary)) <= {0,255} or not np.any(binary)
                or depth is None or depth.shape!=binary.shape or depth.dtype!=np.uint16):
            raise ValueError('Invalid original resolution binary Mask/depth')
        selected=binary>0
        values=depth[selected]
        positive=values[values>0]
        if len(positive)<100:raise ValueError('Insufficient object depth in '+name)
        pooled.append(positive)
        components,labels,areas,_=cv2.connectedComponentsWithStats(selected.astype(np.uint8),8)
        foreground_areas=sorted(areas[1:,cv2.CC_STAT_AREA].tolist(),reverse=True)
        ys,xs=np.nonzero(selected)
        row=dict(frame=frame,annotation_method=annotation.get('annotation_method','manual_from_scratch'),
            annotation_sha256=sha(rev/'annotation.json'),mask_pixels=int(selected.sum()),
            bbox_xyxy=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)],
            components=components-1,component_areas=foreground_areas,
            valid_depth_percent=float(np.count_nonzero(values)/len(values)*100),
            positive_depth_mm_percentiles=np.percentile(positive,[.5,5,50,95,99.5]).tolist(),
            depth_outside_300_800_pixels=int(np.count_nonzero((values>0)&((values<300)|(values>800)))),
            depth_over_1500_pixels=int(np.count_nonzero(values>1500)))
        rows.append(row)
        shutil.copy2(mask_path,output/'masks'/name)
        shutil.copy2(rev/'annotation.json',output/'annotations'/(Path(name).stem+'.json'))
        overlay=rgb.copy()
        overlay[selected]=(overlay[selected]*.68+np.array([0,215,255])*.32).astype(np.uint8)
        contours,_=cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay,contours,-1,(255,0,255),1)
        picture=Image.fromarray(cv2.cvtColor(overlay,cv2.COLOR_BGR2RGB)).crop((225,250,455,450)).resize((322,280))
        thumbs.append((name,picture))
    if sha(masks/'state.json')!=state_sha or sha(masks/'report.json')!=source_sha:
        raise ValueError('User saved while auditing; preserve this attempt and retry a new snapshot')
    for start in range(0,len(thumbs),8):
        page=thumbs[start:start+8]
        sheet=Image.new('RGB',(1288,612),(25,25,25))
        draw=ImageDraw.Draw(sheet)
        for j,(name,picture) in enumerate(page):
            x,y=j%4*322,j//4*306
            draw.text((x+5,y+5),name+' HUMAN REVIEWED',fill='white')
            sheet.paste(picture,(x,y+26))
        sheet.save(output/'contact'/('masks_%02d.png'%(start//8)))
    for filename in ('report.json','state.json','manual_editor.json','imported_from.json'):
        if (masks/filename).exists():shutil.copy2(masks/filename,output/('source_'+filename))
    if (masks/'proposals'/'generator_report.json').exists():
        shutil.copy2(masks/'proposals'/'generator_report.json',output/'proposal_generator_report.json')
    shutil.copy2(__file__,output/Path(__file__).name)
    report=dict(passed=True,scope='Human confirmation, source/operation hashes, full-target raw depth; visual inspection still required',
        source_scene=str(scene),source_mask_output=str(masks),source_report_sha256=source_sha,source_state_sha256=state_sha,
        human_confirmed_frames=72,all_operation_replays_exact=True,raw_sources_modified=False,
        masks_are_pose_ground_truth=False,accepted_for_initial_reconstruction=False,
        visual_inspection_completed=False,frames=rows,
        per_frame_valid_depth_percent=stats([r['valid_depth_percent'] for r in rows]),
        pooled_positive_depth_mm_percentiles=np.percentile(np.concatenate(pooled),[.1,.5,5,50,95,99.5,99.9]).tolist(),
        depth_outside_300_800_pixels=sum(r['depth_outside_300_800_pixels'] for r in rows),
        depth_over_1500_pixels=sum(r['depth_over_1500_pixels'] for r in rows))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','human_confirmed_frames','all_operation_replays_exact',
        'per_frame_valid_depth_percent','pooled_positive_depth_mm_percentiles','depth_outside_300_800_pixels','depth_over_1500_pixels')}))


if __name__=='__main__':main()
