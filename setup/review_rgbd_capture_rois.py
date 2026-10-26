#!/usr/bin/env python3
"""Read-only sequence timing and manually chosen depth-patch review.

Rectangles are diagnostic samples, not cup segmentation masks. Each frame's
host elapsed time and SDK counter are assessed within its source capture.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def stats(values):
    a = np.asarray(values, float)
    if not a.size:
        return None
    return dict(n=int(a.size), minimum=float(a.min()), mean=float(a.mean()), median=float(np.median(a)),
                p05=float(np.percentile(a, 5)), p95=float(np.percentile(a, 95)), maximum=float(a.max()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--rois', type=Path, required=True)
    p.add_argument('--contact-report', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    meta, annotations = read(args.scene/'metadata.json'), read(args.rois)
    frames = meta['frames']
    contact = read(args.contact_report)
    if Path(contact['scene']).resolve() != args.scene.resolve():
        raise ValueError('Contact sheet sources belong to another scene')
    for source in contact['source_files']:
        if sha(Path(source['path'])) != source['sha256']:
            raise ValueError('Contact source SHA changed: '+source['path'])
    with (args.scene/'timestamps.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != len(frames) or read(args.scene/'timestamps.json') != frames:
        raise ValueError('CSV/JSON counts or saved metadata differ')
    for row, frame in zip(rows, frames):
        if row['rgb'] != frame['rgb'] or row['depth'] != frame['depth'] or int(row['index']) != frame['index']:
            raise ValueError('Timestamp order mismatch')
    report = dict(scene=str(args.scene.resolve()), scope='Diagnostic patches and saved timing only; no masks or calibration acceptance',
                  human_mask_annotation_created=False, raw_files_modified=False,
                  verified_rgb_depth_sha_files=len(contact['source_files']), roi_annotation=annotations,
                  roi_annotation_sha256=sha(args.rois), metadata_sha256=sha(args.scene/'metadata.json'),
                  per_frame=[], source_captures={}, patch_summary={},
                  limitations=['Rectangles are selected by assistant visual review; they are sparse surface samples, not full object masks.',
                               'Nonzero depth is availability, not true depth accuracy. Patch percentiles do not prove physical calibration.',
                               'Single photographs cannot independently verify physical stillness or exact rotation.',
                               'Missing depth and stereo occlusion near silhouette/handle remain visible; no filtering or filling is applied.',
                               'The visible upper face is cup bottom because the cup is inverted. Mouth/interior/contact surface are not covered.'])
    patch_data = {item['name']: [] for item in annotations['patches']}
    rgb_hashes, depth_hashes = [], []
    selected_overlays = set(annotations['overlay_frames'])
    for i, frame in enumerate(frames):
        rgb_path, depth_path = args.scene/frame['rgb'], args.scene/frame['depth']
        rgb = cv2.imread(str(rgb_path))
        depth = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
        if rgb is None or depth is None or rgb.shape != (480,640,3) or depth.shape != (480,640) or depth.dtype != np.uint16:
            raise ValueError('Unexpected saved RGB/depth format')
        ratio = float(np.mean(depth > 0))
        if not np.isclose(ratio, frame['saved_valid_pixel_ratio']):
            raise ValueError('Raw depth ratio differs from metadata')
        rgb_hashes.append(sha(rgb_path)); depth_hashes.append(sha(depth_path))
        local = frame.get('source_capture_scene', str(args.scene.resolve()))
        group = report['source_captures'].setdefault(local, [])
        group.append(frame)
        patch_stats = {}
        for item in annotations['patches']:
            if item.get('frames') is not None and i not in item['frames']:
                continue
            x0,y0,x1,y1 = item['xyxy']
            if not 0 <= x0 < x1 <= 640 or not 0 <= y0 < y1 <= 480:
                raise ValueError('Patch outside image')
            values = depth[y0:y1,x0:x1]
            valids = values[values > 0]
            item_stats = dict(valid_percent=float(np.mean(values > 0)*100), positive_depth_mm=stats(valids),
                              positive_over_1500mm=int(np.count_nonzero(values > 1500)), pixels=int(values.size))
            patch_stats[item['name']] = item_stats
            patch_data[item['name']].append(dict(frame=i, **item_stats))
            if i in selected_overlays:
                cv2.rectangle(rgb,(x0,y0),(x1-1,y1-1),(0,255,255),1)
                cv2.putText(rgb,item['name'],(x0,y0-3),cv2.FONT_HERSHEY_SIMPLEX,.29,(0,0,255),1)
        if i in selected_overlays:
            cv2.imwrite(str(args.output/('patches_'+Path(frame['rgb']).name)),rgb)
        gap = abs(frame['color_timestamp_ms']-frame['depth_timestamp_ms'])
        wait = frame['host_elapsed_seconds']-frame['request_host_elapsed_seconds']
        report['per_frame'].append(dict(index=i, rgb=frame['rgb'], whole_valid_percent=ratio*100,
            timestamp_gap_ms=gap, post_request_wait_seconds=wait,
            timestamp_domains_match=frame['color_timestamp_domain']==frame['depth_timestamp_domain'], patches=patch_stats))
    for name, data in patch_data.items():
        report['patch_summary'][name] = dict(frames=len(data), per_frame_valid_percent=stats([x['valid_percent'] for x in data]),
            per_frame_positive_median_depth_mm=stats([x['positive_depth_mm']['median'] for x in data if x['positive_depth_mm']]),
            min_valid_frames=[x['frame'] for x in data if x['valid_percent']==min(y['valid_percent'] for y in data)] if data else [],
            positive_over_1500mm_total=sum(x['positive_over_1500mm'] for x in data))
    groups = {}
    for path, group in report['source_captures'].items():
        streams = {}
        for stream in ('color','depth'):
            numbers=[f[stream+'_frame_number'] for f in group]
            times=[f[stream+'_timestamp_ms'] for f in group]
            streams[stream]=dict(unique=len(set(numbers))==len(numbers),
                increasing_frame_numbers=all(b>a for a,b in zip(numbers,numbers[1:])),
                increasing_timestamps=all(b>a for a,b in zip(times,times[1:])))
        groups[path]=dict(frames=len(group),streams=streams)
    report['source_captures']=groups
    report['whole_valid_percent']=stats([f['whole_valid_percent'] for f in report['per_frame']])
    report['timestamp_gap_ms']=stats([f['timestamp_gap_ms'] for f in report['per_frame']])
    report['settle_seconds']=stats([f['post_request_wait_seconds'] for f in report['per_frame']])
    report['identical_rgb_content_groups']=[[i for i,x in enumerate(rgb_hashes) if x==v] for v in set(rgb_hashes) if rgb_hashes.count(v)>1]
    report['identical_depth_content_groups']=[[i for i,x in enumerate(depth_hashes) if x==v] for v in set(depth_hashes) if depth_hashes.count(v)>1]
    report['timing_checks_passed']=(all(f['timestamp_domains_match'] and f['timestamp_gap_ms']<=meta['requested']['max_timestamp_gap_ms']
        and f['post_request_wait_seconds']+1e-8>=meta['requested']['settle_seconds'] for f in report['per_frame'])
        and all(all(all(s.values()) for s in group['streams'].values()) for group in groups.values()))
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(__file__,args.output/Path(__file__).name)
    shutil.copy2(args.rois,args.output/args.rois.name)
    print(json.dumps({k:report[k] for k in ('timing_checks_passed','whole_valid_percent','timestamp_gap_ms','settle_seconds','patch_summary','identical_rgb_content_groups')},ensure_ascii=False))


if __name__=='__main__':
    main()
