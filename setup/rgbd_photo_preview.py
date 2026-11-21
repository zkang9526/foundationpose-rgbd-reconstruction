"""Local browser preview and manual controls for the existing RGB-D saver."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np


PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>D435i RGB-D手动采集</title>
<style>body{font:17px system-ui;margin:20px;background:#17202b;color:#edf2f8;max-width:1400px}
h1{font-size:24px}p{line-height:1.6}.views{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
img{width:100%;background:#000}button{font:inherit;padding:12px 20px;margin:8px 8px 8px 0}
#progress{font-size:24px;font-weight:bold}#path{overflow-wrap:anywhere}#notice{color:#ffd98c}</style>
<h1>D435i 杯子 RGB-D 采集</h1><p id="progress">正在连接相机</p>
<div class="views"><div><p>RGB 实时画面</p><img id="rgb" alt="等待RGB"></div>
<div><p>对齐深度预览 · 黑色表示无有效深度</p><img id="depth" alt="等待深度"></div></div>
<p>固定相机，保持本轮杯子摆放，杯身和杯把完整入镜并留边。每次转动后停稳、手退出，再保存。保存期间保持静止。</p>
<button id="save" disabled onclick="act('capture')">保存一张 RGB-D</button>
<button id="stop" onclick="act('stop')">结束并保留已采数据</button>
<p id="notice"></p><p id="details"></p><p id="path"></p>
<p>深度颜色显示范围为0.2–1.2米，原始毫米深度另存。整幅有效率仅作预览参考，杯子区域需要单独检查。</p>
<script>
let busy=false;
async function act(name){if(busy)return;busy=true;document.querySelector('#save').disabled=true;
try{const response=await fetch('/'+name,{method:'POST',headers:{'X-Photo-Control':'1'}});
document.querySelector('#notice').textContent=await response.text();}catch(error){document.querySelector('#notice').textContent='连接中断，请检查采集进程。';}
finally{busy=false;}}
async function tick(){try{const response=await fetch('/status');const s=await response.json();
const count=s.saved_frames;document.querySelector('#progress').textContent=`已保存 ${count} / ${s.views} 张 · ${s.message}`;
document.querySelector('#save').disabled=busy||!s.ready||s.busy||!s.running||s.frame_age_seconds===null||s.frame_age_seconds>1.5;
document.querySelector('#stop').disabled=!s.running;
document.querySelector('#path').textContent='保存目录 '+s.output;
document.querySelector('#details').textContent=`下一张计划角度 ${s.next_planned_angle_degrees.toFixed(1)}°（非实测）；整幅原始有效深度 ${(100*s.whole_image_valid_fraction).toFixed(1)}%`;
document.querySelector('#rgb').src='/rgb.jpg?t='+Date.now();document.querySelector('#depth').src='/depth.jpg?t='+Date.now();
}catch(error){document.querySelector('#save').disabled=true;document.querySelector('#notice').textContent='预览连接已结束或尚未就绪，请查看采集记录。';}}
setInterval(tick,500);tick();
</script></html>'''


class PhotoPreview:
    def __init__(self, output, views, angle_step, requests, port):
        self.requests = requests
        self.lock = threading.Lock()
        self.rgb_jpeg = self.depth_jpeg = b''
        self.last_frame_time = None
        self.last_publish = 0.
        self.state = dict(output=str(output), views=views, saved_frames=0, ready=False,
            busy=False, running=True, message='相机预热中', next_planned_angle_degrees=0.,
            whole_image_valid_fraction=0.)
        self.angle_step = angle_step
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split('?', 1)[0]
                with owner.lock:
                    if path == '/':
                        data, kind = PAGE.encode('utf-8'), 'text/html; charset=utf-8'
                    elif path == '/status':
                        value = dict(owner.state, frame_age_seconds=None if owner.last_frame_time is None
                                     else time.monotonic() - owner.last_frame_time)
                        data, kind = json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8'
                    elif path in ('/rgb.jpg', '/depth.jpg'):
                        data = owner.rgb_jpeg if path == '/rgb.jpg' else owner.depth_jpeg
                        kind = 'image/jpeg'
                    else:
                        self.send_error(404)
                        return
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                if self.headers.get('X-Photo-Control') != '1':
                    self.send_error(403)
                    return
                with owner.lock:
                    if self.path not in ('/capture', '/stop'):
                        self.send_error(404)
                        return
                    if not owner.state['running']:
                        self.send_error(409, 'Capture already stopped')
                        return
                    if self.path == '/capture':
                        if (not owner.state['ready'] or owner.state['busy'] or owner.last_frame_time is None
                                or time.monotonic() - owner.last_frame_time > 1.5):
                            self.send_error(409, 'Wait for fresh preview and previous save')
                            return
                        owner.state.update(busy=True, message='正在等待停稳后的新帧')
                        action = 'enter'
                        message = '保存请求已收到，请保持相机和杯子静止。'
                    else:
                        owner.state.update(ready=False, message='正在结束采集')
                        action = 'quit'
                        message = '正在保留数据并释放相机。'
                    owner.requests.put((action, time.monotonic()))
                data = message.encode('utf-8')
                self.send_response(202)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def set_state(self, **values):
        with self.lock:
            self.state.update(values)
            self.state['next_planned_angle_degrees'] = self.state['saved_frames'] * self.angle_step

    def publish(self, rgb_frame, depth_frame, scale):
        current_time = time.monotonic()
        if current_time - self.last_publish < .2:
            return
        rgb = np.asanyarray(rgb_frame.get_data())
        depth = np.asanyarray(depth_frame.get_data())
        valid = depth > 0
        levels = np.clip((depth.astype(np.float32) * scale - .2) / 1.0 * 255, 0, 255).astype(np.uint8)
        color_depth = cv2.applyColorMap(levels, cv2.COLORMAP_TURBO)
        color_depth[~valid] = 0
        ok_rgb, jpg_rgb = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        ok_depth, jpg_depth = cv2.imencode('.jpg', color_depth)
        if not ok_rgb or not ok_depth:
            raise RuntimeError('Could not encode live preview')
        with self.lock:
            self.rgb_jpeg, self.depth_jpeg = jpg_rgb.tobytes(), jpg_depth.tobytes()
            self.last_frame_time = current_time
            self.state['whole_image_valid_fraction'] = float(valid.mean())
        self.last_publish = current_time

    def close(self, report, grace_seconds=3.):
        self.set_state(running=False, ready=False, busy=False, saved_frames=report['saved_frames'],
                       message='采集完成' if report['passed'] else '采集已停止，记录已保留')
        time.sleep(grace_seconds)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
