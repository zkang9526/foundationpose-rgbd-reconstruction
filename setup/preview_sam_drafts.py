"""Source-verified contact sheets for unconfirmed SAM proposals."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--scene', type=Path, required=True)
p.add_argument('--drafts', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
report = json.loads((args.drafts/'report.json').read_text())
if not report['passed'] or not report['draft_only']:
    raise ValueError('Expected completed unconfirmed draft batch')
entries = []
for frame in report['frames']:
    rgb_path, mask_path = args.scene/'rgb'/frame['frame'], args.drafts/frame['mask_file']
    if (hashlib.sha256(rgb_path.read_bytes()).hexdigest() != frame['source_rgb_sha256']
            or hashlib.sha256(mask_path.read_bytes()).hexdigest() != frame['mask_sha256']):
        raise ValueError('Source or proposal SHA changed')
    rgb, mask = cv2.imread(str(rgb_path)), cv2.imread(str(mask_path),cv2.IMREAD_UNCHANGED)
    overlay = rgb.copy()
    overlay[mask>0] = (overlay[mask>0]*.7 + np.array([0,215,255])*.3).astype(np.uint8)
    contours,_ = cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay,contours,-1,(255,0,255),1)
    crop = Image.fromarray(cv2.cvtColor(overlay,cv2.COLOR_BGR2RGB)).crop((225,250,455,450)).resize((322,280))
    entries.append((frame['frame'],crop))
for start in range(0,len(entries),8):
    page=entries[start:start+8]
    sheet=Image.new('RGB',(1288,((len(page)+3)//4)*306),(30,30,30))
    draw=ImageDraw.Draw(sheet)
    for i,(name,picture) in enumerate(page):
        x,y=i%4*322,i//4*306
        draw.text((x+5,y+5),name+' SAM DRAFT',fill='white')
        sheet.paste(picture,(x,y+26))
    sheet.save(args.output/('drafts_%02d.png'%(start//8)))
(args.output/'review_scope.json').write_text(json.dumps(dict(frames=len(entries),human_confirmed=False,
    assistant_visual_inspection_pending=True,source_report_sha256=hashlib.sha256((args.drafts/'report.json').read_bytes()).hexdigest()),indent=2)+'\n')
print(json.dumps(dict(frames=len(entries),contact_pages=(len(entries)+7)//8,output=str(args.output))))
