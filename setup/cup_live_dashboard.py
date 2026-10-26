#!/usr/bin/env python3
"""Local-only live viewer and explicit same-frame ROI/mask initialization."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time


HTML = r'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>杯子实时位姿</title>
<style>body{font:16px system-ui;margin:24px;background:#f4f6f8;color:#182630}button{padding:9px 15px;margin:5px;border:1px solid #bcc9d1;border-radius:6px;background:white;cursor:pointer}canvas,img{width:640px;max-width:100%;background:#ddd;border-radius:5px}section{display:flex;gap:20px;flex-wrap:wrap}pre{white-space:pre-wrap}#msg{color:#a04014}h2{font-size:18px}</style>
<h1>杯子实时 6D 位姿试跑</h1><p>首次停稳并确认Mask。目标丢失后自动全图搜索原目标，返回时请短暂停稳；候选不明确时继续等待。当前网格有缺陷，输出精度尚未验证。</p>
<div><button onclick="freeze()">1 冻结画面</button><button id="maskButton" onclick="mask()">2 生成 Mask</button><button id="initButton" disabled onclick="act('/initialize',{candidate_id:maskId})">3 确认 Mask 并初始化</button><button onclick="act('/pause')">暂停跟踪</button><button onclick="act('/stop')">停止并保存记录</button></div>
<div id="samControls" hidden><label>编辑方式：<select id="mode"><option value="box">拖框</option><option value="1">前景点（杯身/杯把）</option><option value="0">背景点（桌面/把手空隙）</option></select></label><button onclick="undoPoint()">撤销最后一点</button><button onclick="clearPoints()">清空提示点</button><span>添加或删除点后，点“生成 SAM Mask”更新结果。</span></div>
<p id="connection" role="status">正在连接相机服务…</p><p id="msg">等待相机画面。冻结后拖框圈住完整杯身和杯把，留少量背景；检查 Mask 后初始化。</p>
<section><div><h2>相机 / 冻结帧 / 黄色 Mask</h2><canvas id="c" width="640" height="480"></canvas></div><div><h2>推理所用帧的网格轮廓与轴</h2><img id="o" width="640" height="480"></div></section>
<p id="imageStatus"></p><p id="protocol"></p><pre id="s">连接中</pre><pre id="ref">ArUco参考：等待有效的同帧参考；相对运动误差要求杯子和码固定</pre><pre id="pose"></pre>
<script>
const c=document.getElementById('c'), ctx=c.getContext('2d');let frozen=false,drag=false,start=null,rect=null,busy=false,points=[],labels=[],maskId=null,maskBusy=false,isSam=false;
let sessionOutput=null,imageSequence=0,previewPending=false,overlayPending=false,overlayTimer=null,controlRevision=0;
function dirty(){maskId=null;document.getElementById('initButton').disabled=true}
function syncSession(j){const a=j.aruco_settings||{};document.getElementById('protocol').textContent=a.enabled?(a.fixed_scene?'误差评测：杯子和码固定，只移动相机。':'当前只跟踪杯子并检测码；杯子与码可相对移动，不计算固定场景误差。'):'';if(j.state==='waiting_for_roi')j.message='模型与图像已就绪；请冻结画面、框选杯子和杯把、生成Mask并确认初始化';if(sessionOutput===j.output)return;sessionOutput=j.output;imageSequence++;previewPending=false;overlayPending=false;clearTimeout(overlayTimer);frozen=false;drag=false;start=null;rect=null;points=[];labels=[];dirty();document.getElementById('mode').value='box';document.getElementById('msg').textContent=j.state==='waiting_for_roi'?'模型与图像已就绪；请冻结画面、框选杯子和杯把、生成Mask并确认初始化':(j.message||'新会话已连接')}
function undoPoint(){if(maskBusy)return;points.pop();labels.pop();dirty();draw()}
function clearPoints(){if(maskBusy)return;points=[];labels=[];dirty();draw()}
function point(e){const b=c.getBoundingClientRect();return [Math.max(0,Math.min(639,(e.clientX-b.left)*640/b.width)),Math.max(0,Math.min(479,(e.clientY-b.top)*480/b.height))]}
c.onpointerdown=e=>{if(!frozen||maskBusy)return;let mode=document.getElementById('mode').value;if(isSam&&mode!=='box'){if(!rect||points.length>=64)return;points.push(point(e).map(Math.round));labels.push(Number(mode));dirty();draw();return}start=point(e);points=[];labels=[];dirty();drag=true;c.setPointerCapture(e.pointerId)};
c.onpointermove=e=>{if(!drag)return;let p=point(e);rect=[Math.round(Math.min(start[0],p[0])),Math.round(Math.min(start[1],p[1])),Math.round(Math.abs(start[0]-p[0])),Math.round(Math.abs(start[1]-p[1]))];draw()};
c.onpointerup=()=>{drag=false};
let base=new Image();function draw(){ctx.clearRect(0,0,640,480);if(base.complete&&base.naturalWidth)ctx.drawImage(base,0,0,640,480);if(rect){ctx.strokeStyle='#ffed00';ctx.lineWidth=2;ctx.strokeRect(...rect)}points.forEach((p,i)=>{ctx.beginPath();ctx.arc(p[0],p[1],5,0,Math.PI*2);ctx.fillStyle=labels[i]?'#00ff60':'#ff3040';ctx.fill();ctx.strokeStyle='#fff';ctx.stroke()})}
function clearSelection(){frozen=false;drag=false;rect=null;points=[];labels=[];dirty()}
async function load(force=false){if(previewPending&&!force)return false;const sequence=++imageSequence,next=new Image();previewPending=true;return new Promise((ok,fail)=>{let done=false;const finish=(error)=>{if(done)return;done=true;clearTimeout(timer);if(sequence===imageSequence)previewPending=false;if(error){fail(error);return}if(sequence===imageSequence){base=next;draw();document.getElementById('imageStatus').textContent=''}ok(true)};const timer=setTimeout(()=>finish(Error('相机预览加载超时，将自动重试')),5000);next.onload=()=>finish();next.onerror=()=>finish(Error('相机预览暂不可用，将自动重试'));next.src='/preview.jpg?t='+Date.now()})}
function loadOverlay(){if(overlayPending)return;overlayPending=true;const target=document.getElementById('o');const finish=()=>{overlayPending=false;clearTimeout(overlayTimer)};target.onload=finish;target.onerror=()=>{finish();document.getElementById('imageStatus').textContent='位姿叠图加载失败，将自动重试'};overlayTimer=setTimeout(finish,5000);target.src='/overlay.jpg?t='+Date.now()}
function imageError(error){document.getElementById('imageStatus').textContent=error.message}
async function act(path,data={}){controlRevision++;try{let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let j=await r.json();if(!r.ok)throw Error(j.error);document.getElementById('msg').textContent=j.message||'已执行';if(path==='/initialize'){clearSelection();imageSequence++;previewPending=false}return j}catch(e){document.getElementById('msg').textContent=e.message;return null}finally{controlRevision++}}
async function freeze(){if(maskBusy)return;if(await act('/freeze')){frozen=true;rect=null;points=[];labels=[];dirty();document.getElementById('mode').value='box';await load(true).catch(imageError)}}
async function mask(){if(maskBusy)return;if(!rect){document.getElementById('msg').textContent='请先冻结并拖框，圈住完整杯子和杯把';return}maskBusy=true;dirty();document.getElementById('maskButton').disabled=true;document.getElementById('msg').textContent='正在生成 Mask；保持相机和杯子停稳…';try{let j=await act('/mask',{rect,points,labels});if(j){maskId=j.candidate_id;document.getElementById('initButton').disabled=false;await load(true).catch(imageError)}}finally{maskBusy=false;document.getElementById('maskButton').disabled=false}}
async function refresh(){if(busy)return;busy=true;const revision=controlRevision,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),4000);try{let r=await fetch('/status',{signal:controller.signal});if(r.ok===false)throw Error('状态请求失败');let j=await r.json();if(revision!==controlRevision)return;syncSession(j);if(['initializing','verifying_reacquisition','tracking_estimate_unverified','needs_reinitialization','paused'].includes(j.state))clearSelection();document.getElementById('connection').textContent='已连接相机服务';if(!maskBusy&&!drag)document.getElementById('msg').textContent=j.message||'';isSam=(j.segmentation_backend||'').startsWith('SAM');document.getElementById('samControls').hidden=!isSam;document.getElementById('maskButton').textContent=isSam?'2 生成 '+j.segmentation_backend+' Mask':'2 生成 GrabCut Mask';document.getElementById('s').textContent='分割: '+(j.segmentation_backend||'GrabCut')+' | 状态: '+j.state+' | 成功帧: '+j.completed+' | 失败帧: '+j.failed+'\n当前连续跟踪 FPS: '+(j.processing_fps||0).toFixed(2)+' | 结果距今秒: '+(j.result_age_seconds||0).toFixed(2)+'\n记录: '+j.output+'\n'+(j.message||'');document.getElementById('pose').textContent=j.pose?'原始 OBJ → 相机（米），估计矩阵:\n'+j.pose.map(r=>r.map(v=>v.toFixed(5)).join('  ')).join('\n'):'';document.getElementById('o').hidden=!j.pose;if(!frozen&&!drag)load().catch(imageError);if(j.pose)loadOverlay()}catch(e){document.getElementById('connection').textContent='连接已中断，正在重试：'+e.message;document.getElementById('o').hidden=true}finally{clearTimeout(timer);busy=false}}
async function referenceStatus(){try{let j=await (await fetch('/status')).json(),v=j.reference_evaluation||{},e=j.pose?v.anchored_object_errors:null,a=j.aruco_settings||{},d=j.aruco_status||{};let config=a.enabled?'ArUco '+a.dictionary+' / ID '+a.marker_id+' / 黑边 '+(a.measured_black_side_m*1000).toFixed(1)+' mm\n':'';let detection=d.source_frame?'参考帧 '+d.source_frame+' | '+(d.reference_accepted?'参考有效':(d.reason||'参考无效'))+(d.min_edge_pixels?' | 短边 '+d.min_edge_pixels.toFixed(1)+' px':'')+'\n':'';document.getElementById('ref').textContent=config+detection+(e?'首帧对齐后的杯子漂移：'+e.translation_error_mm.toFixed(2)+' mm / '+e.rotation_error_deg.toFixed(2)+'° | 参考首帧 '+v.anchor_frame+'\n首帧偏差已消除；绝对杯子位姿精度需要独立标定码到杯子的变换':'ArUco参考：'+(v.reason||'尚无有效参考')+' | 深度一致性拒绝帧：'+(j.quality_rejected||0))}catch(e){}}
setInterval(refresh,100);setInterval(referenceStatus,500);refresh();
</script></html>'''


def make_server(bind, port, state, control, stop):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, data, mime):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            path = self.path.split('?')[0]
            with state['lock']:
                if path == '/':
                    data, mime = HTML.encode('utf-8'), 'text/html; charset=utf-8'
                elif path == '/status':
                    value = {k: v for k, v in state.items() if k in
                             ('state', 'completed', 'failed', 'output', 'message', 'pose', 'processing_fps', 'quality_rejected', 'reference_evaluation', 'aruco_settings', 'aruco_status')}
                    value['segmentation_backend'] = state.get('segmentation_backend', 'GrabCut（旧入口）')
                    value['mask_busy'] = state.get('mask_busy', False)
                    value['result_age_seconds'] = time.monotonic() - state['result_time'] if state.get('result_time') else None
                    data, mime = json.dumps(value, allow_nan=False).encode(), 'application/json'
                elif path in ('/preview.jpg', '/overlay.jpg'):
                    key = 'preview_jpeg' if path == '/preview.jpg' else 'overlay_jpeg'
                    data, mime = state.get(key, b''), 'image/jpeg'
                else:
                    self.send(404, b'Not found', 'text/plain')
                    return
            self.send(200 if data else 503, data, mime)

        def do_POST(self):
            try:
                if self.path not in ('/freeze', '/mask', '/initialize', '/pause', '/stop'):
                    raise ValueError('Unknown control')
                # Only the served page can issue state-changing browser requests.
                origin = self.headers.get('Origin')
                if origin is not None and origin != 'http://' + self.headers.get('Host', ''):
                    raise ValueError('Origin differs from local viewer')
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 4096:
                    raise ValueError('Invalid request length')
                value = json.loads(self.rfile.read(length) or b'{}')
                message = control(self.path, value)
                with state['lock']:
                    candidate_id = state.get('candidate_id')
                self.send(200, json.dumps(dict(message=message, candidate_id=candidate_id), ensure_ascii=False).encode('utf-8'), 'application/json')
            except Exception as error:
                self.send(400, json.dumps(dict(error=str(error)), ensure_ascii=False).encode('utf-8'), 'application/json')

    server = ThreadingHTTPServer((bind, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
