#!/usr/bin/env python3
"""Synthetic HTTP tests for manual-mask rasterization and evidence retention."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

from PIL import Image

from manual_mask_editor import Editor, make_server, render_mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    scene, annotations = args.output / 'synthetic_scene', args.output / 'annotations'
    for directory in ('rgb', 'depth'):
        (scene / directory).mkdir(parents=True)
    for index in range(2):
        name = '%06d.png' % index
        Image.new('RGB', (80, 60), (100, 140 + index, 180)).save(scene / 'rgb' / name)
        Image.new('I;16', (80, 60), 450).save(scene / 'depth' / name)
    before = {str(p.relative_to(scene)): hashlib.sha256(p.read_bytes()).hexdigest() for p in scene.rglob('*.png')}
    tests = []

    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        tests.append(label)

    editor = Editor(scene, annotations)
    server = make_server(editor, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)

    def call(path, value=None, origin=None, token=None, headers=None):
        request_headers = dict(headers or {})
        data = None
        if value is not None:
            data = json.dumps(value).encode()
            request_headers.update({'Content-Type': 'application/json', 'X-Editor-Token': token or editor.token})
        if origin:
            request_headers['Origin'] = origin
        request = urllib.request.Request(base + path, data=data, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    outer = dict(type='polygon', value=255, points=[[10, 10], [65, 10], [65, 50], [10, 50]])
    hole = dict(type='polygon', value=0, points=[[25, 20], [40, 20], [40, 35], [25, 35]])
    brush = dict(type='brush', value=255, radius=2, points=[[3, 3], [7, 3]])
    erase = dict(type='brush', value=0, radius=1, points=[[50, 40], [55, 40]])
    operations = [outer, hole, brush, erase]
    try:
        check('page_served_with_session_token', call('/')[0] == 200 and editor.token.encode() in call('/')[1])
        check('source_image_endpoint', call('/image?index=0')[0] == 200)
        check('no_arbitrary_file_route', call('/image?path=../../AGENTS.md')[0] == 400 and call('/../../AGENTS.md')[0] == 404)
        check('reject_invalid_host', call('/status', headers={'Host': 'evil.example'})[0] == 400)
        check('reject_cross_origin', call('/preview', {'index': 0, 'operations': operations}, origin='http://evil.example')[0] == 400)
        check('reject_wrong_token', call('/preview', {'index': 0, 'operations': operations}, token='invalid')[0] == 400)
        code, body = call('/preview', {'index': 0, 'operations': operations})
        preview = json.loads(body)
        check('preview_final_binary', code == 200)
        payload = dict(index=0, base_revision=None, operations=operations, confirmed=True, preview_sha256=preview['mask_sha256'])
        check('reject_changed_preview', call('/save', dict(payload, preview_sha256='0' * 64))[0] == 400)
        code, body = call('/save', payload)
        revision1 = json.loads(body)['revision']
        check('save_human_confirmed_revision', code == 200)
        mask_path = annotations / 'masks' / '000000.png'
        with Image.open(mask_path) as mask:
            check('original_resolution_binary_L', mask.mode == 'L' and mask.size == (80, 60) and set(mask.tobytes()) == {0, 255})
            check('foreground_and_background_hole', mask.getpixel((15, 15)) == 255 and mask.getpixel((30, 25)) == 0)
            check('brush_and_erase', mask.getpixel((5, 3)) == 255 and mask.getpixel((52, 40)) == 0)
        check('preview_exactly_matches_saved_png', hashlib.sha256(mask_path.read_bytes()).hexdigest() == preview['mask_sha256'])
        original_revision_bytes = {p.name: p.read_bytes() for p in (annotations / 'revisions' / revision1).iterdir()}
        check('reject_stale_revision', call('/save', payload)[0] == 409)
        # Undo is replay of a shortened operation list, without modifying old evidence.
        undone = operations[:-1]
        check('undo_operation_replay', render_mask([80, 60], undone).getpixel((52, 40)) == 255)
        p2 = json.loads(call('/preview', {'index': 0, 'operations': undone})[1])
        next_payload = dict(payload, base_revision=revision1, operations=undone, preview_sha256=p2['mask_sha256'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: call('/save', next_payload)[0], range(2)))
        check('concurrent_save_one_winner', sorted(results) == [200, 409])
        check('old_revision_immutable', all(p.read_bytes() == original_revision_bytes[p.name] for p in (annotations / 'revisions' / revision1).iterdir()))
        empty = json.loads(call('/preview', {'index': 1, 'operations': []})[1])
        check('reject_empty_confirmed_mask', call('/save', dict(index=1, base_revision=None, operations=[], confirmed=True, preview_sha256=empty['mask_sha256']))[0] == 400)
        check('reject_outside_image_coordinate', call('/preview', {'index': 0, 'operations': [dict(outer, points=[[0, 0], [80, 0], [0, 20]])]})[0] == 400)
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        try:
            # Only send the excessive Content-Length header: the server must
            # reject it before allocating/reading the body. Sending a huge body
            # would legitimately race a Windows connection reset on rejection.
            connection.request('POST', '/preview', headers={'Content-Type': 'application/json',
                               'Content-Length': '2000001', 'X-Editor-Token': editor.token})
            response = connection.getresponse()
            check('reject_oversized_json_before_read', response.status == 400)
            response.read()
        finally:
            connection.close()
        try:
            duplicate = Editor(scene, annotations)
        except ValueError:
            tests.append('reject_second_process_output_lock')
        else:
            duplicate.close()
            raise AssertionError('Second output lock was permitted')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        editor.close()
    # Removing a derived export simulates a crash between state commit and export.
    mask_path.unlink()
    resumed = Editor(scene, annotations)
    try:
        check('restart_keeps_revision_and_repairs_export', resumed.detail(0)['confirmed'] and mask_path.exists() and len(list((annotations / 'revisions').iterdir())) == 2)
        after = {str(p.relative_to(scene)): hashlib.sha256(p.read_bytes()).hexdigest() for p in scene.rglob('*.png')}
        check('source_rgb_depth_unchanged', before == after)
        Image.new('RGB', (80, 60), (1, 2, 3)).save(scene / 'rgb' / '000001.png')
        unchanged = dict(index=1, base_revision=None, operations=[outer], confirmed=True,
                         preview_sha256=hashlib.sha256(__import__('manual_mask_editor').mask_bytes(render_mask([80, 60], [outer]))).hexdigest())
        try:
            resumed.save(unchanged)
        except ValueError:
            tests.append('source_change_blocks_save')
        else:
            raise AssertionError('Changed source accepted')
    finally:
        resumed.close()
    report = dict(passed=True, scope='synthetic_http_and_filesystem_smoke_only', tests=tests, test_count=len(tests),
                  actual_cup_annotation_validated=False, output=str(args.output.resolve()))
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
