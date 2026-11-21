#!/usr/bin/env python3
"""Local, offline human mask editor. Source RGB/depth are read-only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw

SCHEMA = 'foundationpos_manual_masks_v1'
MAX_PIXELS = 16_000_000
MAX_BODY = 2_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_bytes(path, data):
    temporary = path.with_name(path.name + '.tmp-' + secrets.token_hex(8))
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def e_path(path):
    result = Path(path).expanduser().resolve()
    if os.name == 'nt' and result.drive.upper() != 'E:':
        raise ValueError('Windows inputs and outputs must resolve to E drive')
    return result


def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def png_info(path):
    with Image.open(path) as picture:
        if picture.format != 'PNG':
            raise ValueError('Expected PNG: ' + path.name)
        width, height = picture.size
        if min(width, height) < 1 or max(width, height) > 4096 or width * height > MAX_PIXELS:
            raise ValueError('PNG dimensions exceed editor limits')
        picture.verify()
    return [width, height]


def render_mask(size, operations, proposal_resolver=None):
    if not isinstance(operations, list) or len(operations) > 4000:
        raise ValueError('Invalid operation count')
    image = Image.new('L', tuple(size), 0)
    draw = ImageDraw.Draw(image)
    total = 0
    for operation in operations:
        if isinstance(operation, dict) and operation.get('type') == 'proposal':
            if set(operation) != {'type', 'proposal_id'} or proposal_resolver is None:
                raise ValueError('Expected a retained proposal for this frame')
            image.paste(proposal_resolver(operation['proposal_id']), (0, 0))
            continue
        if not isinstance(operation, dict) or set(operation) - {'type', 'value', 'points', 'radius'}:
            raise ValueError('Invalid operation')
        kind, value, points = operation.get('type'), operation.get('value'), operation.get('points')
        if type(value) is not int or value not in (0, 255) or kind not in ('polygon', 'brush'):
            raise ValueError('Expected foreground 255 or background 0')
        if not isinstance(points, list) or not (1 <= len(points) <= 20000):
            raise ValueError('Invalid points')
        total += len(points)
        if total > 100000 or kind == 'polygon' and len(points) < 3:
            raise ValueError('Too many points, or polygon has fewer than 3 points')
        checked = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('Invalid coordinate')
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
                raise ValueError('Coordinates must be finite numbers')
            x, y = point
            if not (0 <= x <= size[0] - 1 and 0 <= y <= size[1] - 1):
                raise ValueError('Coordinate outside original image')
            checked.append((round(x), round(y)))
        if kind == 'polygon':
            draw.polygon(checked, fill=value)
        else:
            radius = operation.get('radius')
            if type(radius) is not int or not 1 <= radius <= 150:
                raise ValueError('Brush radius must be 1..150 original pixels')
            if len(checked) > 1:
                draw.line(checked, fill=value, width=2 * radius + 1)
            for x, y in checked:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=value)
    return image


def mask_bytes(mask):
    stream = io.BytesIO()
    mask.save(stream, format='PNG')
    return stream.getvalue()


def retained_proposals(output):
    items = []
    for path in (output / 'proposals/index.json', output / 'sam_proposals.json'):
        if path.exists():
            items.extend(json.loads(path.read_text(encoding='utf-8'))['frames'])
    return items


def proposal_path(output, item):
    path = output / item.get('artifact', 'proposals/masks/' + item['frame'])
    if not inside(path.resolve(), output.resolve()):
        raise ValueError('Proposal artifact escapes annotation workspace')
    return path


class Editor:
    def __init__(self, scene, output, sam_runtime=None):
        self.scene, self.output = e_path(scene), e_path(output)
        if inside(self.output, self.scene) or inside(self.scene, self.output):
            raise ValueError('Annotation output must be separate from the source scene')
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.sam = None
        if sam_runtime is not None:
            from manual_mask_sam import PromptedSam
            self.sam = PromptedSam(sam_runtime)
        if self.output.exists() and not (self.output / 'manual_editor.json').is_file() and any(self.output.iterdir()):
            raise ValueError('Existing output is not an editor dataset; choose a new directory')
        self.output.mkdir(parents=True, exist_ok=True)
        self.process_lock = (self.output / '.editor.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.process_lock.seek(0)
                if not self.process_lock.read(1):
                    self.process_lock.write(b'0')
                    self.process_lock.flush()
                self.process_lock.seek(0)
                msvcrt.locking(self.process_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.process_lock.close()
            raise ValueError('Another editor already uses this output') from error
        try:
            manifest = self.output / 'manual_editor.json'
            if manifest.exists():
                self.manifest = json.loads(manifest.read_text(encoding='utf-8'))
                if self.manifest.get('schema') != SCHEMA or self.manifest.get('source_scene') != str(self.scene):
                    raise ValueError('Output belongs to a different tool or source scene')
                self.frames = self.manifest['frames']
                for frame in self.frames:
                    self.sources(frame, verify=True)
            else:
                if any(p.name != '.editor.lock' for p in self.output.iterdir()):
                    raise ValueError('Existing output has no matching manual_editor.json; choose a new directory')
                self.frames = []
                rgb_dir, depth_dir = self.scene / 'rgb', self.scene / 'depth'
                if not rgb_dir.is_dir() or not depth_dir.is_dir():
                    raise ValueError('Source scene needs rgb/ and depth/')
                for rgb in sorted(rgb_dir.glob('*.png')):
                    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\.png', rgb.name):
                        raise ValueError('Unsupported PNG filename')
                    depth = depth_dir / rgb.name
                    if not depth.is_file() or not inside(rgb.resolve(), self.scene) or not inside(depth.resolve(), self.scene):
                        raise ValueError('Missing paired depth or source path escapes scene')
                    size = png_info(rgb)
                    if png_info(depth) != size:
                        raise ValueError('RGB and aligned depth dimensions differ')
                    self.frames.append(dict(frame=rgb.name, size=size, source_rgb_sha256=sha(rgb), source_depth_sha256=sha(depth)))
                if not self.frames or len(self.frames) > 10000:
                    raise ValueError('Expected 1..10000 paired PNGs')
                self.manifest = dict(schema=SCHEMA, created_utc=now(), source_scene=str(self.scene),
                                     source_scene_read_only=True, frames=self.frames, mask_values=[0, 255],
                                     masks_are_pose_ground_truth=False)
                atomic_json(manifest, self.manifest)
            for directory in ('masks', 'revisions'):
                (self.output / directory).mkdir(exist_ok=True)
            self.state_path = self.output / 'state.json'
            self.state = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {}
            if not isinstance(self.state, dict) or set(self.state) - {f['frame'] for f in self.frames}:
                raise ValueError('Invalid saved frame index')
            if any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{8}T[0-9]{12}Z_[0-9a-f]{16}', v) for v in self.state.values()):
                raise ValueError('Invalid saved revision index')
            self.proposals_by_id, self.proposals_by_frame = {}, {}
            proposal_items = retained_proposals(self.output)
            if proposal_items:
                known = {f['frame']:f for f in self.frames}
                for item in proposal_items:
                    original = known.get(item['frame'])
                    if (not original or item['source_rgb_sha256'] != original['source_rgb_sha256']
                            or item['source_depth_sha256'] != original['source_depth_sha256']
                            or not re.fullmatch(r'[0-9a-f]{64}', item['proposal_id'])
                            or item['proposal_id'] != hashlib.sha256((item['frame']+':'+item['mask_sha256']).encode()).hexdigest()):
                        raise ValueError('Proposal/source index differs from this dataset')
                    self.proposals_by_id[item['proposal_id']] = item
                    self.proposals_by_frame[item['frame']] = item
            self.report()
        except Exception:
            self.close()
            raise

    def close(self):
        if getattr(self, 'process_lock', None) and not self.process_lock.closed:
            if os.name == 'nt':
                import msvcrt
                self.process_lock.seek(0)
                msvcrt.locking(self.process_lock.fileno(), msvcrt.LK_UNLCK, 1)
            self.process_lock.close()

    def sources(self, frame, verify=False):
        result = []
        for directory, key in [('rgb', 'source_rgb_sha256'), ('depth', 'source_depth_sha256')]:
            path = (self.scene / directory / frame['frame']).resolve()
            if not inside(path, self.scene) or not path.is_file() or verify and sha(path) != frame[key]:
                raise ValueError('Source changed or missing: ' + frame['frame'])
            result.append(path)
        return result

    def frame(self, index):
        if type(index) is not int or not 0 <= index < len(self.frames):
            raise ValueError('Frame index is outside this dataset')
        return self.frames[index]

    def proposal(self, frame, proposal_id):
        if not isinstance(proposal_id,str) or not re.fullmatch(r'[0-9a-f]{64}',proposal_id):
            raise ValueError('Invalid proposal ID')
        item = self.proposals_by_id.get(proposal_id)
        if not item or item['frame'] != frame['frame']:
            raise ValueError('Proposal belongs to another frame or is not retained')
        path = proposal_path(self.output, item)
        if sha(path) != item['mask_sha256']:
            raise ValueError('Retained proposal SHA changed')
        with Image.open(path) as source:
            if source.mode != 'L' or list(source.size) != frame['size'] or not set(source.tobytes()) <= {0,255}:
                raise ValueError('Proposal must be original-resolution binary L PNG')
            return source.copy()

    def render(self, frame, operations):
        return render_mask(frame['size'],operations,lambda key:self.proposal(frame,key))

    def detail(self, index):
        with self.lock:
            frame = self.frame(index)
            item = self.proposals_by_frame.get(frame['frame'])
            proposal = None
            if item:
                proposal = dict(id=item['proposal_id'], backend=item['backend'], human_confirmed=False,
                    mask_png=base64.b64encode(mask_bytes(self.proposal(frame,item['proposal_id']))).decode('ascii'))
            latest = self.state.get(frame['frame'])
            if latest:
                revision = json.loads((self.output / 'revisions' / latest / 'annotation.json').read_text(encoding='utf-8'))
                content = (self.output / 'revisions' / latest / 'mask.png').read_bytes()
                referenced = {operation['proposal_id'] for operation in revision['operations'] if operation['type'] == 'proposal'}
                historical = [dict(id=key, mask_png=base64.b64encode(mask_bytes(self.proposal(frame,key))).decode('ascii'))
                              for key in sorted(referenced)]
                return dict(frame=frame, revision=latest, operations=revision['operations'], confirmed=True, proposal=proposal,
                            proposals=historical, mask_png=base64.b64encode(content).decode('ascii'), mask_sha256=hashlib.sha256(content).hexdigest())
            return dict(frame=frame, revision=None, operations=[], confirmed=False, proposal=proposal, mask_png=None, mask_sha256=None)

    def segment(self, value):
        if self.sam is None:
            raise ValueError('SAM分割服务未启用')
        if not isinstance(value, dict) or set(value) != {'index', 'rect', 'points', 'labels'}:
            raise ValueError('Expected frame, rectangle and foreground/background points')
        with self.lock:
            frame = dict(self.frame(value['index']))
            self.sources(frame, verify=True)
        item = self.sam.generate(self, frame, value)
        key = hashlib.sha256((item['frame']+':'+item['mask_sha256']).encode()).hexdigest()
        item['proposal_id'] = key
        with self.lock:
            history_path = self.output / 'sam_proposals.json'
            history = json.loads(history_path.read_text()) if history_path.exists() else dict(frames=[])
            history['frames'].append(item)
            atomic_json(history_path, history)
            self.proposals_by_id[key] = item
            self.proposals_by_frame[frame['frame']] = item
            content = mask_bytes(self.proposal(frame, key))
        return dict(proposal_id=key, backend=item['backend'], seconds=item.get('inference_seconds'),
                    mask_png=base64.b64encode(content).decode('ascii'), mask_sha256=hashlib.sha256(content).hexdigest())

    def preview(self, value):
        if not isinstance(value, dict) or set(value) != {'index', 'operations'}:
            raise ValueError('Expected index and operations')
        frame = self.frame(value['index'])
        content = mask_bytes(self.render(frame, value['operations']))
        return dict(mask_png=base64.b64encode(content).decode('ascii'), mask_sha256=hashlib.sha256(content).hexdigest())

    def report(self):
        records = []
        for frame in self.frames:
            latest = self.state.get(frame['frame'])
            row = dict(frame, confirmed=bool(latest), latest_revision=latest)
            if latest:
                revision_mask = self.output / 'revisions' / latest / 'mask.png'
                target = self.output / 'masks' / frame['frame']
                # Rebuild a missing/stale derived export after an interrupted save.
                expected = sha(revision_mask)
                if not target.exists() or sha(target) != expected:
                    atomic_bytes(target, revision_mask.read_bytes())
                row['mask_sha256'] = expected
            records.append(row)
        value = dict(schema=SCHEMA, created_utc=now(), source_scene=str(self.scene), frames=records,
                     total_frames=len(records), confirmed_frames=len(self.state),
                     all_frames_human_confirmed=len(self.state) == len(records),
                     raw_sources_modified=False, mask_values=[0, 255], masks_are_pose_ground_truth=False)
        atomic_json(self.output / 'report.json', value)
        return value

    def save(self, value):
        if not isinstance(value, dict) or set(value) != {'index', 'base_revision', 'operations', 'confirmed', 'preview_sha256'} or value['confirmed'] is not True:
            raise ValueError('Explicit human confirmation and exact save fields are required')
        with self.lock:
            frame = self.frame(value['index'])
            if value['base_revision'] != self.state.get(frame['frame']):
                raise FileExistsError('Another tab saved this frame. Reload it before editing again.')
            self.sources(frame, verify=True)
            mask = self.render(frame, value['operations'])
            if not mask.getbbox():
                raise ValueError('Cannot confirm an empty foreground mask')
            content = mask_bytes(mask)
            if value['preview_sha256'] != hashlib.sha256(content).hexdigest():
                raise ValueError('Preview the current final binary mask before confirmation')
            revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '_' + secrets.token_hex(8)
            revision_dir = self.output / 'revisions' / revision
            revision_dir.mkdir(exist_ok=False)
            try:
                with (revision_dir / 'mask.png').open('xb') as stream:
                    stream.write(content)
                annotation = dict(schema=SCHEMA, revision=revision, previous_revision=value['base_revision'],
                                  frame=frame, confirmed_by='human_browser_action', confirmed_utc=now(),
                                  mask_sha256=sha(revision_dir / 'mask.png'), operations=value['operations'],
                                  confirmed_preview_sha256=value['preview_sha256'])
                used = [self.proposals_by_id[o['proposal_id']] for o in value['operations'] if o['type']=='proposal']
                annotation.update(annotation_method='machine_draft_human_review' if used else 'manual_from_scratch',
                                  proposal_sources=used)
                # Exclusive files in a unique revision; old versions are never changed.
                with (revision_dir / 'annotation.json').open('x', encoding='utf-8') as stream:
                    json.dump(annotation, stream, ensure_ascii=False, indent=2, allow_nan=False)
                    stream.write('\n')
                new_state = dict(self.state)
                new_state[frame['frame']] = revision
                atomic_json(self.state_path, new_state)
                self.state = new_state
                report = self.report()
            except Exception:
                # Retain any partial revision as failure evidence; it is not current.
                raise
            return dict(saved=True, revision=revision, confirmed_frames=report['confirmed_frames'], total_frames=len(self.frames))


HTML = r'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>杯子人工 Mask 标注</title>
<style>body{font:16px system-ui;margin:18px;background:#f3f5f7;color:#17212c}button,select,input{margin:4px;padding:7px}button{cursor:pointer}#viewport{overflow:auto;max-height:72vh;border:1px solid #8592a1;background:#222}#canvas{display:block;touch-action:none}#message{white-space:pre-wrap;color:#88420b}.row{display:flex;align-items:center;flex-wrap:wrap}p{max-width:1100px}</style>
<h2>杯子人工 Mask 标注 · 本机离线</h2><p>包含杯身、把手及可见内壁；把手缝隙、桌面和手属于背景。可见杯子即使深度为 0 也应标前景。源 RGB/深度只读，每次保存保留新版本。</p>
<div class="row"><button onclick="navigate(-1)">上一张</button><span id="position"></span><button onclick="navigate(1)">下一张</button><label>跳到 <input id="jump" type="number" min="1" style="width:70px"></label><button onclick="jumpTo()">跳转</button><span id="progress"></span></div>
<div class="row"><select id="mode"><option value="sambox">SAM矩形框</option><option value="samfg">SAM前景点</option><option value="sambg">SAM背景点</option><option value="fgpoly">前景多边形</option><option value="bgpoly">背景多边形 / 挖孔</option><option value="brush">前景画笔</option><option value="erase">背景橡皮擦</option></select><button onclick="finishPolygon()">完成多边形 (Enter)</button><button onclick="cancelPolygon()">取消未完成多边形 (Esc)</button><button onclick="undo()">撤销 (Ctrl+Z)</button><label>画笔半径 <input id="radius" type="number" min="1" max="150" value="5" style="width:65px"> 原图像素</label><label>显示缩放 <select id="zoom" onchange="resize()"><option value="0.5">50%</option><option value="1" selected>100%</option><option value="1.5">150%</option><option value="2">200%</option><option value="3">300%</option><option value="4">400%</option></select></label><label>叠图透明度 <input id="opacity" type="range" min="0" max="80" value="35" oninput="draw()"></label></div>
<div id="samTools" hidden><button id="samButton" onclick="segmentSam()">按框生成 / 更新 SAM Mask</button><button onclick="clearSamPrompts()">清除SAM框和提示点</button><span>先拖框包含完整杯子和杯把。漏选处加前景点，误选处加背景点，再生成。</span></div>
<div><button onclick="preview()">预览最终二值 Mask</button><label><input id="confirm" type="checkbox">我已查看最终预览并确认本张 Mask</label><button id="save" onclick="save()">保存并确认本张</button><button onclick="reloadFrame()">重新载入本张</button></div>
<div><button id="draft" onclick="loadDraft()" disabled>重新载入机器草稿</button><span id="draftInfo"></span></div>
<p id="message">加载中…</p><div id="viewport"><canvas id="canvas"></canvas></div>
<script>
const TOKEN=__TOKEN__, c=document.getElementById('canvas'),ctx=c.getContext('2d'),mc=document.createElement('canvas'),mx=mc.getContext('2d');
let index=0,total=0,revision=null,operations=[],pending=[],stroke=null,base=new Image(),width=640,height=480,dirty=false,busy=false,frameName='',exactMask=null,previewSha=null,proposal=null;
let samEnabled=false,samRect=null,samDrag=null,samPoints=[],samLabels=[],samPromptsDirty=false;
let proposalImages=new Map();
function message(s){document.getElementById('message').textContent=s}
async function request(path,data){let options=data?{method:'POST',headers:{'Content-Type':'application/json','X-Editor-Token':TOKEN},body:JSON.stringify(data)}:{};let r=await fetch(path,options),j=await r.json();if(!r.ok)throw Error(j.error||r.status);return j}
function changed(){dirty=true;exactMask=null;previewSha=null;document.getElementById('confirm').checked=false;message('有未保存修改；完成轮廓后点击“预览最终二值 Mask”，检查后勾选确认再保存。')}
function resize(){let z=Number(document.getElementById('zoom').value);c.style.width=(width*z)+'px';c.style.height=(height*z)+'px'}
function paint(context,op){if(op.type==='proposal'){let image=proposalImages.get(op.proposal_id);if(!image)throw Error('草稿与当前图片不对应');context.drawImage(image,0,0);return}context.fillStyle=context.strokeStyle=op.value?'white':'black';context.lineJoin=context.lineCap='round';context.beginPath();context.moveTo(...op.points[0]);for(let p of op.points.slice(1))context.lineTo(...p);if(op.type==='polygon'){context.closePath();context.fill()}else{context.lineWidth=2*op.radius+1;context.stroke();for(let p of op.points){context.beginPath();context.arc(...p,op.radius,0,Math.PI*2);context.fill()}}}
function loadDraft(){if(busy||!proposal)return;if((dirty||revision)&&!confirm('用机器草稿替换当前编辑轮廓？已保存的历史版本仍保留。'))return;operations=[{type:'proposal',proposal_id:proposal.id}];pending=[];stroke=null;changed();draw()}
function draw(){if(!base.complete||!base.naturalWidth)return;mx.fillStyle='black';mx.fillRect(0,0,width,height);if(exactMask)mx.drawImage(exactMask,0,0);else{for(let op of operations)paint(mx,op);if(stroke)paint(mx,stroke)}ctx.clearRect(0,0,width,height);ctx.drawImage(base,0,0);let pixels=mx.getImageData(0,0,width,height),alpha=Math.round(Number(document.getElementById('opacity').value)*2.55);for(let i=0;i<pixels.data.length;i+=4){let yes=pixels.data[i]>127;pixels.data[i]=255;pixels.data[i+1]=215;pixels.data[i+2]=0;pixels.data[i+3]=yes?alpha:0}let overlay=document.createElement('canvas');overlay.width=width;overlay.height=height;overlay.getContext('2d').putImageData(pixels,0,0);ctx.drawImage(overlay,0,0);if(pending.length){ctx.strokeStyle='#00ff8a';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(...pending[0]);for(let p of pending.slice(1))ctx.lineTo(...p);ctx.stroke();for(let p of pending){ctx.fillStyle='#00ff8a';ctx.fillRect(p[0]-2,p[1]-2,4,4)}}drawSamPrompts()}
function drawSamPrompts(){
  if(samRect){ctx.strokeStyle='#21c5ff';ctx.lineWidth=2;ctx.strokeRect(...samRect)}
  samPoints.forEach((point,i)=>{ctx.beginPath();ctx.arc(point[0],point[1],4,0,2*Math.PI);ctx.fillStyle=samLabels[i]?'#00ef83':'#ff4561';ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=1;ctx.stroke()});
}
function promptsChanged(){samPromptsDirty=true;previewSha=null;document.getElementById('confirm').checked=false;message('SAM提示已改变，点击“按框生成 / 更新 SAM Mask”。');draw()}
function clearSamPrompts(){if(busy)return;samRect=null;samDrag=null;samPoints=[];samLabels=[];samPromptsDirty=false;draw()}
async function proposalImage(item){
  const image=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src='data:image/png;base64,'+item.mask_png});
  proposalImages.set(item.id,image);
  return image;
}
async function segmentSam(){
  if(busy)return;
  if(!samRect||samRect[2]<12||samRect[3]<12){message('请先拖出包含杯身和杯把的矩形框。');return}
  if(pending.length||stroke){message('请先完成或取消当前手工轮廓。');return}
  busy=true;document.getElementById('samButton').disabled=true;message('SAM正在分割，首次加载稍慢，请等待…');
  try{
    const result=await request('/segment',{index,rect:samRect,points:samPoints,labels:samLabels});
    const image=await proposalImage({id:result.proposal_id,mask_png:result.mask_png});
    proposal={id:result.proposal_id,image};operations=[{type:'proposal',proposal_id:proposal.id}];
    pending=[];stroke=null;samPromptsDirty=false;changed();await exactPreview(result);
    document.getElementById('draft').disabled=false;
    message('SAM已完成。可继续加前景/背景点再生成，或检查黄色Mask后勾选确认并保存。');
  }catch(error){message(error.message)}finally{busy=false;document.getElementById('samButton').disabled=false}
}
async function exactPreview(j){exactMask=await new Promise((ok,fail)=>{let im=new Image();im.onload=()=>ok(im);im.onerror=fail;im.src='data:image/png;base64,'+j.mask_png});previewSha=j.mask_sha256;draw()}
async function preview(){if(busy)return;if(samPromptsDirty){message('请先按新提示生成SAM Mask，或清除SAM提示。');return}if(pending.length||stroke){message('请先完成或取消当前轮廓。');return}busy=true;try{let j=await request('/preview',{index,operations});await exactPreview(j);message('已显示与保存文件完全相同的最终二值轮廓。请检查后勾选确认并保存。')}catch(e){message(e.message)}finally{busy=false}}
function point(e){let b=c.getBoundingClientRect();return [Math.round(Math.max(0,Math.min(width-1,(e.clientX-b.left)*width/b.width))),Math.round(Math.max(0,Math.min(height-1,(e.clientY-b.top)*height/b.height)))]}
c.onpointerdown=e=>{
  if(busy)return;
  const mode=document.getElementById('mode').value,p=point(e);
  if(mode.startsWith('sam')){
    if(!samEnabled){message('当前页面未启用SAM。');return}
    if(mode==='sambox'){samDrag=p;samRect=[p[0],p[1],0,0];c.setPointerCapture(e.pointerId)}
    else{samPoints.push(p);samLabels.push(mode==='samfg'?1:0)}
    promptsChanged();return;
  }
  if(mode.endsWith('poly')){pending.push(p);changed();draw();return}
  if(pending.length){message('请先完成或取消当前多边形。');return}
  const radius=Math.max(1,Math.min(150,Math.round(Number(document.getElementById('radius').value)||5)));
  stroke={type:'brush',value:mode==='brush'?255:0,radius,points:[p]};c.setPointerCapture(e.pointerId);changed();draw();
};
c.onpointermove=e=>{
  if(busy)return;
  const p=point(e);
  if(samDrag){samRect=[Math.min(samDrag[0],p[0]),Math.min(samDrag[1],p[1]),Math.abs(p[0]-samDrag[0]),Math.abs(p[1]-samDrag[1])];draw();return}
  if(stroke){const last=stroke.points.at(-1);if(p[0]!==last[0]||p[1]!==last[1]){stroke.points.push(p);draw()}}
};
c.onpointerup=()=>{samDrag=null;if(stroke){operations.push(stroke);stroke=null;draw()}};c.onpointercancel=c.onpointerup;
function finishPolygon(){if(busy)return;if(pending.length<3){message('多边形至少需要 3 个点。');return}operations.push({type:'polygon',value:document.getElementById('mode').value==='fgpoly'?255:0,points:pending});pending=[];changed();draw()}
function cancelPolygon(){if(busy)return;pending=[];draw()}
function undo(){if(busy)return;if(document.getElementById('mode').value.startsWith('sam')){if(samPoints.length){samPoints.pop();samLabels.pop()}else samRect=null;promptsChanged();return}if(pending.length)pending.pop();else operations.pop();changed();draw()}
document.getElementById('mode').onchange=()=>{if(pending.length){pending=[];message('切换工具已取消未完成多边形；已完成标注仍保留。');draw()}};
window.onkeydown=e=>{if(e.target.matches('input,select'))return;if(e.key==='Enter'){e.preventDefault();if(document.getElementById('mode').value.startsWith('sam'))segmentSam();else finishPolygon()}else if(e.key==='Escape')cancelPolygon();else if(e.ctrlKey&&e.key.toLowerCase()==='z'){e.preventDefault();undo()}};
window.onbeforeunload=e=>{if(dirty||samPromptsDirty){e.preventDefault();e.returnValue='有未保存的标注或SAM提示'}};
async function loadFrame(target){
  busy=true;
  try{
    const j=await request('/frame?index='+target);
    index=target;revision=j.revision;operations=j.operations;pending=[];stroke=null;exactMask=null;previewSha=null;proposal=null;
    proposalImages=new Map();samRect=null;samDrag=null;samPoints=[];samLabels=[];samPromptsDirty=false;
    [width,height]=j.frame.size;frameName=j.frame.frame;c.width=mc.width=width;c.height=mc.height=height;resize();
    await new Promise((ok,fail)=>{base.onload=ok;base.onerror=()=>fail(Error('RGB载入失败'));base.src='/image?index='+index+'&t='+Date.now()});
    for(const item of j.proposals||[])await proposalImage(item);
    if(j.proposal){const image=await proposalImage(j.proposal);proposal={id:j.proposal.id,image};if(!j.confirmed)operations=[{type:'proposal',proposal_id:proposal.id}]}
    document.getElementById('draft').disabled=!proposal;
    document.getElementById('draftInfo').textContent=proposal?'本张有 '+j.proposal.backend+' 草稿，可直接重新框选SAM分割。':'';
    if(j.mask_png)await exactPreview(j);
    dirty=false;document.getElementById('confirm').checked=false;
    document.getElementById('position').textContent=(index+1)+' / '+total+' · '+frameName;
    document.getElementById('jump').value=index+1;
    message(j.confirmed?'此张已有保存版本，重新分割后可检查并保存新版本。':'拖矩形框包含杯身和杯把，点击“按框生成 / 更新 SAM Mask”。');draw();
  }finally{busy=false}
}
async function navigate(delta){if(busy)return;if((dirty||samPromptsDirty)&&!confirm('有未保存标注或SAM提示，放弃本次修改并切换？'))return;try{await loadFrame(Math.max(0,Math.min(total-1,index+delta)))}catch(e){message(e.message)}}
async function jumpTo(){let n=Number(document.getElementById('jump').value);if(!Number.isInteger(n)||n<1||n>total){message('请输入有效张号。');return}await navigate(n-1-index)}
async function reloadFrame(){await navigate(0)}
async function save(){if(busy)return;if(pending.length||stroke){message('请先完成或取消正在绘制的轮廓。');return}if(!previewSha){message('请先点击“预览最终二值 Mask”。');return}if(!document.getElementById('confirm').checked){message('请检查最终预览并勾选本张确认。');return}busy=true;document.getElementById('save').disabled=true;try{let j=await request('/save',{index,base_revision:revision,operations,confirmed:true,preview_sha256:previewSha});revision=j.revision;dirty=false;document.getElementById('progress').textContent='已确认 '+j.confirmed_frames+' / '+j.total_frames;message('已保存独立版本 '+revision+'；可继续下一张。')}catch(e){message(e.message)}finally{busy=false;document.getElementById('save').disabled=false}}
(async()=>{try{let s=await request('/status');total=s.total_frames;samEnabled=!!s.sam_enabled;document.getElementById('samTools').hidden=!samEnabled;if(!samEnabled)document.getElementById('mode').value='fgpoly';document.getElementById('progress').textContent='已确认 '+s.confirmed_frames+' / '+total;await loadFrame(s.first_unconfirmed)}catch(e){message(e.message)}})();
</script></html>'''


def make_server(editor, port=8767):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, data, mime='application/json; charset=utf-8'):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            for name, value in [('Content-Type', mime), ('Content-Length', str(len(data))), ('Cache-Control', 'no-store'),
                                ('X-Content-Type-Options', 'nosniff'), ('Cross-Origin-Resource-Policy', 'same-origin')]:
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def safe_host(self):
            expected = '127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Host') != expected:
                raise ValueError('Invalid local Host')
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                raise ValueError('Cross-origin requests are forbidden')

        def do_GET(self):
            try:
                self.safe_host()
                parsed = urlsplit(self.path)
                if parsed.path == '/' and not parsed.query:
                    self.send(200, HTML.replace('__TOKEN__', json.dumps(editor.token)).encode('utf-8'), 'text/html; charset=utf-8')
                elif parsed.path == '/status' and not parsed.query:
                    with editor.lock:
                        first = next((i for i, f in enumerate(editor.frames) if f['frame'] not in editor.state), 0)
                        self.send(200, dict(total_frames=len(editor.frames), confirmed_frames=len(editor.state),
                                            first_unconfirmed=first, sam_enabled=editor.sam is not None))
                elif parsed.path in ('/frame', '/image'):
                    query = parse_qs(parsed.query, strict_parsing=True)
                    if set(query) - {'index', 't'} or len(query.get('index', [])) != 1 or not query['index'][0].isdigit():
                        raise ValueError('Expected a dataset frame index')
                    index = int(query['index'][0])
                    if parsed.path == '/frame':
                        self.send(200, editor.detail(index))
                    else:
                        frame = editor.frame(index)
                        source = editor.sources(frame)[0]
                        self.send(200, source.read_bytes(), 'image/png')
                else:
                    self.send(404, dict(error='Unknown endpoint'))
            except Exception as error:
                self.send(400, dict(error=str(error)))

        def do_POST(self):
            try:
                self.safe_host()
                if self.path not in ('/save', '/preview', '/segment'):
                    self.send(404, dict(error='Unknown endpoint'))
                    return
                if self.headers.get('X-Editor-Token') != editor.token:
                    raise ValueError('Invalid editor session token')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Expected bounded JSON body')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    raise ValueError('Payload exceeds 2 MB or is empty')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Incomplete body')
                value = json.loads(data)
                handlers = {'/save': editor.save, '/preview': editor.preview, '/segment': editor.segment}
                self.send(200, handlers[self.path](value))
            except FileExistsError as error:
                self.send(409, dict(error=str(error)))
            except Exception as error:
                self.send(400, dict(error=str(error)))

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--sam-runtime', type=Path, help='Local SAM2 runtime for box/point prompting')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be 1024..65535')
    editor = Editor(args.scene, args.output, sam_runtime=args.sam_runtime)
    server = None
    try:
        server = make_server(editor, args.port)
        print(json.dumps(dict(ready=True, url='http://127.0.0.1:' + str(args.port), scene=str(editor.scene),
                              output=str(editor.output), total_frames=len(editor.frames)), ensure_ascii=False), flush=True)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print(json.dumps(dict(stopped=True, confirmed_frames=len(editor.state), total_frames=len(editor.frames))), flush=True)
    finally:
        if server:
            server.server_close()
        editor.close()


if __name__ == '__main__':
    main()
