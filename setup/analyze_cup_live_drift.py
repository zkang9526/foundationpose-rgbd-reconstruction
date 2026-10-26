#!/usr/bin/env python3
"""Audit saved live frames; visualize drift and measured depth without pose GT."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--mesh', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Output must be new')
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    source = json.loads((args.session / 'session.json').read_text())
    assert source['source'] == 'live_d435i' and sha(args.mesh) == source['mesh_sha256']
    vertices = np.array([[float(v) for v in line.split()[1:4]] for line in args.mesh.read_text().splitlines() if line.startswith('v ')])
    center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    K = np.array(source['K'])
    controls = [json.loads(line) for line in (args.session / 'controls.jsonl').read_text().splitlines()]
    events = [json.loads(line) for line in (args.session / 'frame_events.jsonl').read_text().splitlines()]
    init = [row['frame'] for row in events if row['operation'] == 'register']
    data, metadata, poses = [], {}, {}
    args.output.mkdir(parents=True, exist_ok=False)
    sample_ids = sorted(set([0, 1, 2, 3, 5, 10, 20, 40, 80, 120, 160, 200, 240, 280, 320, 360, len(events)-1]))
    previous = None
    for index, event in enumerate(events):
        stem = event['frame']
        folder = args.session / 'frames' / stem
        requestpath = args.session / 'requests' / (stem + '.json')
        request = json.loads(requestpath.read_text())
        assert sha(requestpath) == event['request_sha256']
        for name, digest in request['input_sha256'].items():
            assert sha(folder / name) == digest
        assert sha(folder / 'pose_camera_from_mesh.txt') == event['pose_sha256']
        assert sha(folder / 'overlay.png') == event['overlay_sha256']
        meta = json.loads((folder / 'capture.json').read_text())
        pose = np.loadtxt(folder / 'pose_camera_from_mesh.txt')
        raw = cv2.imread(str(folder / 'depth.png'), -1)
        assert raw.dtype == np.uint16 and pose.shape == (4, 4)
        metadata[stem], poses[stem] = meta, pose
        cam_center = pose[:3, :3] @ center + pose[:3, 3]
        pixel = K @ cam_center
        pixel = pixel[:2] / pixel[2]
        row = dict(frame=stem, operation=event['operation'], rgb_depth_gap_ms=meta['rgb_depth_timestamp_gap_ms'],
                   input_host_gap_seconds=None if previous is None else meta['received_monotonic'] - previous['received_monotonic'],
                   worker_seconds=event['worker_seconds'], bridge_seconds=event['bridge_seconds'],
                   host_receive_to_result_seconds=event['host_receive_to_result_seconds'],
                   predicted_mesh_center_x=float(pixel[0]), predicted_mesh_center_y=float(pixel[1]),
                   predicted_mesh_center_z_m=float(cam_center[2]), whole_raw_depth_nonzero_ratio=float(np.mean(raw > 0)))
        data.append(row)
        previous = meta
        if index in sample_ids:
            scaled = np.clip((raw.astype(np.float32) - 250) / 650 * 255, 0, 255).astype(np.uint8)
            depthvis = cv2.applyColorMap(scaled, cv2.COLORMAP_TURBO)
            depthvis[raw == 0] = 0
            cv2.imwrite(str(args.output / ('depth_' + stem + '.png')), depthvis)
    for page in range(0, len(sample_ids), 6):
        chosen = sample_ids[page:page+6]
        sheet = Image.new('RGB', (320*len(chosen), 780), 'white')
        draw = ImageDraw.Draw(sheet)
        for column, index in enumerate(chosen):
            stem = events[index]['frame']
            for row, path, label in ((0, args.session/'frames'/stem/'rgb.png', 'Raw RGB'),
                                     (1, args.output/('depth_'+stem+'.png'), 'Depth 250..900 mm, black=ZERO'),
                                     (2, args.session/'frames'/stem/'overlay.png', 'Saved estimated pose overlay')):
                image = Image.open(path).convert('RGB').resize((320, 240))
                draw.text((column*320+4, row*260+3), stem+' '+label, fill='black')
                sheet.paste(image, (column*320, row*260+20))
        sheet.save(args.output / ('timeline_%02d.png' % (page//6)))
    first, second = metadata['000000'], metadata['000001']
    manual = {}
    for stem, rect in [('000000', [164, 160, 265, 246]), ('000001', [271, 320, 337, 387])]:
        raw = cv2.imread(str(args.session/'frames'/stem/'depth.png'), -1)
        x0, y0, x1, y1 = rect
        region = raw[y0:y1, x0:x1]
        valid = region[region > 0]
        manual[stem] = dict(scope='manually inspected visible cyan body core, not full target', rectangle_xyxy=rect,
                            nonzero_ratio=float(np.mean(region > 0)),
                            depth_mm_percentiles_5_50_95=np.percentile(valid,[5,50,95]).tolist() if len(valid) else None)
    # Independent manually inspected body rectangles show image displacement only.
    positions = dict(initial_cyan_body_bbox=[143, 107, 296, 272], first_track_cyan_body_bbox=[249, 281, 374, 413])
    c0 = np.array([(143+296)/2, (107+272)/2])
    c1 = np.array([(249+374)/2, (281+413)/2])
    positions.update(body_bbox_center_displacement_px=float(np.linalg.norm(c1-c0)),
                     scope='image-coordinate body samples only; not 6D ground truth')
    mask = cv2.imread(str(args.session/'frames/000000/mask.png'), 0)>0
    raw0 = cv2.imread(str(args.session/'frames/000000/depth.png'), -1)
    report = dict(passed=True, scope='399-frame saved-input integrity and qualitative drift diagnosis',
                  pose_accuracy_validated=False, source_session=str(args.session), source_session_sha256=sha(args.session/'session.json'),
                  model_sha256=sha(args.mesh), completed_frames=len(events), registers=init,
                  initial_mask_nonzero_ratio=float(np.mean(raw0[mask]>0)),
                  freeze_to_first_tracking_host_seconds=second['received_monotonic']-first['received_monotonic'],
                  initial_pose_worker_seconds=data[0]['worker_seconds'], manual_body_samples=manual,
                  first_input_body_displacement=positions,
                  rgb_depth_timestamp_gap_ms=dict(min=min(r['rgb_depth_gap_ms'] for r in data),
                                                 median=statistics.median(r['rgb_depth_gap_ms'] for r in data),
                                                 max=max(r['rgb_depth_gap_ms'] for r in data)),
                  steady_tracking_host_gap_seconds=dict(median=statistics.median(r['input_host_gap_seconds'] for r in data[2:]),
                                                        max=max(r['input_host_gap_seconds'] for r in data[2:])),
                  estimated_processing_fps_after_first_transition=(len(data)-2)/(metadata[events[-1]['frame']]['received_monotonic']-second['received_monotonic']),
                  controls=controls, frame_metrics=data)
    with (args.output/'frame_metrics.csv').open('x',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    small={k:v for k,v in report.items() if k not in ('controls','frame_metrics')}
    print(json.dumps(small))


if __name__ == '__main__':
    main()
