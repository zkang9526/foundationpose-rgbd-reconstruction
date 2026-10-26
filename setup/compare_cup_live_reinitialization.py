#!/usr/bin/env python3
"""Compare immutable original live estimates with a separately initialized replay."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('original','replay','mesh','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        p.error('Output must be new')
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    source=json.loads((args.original/'session.json').read_text())
    trial=json.loads((args.replay/'diagnostic_report.json').read_text())
    assert trial['passed'] and trial['completed']==120
    assert sha(args.original/'session.json')==trial['source_session_sha256']
    assert sha(args.mesh)==source['mesh_sha256']==trial['source_model_sha256']
    for stem in trial['frame_ids']:
        old=args.original/'frames'/stem
        new=args.replay/'frames'/stem
        requestpath=args.replay/'requests'/(stem+'.json')
        request=json.loads(requestpath.read_text())
        result=json.loads((args.replay/'responses'/(stem+'.json')).read_text())
        assert result['passed'] and result['request_sha256']==sha(requestpath)
        for name,digest in request['input_sha256'].items():
            assert sha(new/name)==digest
            if name!='mask.png':
                assert sha(old/name)==digest
        assert sha(new/'pose_camera_from_mesh.txt')==result['pose_sha256']
        assert sha(new/'overlay.png')==result['overlay_sha256']
    vertices,faces=[],[]
    for line in args.mesh.read_text().splitlines():
        values=line.split()
        if values and values[0]=='v':vertices.append([float(v) for v in values[1:4]])
        elif values and values[0]=='f':faces.append([int(v.split('/')[0])-1 for v in values[1:4]])
    vertices,faces=np.array(vertices),np.array(faces)
    K=np.array(source['K'])
    target=cv2.imread(str(args.replay/'frames/000001/mask.png'),0)>0
    overlaps={}
    for label,folder in [('original_live',args.original),('fresh_initialization_diagnostic',args.replay)]:
        pose=np.loadtxt(folder/'frames/000001/pose_camera_from_mesh.txt')
        points=vertices@pose[:3,:3].T+pose[:3,3]
        xy=points@K.T
        xy=np.rint(np.clip(xy[:,:2]/xy[:,2:3],-1e6,1e6)).astype(np.int32)
        rendered=np.zeros(target.shape,np.uint8)
        for triangle in xy[faces]:cv2.fillConvexPoly(rendered,triangle,255)
        predicted=rendered>0
        overlaps[label]=float(np.sum(predicted&target)/np.sum(predicted|target))
    args.output.mkdir(parents=True,exist_ok=False)
    samples=['000001','000020','000060','000080','000120']
    sheet=Image.new('RGB',(320*len(samples),825),'white')
    draw=ImageDraw.Draw(sheet)
    draw.text((8,4),'Same original RGB-D; same metric mesh/official weights. Fresh frame + inspected diagnostic mask. NO pose GT.',fill='black')
    for i,stem in enumerate(samples):
        for row,path,label in [(0,args.original/'frames'/stem/'rgb.png','Original input'),
                               (1,args.original/'frames'/stem/'overlay.png','Original live: stale initialization'),
                               (2,args.replay/'frames'/stem/'overlay.png','Fresh registration diagnostic')]:
            y=25+row*265
            draw.text((i*320+4,y),stem+' '+label,fill='black')
            sheet.paste(Image.open(path).convert('RGB').resize((320,240)),(i*320,y+20))
    sheet.save(args.output/'original_vs_fresh_120.png')
    report=dict(passed=True,scope='120 identical-input replay comparison and transfer hash verification',
                model_sha256=sha(args.mesh),original_session_sha256=sha(args.original/'session.json'),
                replay_report_sha256=sha(args.replay/'diagnostic_report.json'),
                verified_frames=len(trial['frame_ids']),first_tracking_frame_diagnostic_mask_iou=overlaps,
                mask_iou_is_not_pose_accuracy=True,pose_accuracy_validated=False,
                changes=['Initialization on actual frame000001 instead of frozen frame000000',
                         'Separately derived and RGB-inspected same-frame diagnostic mask; handle-opening uncertainty remains'],
                original_outputs_modified=False,sampled_visual_frames=samples,
                comparison_sha256=sha(args.output/'original_vs_fresh_120.png'))
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
