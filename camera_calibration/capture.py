"""Isolated RGB/depth/IR checkerboard capture with a browser and immutable trials.

Run through run_windows.ps1 or run_ubuntu.sh. No device calibration is written.
"""
import argparse
from collections import deque
import html
import json
import os
from pathlib import Path
import shutil
import signal
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import pyrealsense2 as rs

from common import (board_points, camera_model, depth_panel, detect, extrinsic, intrinsic,
                    now, orient_corners, pose, project, sha, snapshot_sources, write_json)
from boundary import check_boundary


PAGE = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>D435i 棋盘格验证</title>
<style>body{font:17px system-ui;background:#151c25;color:#e9edf3;margin:24px;max-width:1500px}
button{font:inherit;padding:12px;margin:8px 8px 8px 0}img{width:100%;border:1px solid #536070}
pre{white-space:pre-wrap;background:#26303e;padding:16px}p{line-height:1.7}</style>
<h1>D435i 棋盘格验证 · 独立数据</h1><p>__BOARD_SPEC__<br>
左：RGB；中：SDK 对齐到 RGB 的深度；右：RGB 上的绿色深度跳变（20 mm，仅显示阈值）。</p>
<img id="preview" alt="等待相机帧"><p>下方：左红外 IR1、右红外 IR2；棋盘应在 RGB 和两幅红外图中完整入镜。</p>
<img id="irpreview" alt="等待红外帧"><p>相机固定在支架上，棋盘贴在平整硬板上。摆好后点击保存，倒计时期间保持静止，等接收数增加再移动。
建议 25–35 张：中央和四周、远近、左右/上下倾斜。避免只平移或只正对相机。移动时不拍。</p>
<button id="capture" onclick="act('capture')">倒计时 __CAPTURE_DELAY__ 秒后保存一组</button>
<button onclick="annotate()">可选：标注上次照片的板外轮廓</button>
<button onclick="act('stop')">完成采集并停止</button><pre id="state"></pre>
<div id="annotation" hidden><p>按顺时针依次点击实体板的4个最外角。不要点棋盘格内角点或打印图案边缘。
板与背景至少隔开5 cm。黄线是人工边缘；深度空洞和遮挡会单独记录。</p>
<canvas id="canvas" width="640" height="480" style="max-width:100%;background:#222"></canvas><br>
<button onclick="drawReset()">重选4点</button><button onclick="sendBoundary()">保存边缘对齐检查</button></div>
<p>拒绝的照片与原因同样保留。黑白格之间没有深度台阶；检查外轮廓时，让板与背景有明显距离差。
本页只采集，精度结论由独立分析生成。板→相机位姿不代表相机→机器人/世界外参。</p>
<script>let trial=0,vertices=[],pic=new Image(),ctx=document.getElementById('canvas').getContext('2d');
function drawReset(){vertices=[];ctx.drawImage(pic,0,0)}
async function annotate(){let s=await(await fetch('/status')).json();if(!s.last_trial||s.busy)return;
trial=s.last_trial.index;pic.onload=()=>{document.getElementById('annotation').hidden=false;drawReset()};
pic.src='/trial/'+String(trial).padStart(4,'0')+'/rgb.png'}
document.getElementById('canvas').onclick=e=>{if(vertices.length>=4)return;let b=e.target.getBoundingClientRect();
vertices.push([(e.clientX-b.left)*640/b.width,(e.clientY-b.top)*480/b.height]);ctx.strokeStyle='yellow';
ctx.lineWidth=2;ctx.beginPath();vertices.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));
if(vertices.length===4)ctx.closePath();ctx.stroke()};
async function sendBoundary(){if(vertices.length!==4)return;let r=await fetch('/boundary',{method:'POST',
headers:{'X-Calibration-Control':'1','Content-Type':'application/json'},body:JSON.stringify({trial,vertices})});
document.getElementById('state').textContent=await r.text();document.getElementById('annotation').hidden=true}
async function act(a){try{let r=await fetch('/'+a,{method:'POST',headers:{'X-Calibration-Control':'1'}});
document.getElementById('state').textContent=await r.text()}catch(e){}}
async function tick(){try{let r=await fetch('/status');let s=await r.json();
document.getElementById('state').textContent=JSON.stringify(s,null,2);document.getElementById('capture').disabled=s.busy;
document.getElementById('preview').src='/preview.jpg?t='+Date.now();
document.getElementById('irpreview').src='/ir_preview.jpg?t='+Date.now()}catch(e){} }setInterval(tick,800);tick();</script></html>'''


def render_page(board, delay):
    spec = '%d×%d 方格，%d×%d 内角点，格边长 %g mm。' % (
        board['cols'] + 1, board['rows'] + 1, board['cols'], board['rows'], board['square_mm'])
    return PAGE.replace('__BOARD_SPEC__', html.escape(spec)).replace('__CAPTURE_DELAY__', '%g' % delay)


def image_write(path, array):
    if not cv2.imwrite(str(path), array):
        raise OSError('Could not write ' + str(path))


def frame_info(f):
    return dict(number=f.get_frame_number(), sdk_timestamp_ms=f.get_timestamp(),
                timestamp_domain=str(f.get_frame_timestamp_domain()))


def save_trial(output, frame, earlier, meta, board, allow_unchecked=False):
    output.mkdir(parents=True, exist_ok=False)
    result = dict(created_utc=now(), accepted=False, metadata=frame['info'], reasons=[], corners={},
                  raw_color_encoding='RGB uint8 NPY; RGB PNG decoded by any standard image reader',
                  depth_encoding='uint16 native units; multiply by session depth_scale_m')
    try:
        for key in ('rgb', 'depth_native', 'depth_aligned', 'ir1', 'ir2'):
            np.save(str(output / (key + '.npy')), frame[key], allow_pickle=False)
            image_write(output / (key + '.png'), cv2.cvtColor(frame[key], cv2.COLOR_RGB2BGR)
                        if key == 'rgb' else frame[key])
        image_write(output / 'alignment_panel.jpg', depth_panel(frame['rgb'], frame['depth_aligned'], meta['depth_scale_m']))
        for key in ('rgb', 'ir1', 'ir2'):
            points = detect(frame[key], board)
            result['corners'][key] = None if points is None else points.tolist()
        if allow_unchecked:
            result['reasons'].append('Snapshot only; not accepted into multiview calibration')
            return result
        if frame['info'].get('selected_frame_age_s', 0.) > .2:
            result['reasons'].append('Selected frame is older than 0.2 seconds; retry with live stream')
        if result['corners']['rgb'] is None or result['corners']['ir1'] is None:
            result['reasons'].append('Complete checkerboard not found in both RGB and IR1')
            return result
        info = frame['info']['streams']
        domains = [s['timestamp_domain'] for s in info.values()]
        ts = [s['sdk_timestamp_ms'] for s in info.values()]
        result['timestamp_span_ms'] = float(max(ts)-min(ts)) if len(set(domains)) == 1 else None
        if len(set(domains)) != 1 or max(ts)-min(ts) > 20.:
            result['reasons'].append('Different SDK time domains or stream timestamp span > 20 ms')
        pts = np.array(result['corners']['rgb'], np.float32).reshape(-1, 1, 2)
        if earlier is None:
            result['reasons'].append('No earlier frame for stationarity check; retry after 1 second')
        else:
            gray = cv2.cvtColor(frame['rgb'], cv2.COLOR_RGB2GRAY)
            old = cv2.cvtColor(earlier['rgb'], cv2.COLOR_RGB2GRAY)
            prev, valid, _ = cv2.calcOpticalFlowPyrLK(gray, old, pts, None)
            good = valid.ravel().astype(bool) if valid is not None else np.zeros(len(pts), bool)
            result['stationarity_interval_s'] = frame['info']['monotonic_s'] - earlier['info']['monotonic_s']
            result['stationarity_tracked_corner_fraction'] = float(good.mean())
            if good.mean() < .9:
                result['reasons'].append('Insufficient optical-flow matches for stationarity check')
            else:
                movement = np.linalg.norm(prev[good] - pts[good], axis=2)
                result['stationarity_motion_p95_px'] = float(np.percentile(movement, 95))
                if result['stationarity_motion_p95_px'] > .75:
                    result['reasons'].append('Board/camera moved > 0.75 px over stationarity interval')
        obj = board_points(board)
        K, d = camera_model(meta['intrinsics']['rgb'])
        T_rgb = pose(obj, np.array(result['corners']['rgb'], np.float32), K, d)
        result['factory_T_rgb_from_board'] = T_rgb.tolist()
        for key in ('ir1', 'ir2'):
            if result['corners'][key] is None:
                continue
            Ki, di = camera_model(meta['intrinsics'][key])
            T = np.array(meta['extrinsics']['rgb_to_' + key]['T_destination_from_source']) @ T_rgb
            ordered, order = orient_corners(np.array(result['corners'][key], np.float32), project(obj, T, Ki, di), board)
            result['corners'][key + '_ordered'] = ordered.tolist()
            result[key + '_orientation'] = order
        result['accepted'] = not result['reasons']
        for key in ('rgb', 'ir1', 'ir2'):
            img = cv2.cvtColor(frame[key], cv2.COLOR_RGB2BGR) if key == 'rgb' else cv2.cvtColor(frame[key], cv2.COLOR_GRAY2BGR)
            if result['corners'][key] is not None:
                cv2.drawChessboardCorners(img, (board['cols'], board['rows']), np.array(result['corners'][key], np.float32).reshape(-1, 1, 2), True)
            image_write(output / (key + '_corners.jpg'), img)
    except Exception as e:
        result['error'] = dict(message=str(e), traceback=traceback.format_exc())
        result['reasons'].append(str(e))
    finally:
        result['files'] = [dict(name=p.name, bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(output.iterdir()) if p.is_file()]
        write_json(output / 'trial.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--board', type=Path, default=Path(__file__).with_name('board.json'))
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--duration-seconds', type=float, default=1800)
    p.add_argument('--capture-delay-seconds', type=float, default=3.,
                   help='Wait before selecting a fresh frame, giving the operator time to release the board/mouse')
    p.add_argument('--emitter-mode', choices=('preserve', 'off', 'on'), default='preserve',
                   help='Temporary projector setting; backed up and restored after capture')
    p.add_argument('--snapshot', action='store_true', help='One raw trial; no multiview acceptance')
    a = p.parse_args()
    if a.duration_seconds <= 0:
        p.error('Duration must be positive')
    if not 0 <= a.capture_delay_seconds <= 10:
        p.error('Capture delay must be between 0 and 10 seconds')
    a.output = a.output.resolve()
    if os.name == 'nt' and a.output.drive.upper() != 'E:':
        p.error('Windows calibration outputs must be on E:')
    a.output.mkdir(parents=True, exist_ok=False)
    board = json.loads(a.board.read_text(encoding='utf-8-sig'))
    if not all(isinstance(board[k], int) and 3 <= board[k] <= 30 for k in ('cols', 'rows')) or not 0 < board['square_mm'] < 1000:
        p.error('Invalid board inner-corner dimensions or square spacing')
    (a.output / 'trials').mkdir()
    snapshot_sources(a.output)
    state = dict(started_utc=now(), output=str(a.output), board=board, busy=False, trials=0, accepted=0,
                 capture_delay_seconds=a.capture_delay_seconds,
                 message='Starting camera', physical_calibration_accepted=False, errors=[])
    write_json(a.output / 'session.json', state)
    lock, stop = threading.Lock(), threading.Event()
    latest, history = {}, deque(maxlen=50)
    preview = b''
    ir_preview = b''
    worker = None
    meta = {}
    server = pipeline = None
    server_started = False
    emitter_sensor, emitter_original, emitter_restore_needed = None, None, False

    def event(action, detail):
        with (a.output / 'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(time=now(), action=action, detail=detail), ensure_ascii=False) + '\n')

    def take_trial(snapshot=False):
        nonlocal worker
        requested = dict(utc=now(), monotonic_s=time.monotonic(),
                         delay_seconds=0. if snapshot else a.capture_delay_seconds)
        with lock:
            if state['busy'] or not latest:
                raise RuntimeError('Capture busy or no camera frame available')
            if shutil.disk_usage(a.output).free < 2 * 1024**3:
                raise RuntimeError('Less than 2 GiB free; capture refused')
            state['busy'] = True
            state['message'] = 'Countdown: keep camera and board still'
            write_json(a.output / 'session.json', state)
        event('capture_requested', requested)
        def task():
            deadline = requested['monotonic_s'] + requested['delay_seconds']
            while not snapshot and time.monotonic() < deadline:
                with lock:
                    state['message'] = '倒计时 %.1f 秒：保持相机和棋盘静止' % max(0., deadline-time.monotonic())
                if stop.wait(min(.1, max(0., deadline-time.monotonic()))):
                    with lock:
                        state['busy'] = False
                        state['message'] = 'Capture cancelled before saving; session stopping'
                    event('capture_cancelled', requested)
                    return
            with lock:
                # Select at the end of the countdown, never the click-time RGB-D.
                frame = latest.copy()
                old = next((s for s in reversed(history) if frame['info']['monotonic_s'] - s['info']['monotonic_s'] >= .3), None)
                frame['info'] = dict(frame['info'], capture_request=requested,
                                     selected_frame_age_s=time.monotonic()-frame['info']['monotonic_s'])
                state['trials'] += 1
                index = state['trials']
                state['message'] = 'Checking board in trial %04d' % index
            result = save_trial(a.output / 'trials' / ('%04d' % index), frame, old, meta, board, snapshot)
            with lock:
                state['busy'] = False
                state['accepted'] += int(result['accepted'])
                state['message'] = ('Accepted trial %04d' % index) if result['accepted'] else '; '.join(result['reasons'])
                state['last_trial'] = dict(index=index, accepted=result['accepted'], reasons=result['reasons'])
                write_json(a.output / 'session.json', state)
            event('trial_saved', state['last_trial'])
            print(json.dumps(state['last_trial']), flush=True)
        worker = threading.Thread(target=task)
        worker.start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                data, kind = render_page(board, a.capture_delay_seconds).encode('utf-8'), 'text/html; charset=utf-8'
            elif self.path == '/status':
                with lock:
                    data = json.dumps(state, ensure_ascii=False).encode('utf-8')
                kind = 'application/json; charset=utf-8'
            elif self.path.startswith('/preview.jpg'):
                with lock:
                    data = preview
                kind = 'image/jpeg'
            elif self.path.startswith('/ir_preview.jpg'):
                with lock:
                    data = ir_preview
                kind = 'image/jpeg'
            elif self.path.startswith('/trial/'):
                parts = self.path.split('/')
                if len(parts) != 4 or len(parts[2]) != 4 or not parts[2].isdigit() or parts[3] != 'rgb.png':
                    self.send_error(404)
                    return
                target = a.output / 'trials' / parts[2] / 'rgb.png'
                if not target.is_file():
                    self.send_error(404)
                    return
                data, kind = target.read_bytes(), 'image/png'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            if self.headers.get('X-Calibration-Control') != '1':
                self.send_error(403, 'Use calibration page controls')
                return
            try:
                if self.path == '/capture':
                    take_trial()
                elif self.path == '/boundary':
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 4096:
                        raise ValueError('Invalid boundary request size')
                    body = json.loads(self.rfile.read(length))
                    index = body['trial']
                    if not isinstance(index, int) or not 1 <= index <= state['trials']:
                        raise ValueError('Invalid saved trial index')
                    with lock:
                        if state['busy']:
                            raise ValueError('Wait until capture finishes')
                    tag = now().replace(':', '').replace('.', '').replace('+', '_')
                    target = a.output / 'boundary_checks' / ('%04d_%s' % (index, tag))
                    result = check_boundary(a.output / 'trials' / ('%04d' % index), body['vertices'], meta['depth_scale_m'], target)
                    event('boundary_annotation', dict(trial=index, output=str(target)))
                    with lock:
                        state['last_boundary'] = dict(trial=index, output=str(target),
                                                     edges=[dict(edge=e['edge'], matched=e['matched'],
                                                                 signed_offset_px=e['signed_offset_px']) for e in result['edges']])
                elif self.path == '/stop':
                    event('operator_stop', {})
                    stop.set()
                else:
                    self.send_error(404)
                    return
                self.send_response(202)
                self.end_headers()
                self.wfile.write(b'Accepted')
            except Exception as e:
                self.send_error(409, str(e))

        def log_message(self, *args):
            pass

    result_code = 0
    try:
        if not a.snapshot:
            server = ThreadingHTTPServer((a.host, a.port), Handler)
        context = rs.context()
        devices = [d for d in context.query_devices() if 'D435I' in d.get_info(rs.camera_info.name).upper()]
        if len(devices) != 1:
            raise RuntimeError('Expected exactly one D435i; found %d' % len(devices))
        device = devices[0]
        config = rs.config()
        config.enable_device(device.get_info(rs.camera_info.serial_number))
        config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        for index in (1, 2):
            config.enable_stream(rs.stream.infrared, index, 640, 480, rs.format.y8, 30)
        pipeline = rs.pipeline(context)
        active = pipeline.start(config)
        sensor = active.get_device().first_depth_sensor()
        option_names = ('emitter_enabled', 'laser_power', 'visual_preset', 'enable_auto_exposure', 'exposure', 'gain')
        before_options = {name: sensor.get_option(getattr(rs.option, name)) for name in option_names
                          if sensor.supports(getattr(rs.option, name))}
        write_json(a.output / 'sensor_settings_before.json', dict(created_utc=now(), options=before_options))
        if a.emitter_mode != 'preserve':
            if not sensor.supports(rs.option.emitter_enabled):
                raise RuntimeError('Explicit emitter mode requested but sensor does not support emitter_enabled')
            emitter_sensor, emitter_original = sensor, float(sensor.get_option(rs.option.emitter_enabled))
            desired = 0. if a.emitter_mode == 'off' else 1.
            emitter_restore_needed = emitter_original != desired
            if emitter_restore_needed:
                sensor.set_option(rs.option.emitter_enabled, desired)
            actual = float(sensor.get_option(rs.option.emitter_enabled))
            event('temporary_emitter_setting', dict(before=emitter_original, requested=desired, actual=actual))
            if actual != desired:
                raise RuntimeError('Requested temporary emitter mode was not applied')
        profiles = dict(rgb=active.get_stream(rs.stream.color), depth_native=active.get_stream(rs.stream.depth),
                        ir1=active.get_stream(rs.stream.infrared, 1), ir2=active.get_stream(rs.stream.infrared, 2))
        meta = dict(device={n: device.get_info(getattr(rs.camera_info, n)) for n in
                            ('name', 'serial_number', 'firmware_version', 'usb_type_descriptor')},
                    depth_scale_m=active.get_device().first_depth_sensor().get_depth_scale(),
                    data_origin='live_d435i',
                    intrinsics={k: intrinsic(v) for k, v in profiles.items()}, extrinsics={},
                    align='rs.align(rs.stream.color); no spatial/temporal/hole filling filters',
                    geometry_convention='T_destination_from_source; x right, y down, z forward; meters',
                    device_calibration_written=False, board=board,
                    emitter_control=dict(requested_mode=a.emitter_mode, before_options=before_options,
                                         restore_required=emitter_restore_needed))
        for src, dst in (('depth_native', 'rgb'), ('ir1', 'rgb'), ('ir2', 'rgb'), ('ir1', 'ir2'),
                         ('rgb', 'ir1'), ('rgb', 'ir2'), ('ir1', 'depth_native'), ('rgb', 'depth_native')):
            meta['extrinsics'][src + '_to_' + dst] = extrinsic(profiles[src], profiles[dst], rs)
        meta['depth_options'] = {}
        for name in option_names:
            option = getattr(rs.option, name)
            if sensor.supports(option):
                meta['depth_options'][name] = sensor.get_option(option)
        state['active_emitter_enabled'] = meta['depth_options'].get('emitter_enabled')
        state['requested_emitter_mode'] = a.emitter_mode
        state['depth_verification_scope'] = ('projector-off checkerboard geometry; production active-depth QA needs a separate projector-on session'
                                             if meta['depth_options'].get('emitter_enabled') == 0 else
                                             'current active projector setting; assess physical depth separately')
        write_json(a.output / 'factory.json', meta)
        np.savetxt(str(a.output / 'K_color.txt'), camera_model(meta['intrinsics']['rgb'])[0])
        np.savetxt(str(a.output / 'K_native_depth.txt'), camera_model(meta['intrinsics']['depth_native'])[0])
        align = rs.align(rs.stream.color)
        for _ in range(60):
            pipeline.wait_for_frames(5000)
        state['message'] = 'Ready: keep board stationary, then save a trial'
        if server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            server_started = True
            print('Calibration page: http://%s:%d' % (a.host, a.port), flush=True)
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        start, count = time.monotonic(), 0
        while not stop.is_set() and time.monotonic()-start < a.duration_seconds:
            frames = pipeline.wait_for_frames(5000)
            raw = dict(rgb=frames.get_color_frame(), depth_native=frames.get_depth_frame(),
                       ir1=frames.get_infrared_frame(1), ir2=frames.get_infrared_frame(2))
            if not all(raw.values()):
                continue
            aligned = align.process(frames).get_depth_frame()
            if not aligned:
                continue
            frame = {k: np.asanyarray(v.get_data()).copy() for k, v in raw.items()}
            frame['depth_aligned'] = np.asanyarray(aligned.get_data()).copy()
            frame['info'] = dict(host_utc=now(), monotonic_s=time.monotonic(), streams={k: frame_info(v) for k, v in raw.items()})
            if 'depth_aligned' not in meta['intrinsics']:
                meta['intrinsics']['depth_aligned'] = intrinsic(aligned.profile)
                meta['aligned_shape_matches_rgb'] = frame['depth_aligned'].shape == frame['rgb'].shape[:2]
                meta['aligned_intrinsics_match_rgb'] = all(meta['intrinsics']['depth_aligned'][k] == meta['intrinsics']['rgb'][k]
                                                           for k in ('width', 'height', 'fx', 'fy', 'cx', 'cy', 'model', 'coeffs'))
                write_json(a.output / 'factory.json', meta)
            count += 1
            jpeg = ir_jpeg = None
            if count % 4 == 1:
                ok, jpg = cv2.imencode('.jpg', depth_panel(frame['rgb'], frame['depth_aligned'], meta['depth_scale_m']),
                                        [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    jpeg = jpg.tobytes()
                ir_panel = np.hstack([frame['ir1'], frame['ir2']])
                ok, jpg = cv2.imencode('.jpg', ir_panel, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    ir_jpeg = jpg.tobytes()
            with lock:
                latest = frame
                history.append(frame)
                state['frames_received'] = count
                if jpeg:
                    preview = jpeg
                if ir_jpeg:
                    ir_preview = ir_jpeg
            if a.snapshot and count >= 16:
                take_trial(snapshot=True)
                break
    except Exception as e:
        result_code = 1
        state['errors'].append(dict(message=str(e), traceback=traceback.format_exc()))
        traceback.print_exc()
    finally:
        if worker:
            worker.join(timeout=60)
        if emitter_restore_needed:
            try:
                emitter_sensor.set_option(rs.option.emitter_enabled, emitter_original)
                restored = float(emitter_sensor.get_option(rs.option.emitter_enabled))
                state['emitter_restore'] = dict(expected=emitter_original, actual=restored,
                                                verified=restored == emitter_original)
                write_json(a.output / 'sensor_settings_after_restore.json', state['emitter_restore'])
                event('emitter_restored', state['emitter_restore'])
                if restored != emitter_original:
                    raise RuntimeError('Temporary emitter mode restoration failed')
            except Exception as e:
                result_code = 1
                state['errors'].append(dict(emitter_restore_error=str(e)))
        if pipeline:
            try:
                pipeline.stop()
                state['pipeline_stopped'] = True
            except Exception as e:
                state['errors'].append(dict(stop_error=str(e)))
        if server:
            if server_started:
                server.shutdown()
            server.server_close()
        state.update(ended_utc=now(), status='failed' if result_code else 'finished', busy=False)
        write_json(a.output / 'session.json', state)
        event('session_end', dict(status=state['status'], accepted=state['accepted']))
        print(json.dumps(state, ensure_ascii=False), flush=True)
    return result_code


if __name__ == '__main__':
    raise SystemExit(main())
