#!/usr/bin/env python3
"""Create a derived RGB-D sequence replacing only its last pair.

Never edits either capture. Original and retake timebases/metadata remain
explicit; a planned sequence angle is a human label, never a measured pose.
"""
import argparse
import copy
import csv
import datetime
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--retake', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, retake, output = (p.resolve() for p in (args.source, args.retake, args.output))
    if output.exists() or source == retake or source in output.parents or retake in output.parents:
        raise ValueError('Choose an entirely new output outside either source capture')
    base, replacement = read(source/'metadata.json'), read(retake/'metadata.json')
    request = read(retake/'retake_request.json')
    if not base.get('passed') or not replacement.get('passed') or replacement['saved_frames'] != 1:
        raise ValueError('Expected a complete source and complete one-pair retake')
    frames = base['frames']
    if len(frames) != base['saved_frames'] or len(frames) < 2:
        raise ValueError('Invalid source frame count')
    target = frames[-1]
    if request['source_scene'] != str(source) or request['source_frame_index'] != target['index']:
        raise ValueError('Retake request targets a different original frame')
    for item in request['original_files']:
        path = Path(item['path']).resolve()
        if source not in path.parents or sha(path) != item['sha256']:
            raise ValueError('Original source evidence changed')
    for key in ('color_intrinsics', 'native_depth_intrinsics', 'aligned_depth_intrinsics',
                'native_depth_to_color_extrinsics', 'saved_depth', 'native_depth_scale_meters_per_unit'):
        if base.get(key) != replacement.get(key):
            raise ValueError('Capture compatibility mismatch: '+key)
    if base['device']['serial_number'] != replacement['device']['serial_number']:
        raise ValueError('Camera serial mismatch')
    if not np.array_equal(np.loadtxt(source/'K.txt'), np.loadtxt(retake/'K.txt')):
        raise ValueError('K mismatch')
    if (source/'depth_scale.txt').read_bytes() != (retake/'depth_scale.txt').read_bytes():
        raise ValueError('Saved depth scale mismatch')
    old_options = base['depth_processing']['active_sensor_options']
    new_options = replacement['depth_processing']['active_sensor_options']
    stable_options = [k for k in old_options if k not in ('exposure', 'gain')]
    if old_options.get('enable_auto_exposure') != 1:
        stable_options += ['exposure', 'gain']
    if any(old_options.get(k) != new_options.get(k) for k in stable_options):
        raise ValueError('Acquisition options changed; retain retake separately for review')
    output.mkdir(parents=True, exist_ok=False)
    for directory in ('rgb', 'depth', 'provenance'):
        (output/directory).mkdir()
    selected, evidence = [], []
    new_frame = replacement['frames'][0]
    source_initial_sha = {str(source/item[k]): sha(source/item[k]) for item in frames for k in ('rgb', 'depth')}
    for index, original in enumerate(frames):
        changed = index == len(frames)-1
        origin, actual = (retake, new_frame) if changed else (source, original)
        row = copy.deepcopy(actual)
        row.update(index=original['index'], rgb=original['rgb'], depth=original['depth'],
                   planned_angle_degrees=original['planned_angle_degrees'], planned_angle_is_measured=False,
                   source_capture_scene=str(origin), source_capture_index=actual['index'],
                   source_capture_host_elapsed_seconds_timebase='local to this source capture, not a continuous composed timeline',
                   replacement_of_original_last_pair=changed)
        if changed:
            row['source_capture_original_planned_angle_degrees'] = actual.get('planned_angle_degrees')
            row['planned_angle_assignment'] = 'Original sequence plan retained as intended operator position only; no measured rotation'
        for kind in ('rgb', 'depth'):
            src, dst = origin/actual[kind], output/row[kind]
            digest = sha(src)
            shutil.copy2(src, dst)
            if sha(dst) != digest:
                raise ValueError('Copied file SHA mismatch: '+str(dst))
            evidence.append(dict(output=dst.relative_to(output).as_posix(), source=str(src), sha256=digest,
                                 replaces_original=changed))
        with Image.open(output/row['rgb']) as rgb:
            if rgb.mode != 'RGB' or rgb.size != (640, 480):
                raise ValueError('Unexpected RGB format')
        with Image.open(output/row['depth']) as image:
            depth = np.asarray(image)
            ratio = float(np.count_nonzero(depth)/depth.size)
            if image.size != (640, 480) or not np.isclose(ratio, row['saved_valid_pixel_ratio']):
                raise ValueError('Depth shape/validity mismatch')
        selected.append(row)
    for name in ('K.txt', 'cam_K.txt', 'depth_scale.txt'):
        shutil.copy2(source/name, output/name)
        if sha(source/name) != sha(output/name):
            raise ValueError('Calibration file copy differs')
    for origin, label in ((source, 'original'), (retake, 'retake')):
        for name in ('metadata.json', 'report.json', 'timestamps.json', 'timestamps.csv'):
            shutil.copy2(origin/name, output/'provenance'/(label+'_'+name))
    shutil.copy2(retake/'retake_request.json', output/'provenance'/'retake_request.json')
    shutil.copy2(__file__, output/'provenance'/Path(__file__).name)
    for path, digest in source_initial_sha.items():
        if sha(Path(path)) != digest:
            raise ValueError('Source changed during composition')
    metadata = copy.deepcopy(base)
    for key in ('elapsed_seconds', 'capture_seconds', 'acquired_frames'):
        metadata.pop(key, None)
    metadata.update(output=str(output), scope='Derived file selection and format checks only, not new continuous acquisition or geometry acceptance',
                    capture_mode='derived_sequence_with_one_last_pair_retake', frames=selected,
                    saved_frames=len(selected), passed=True, status='complete',
                    source_scene=str(source), retake_scene=str(retake),
                    capture_session_count=2, mixed_session_frame_timestamps=True,
                    host_elapsed_seconds_are_per_source_capture=True,
                    source_originals_unmodified_verified=True, unchanged_source_pairs=len(frames)-1,
                    pipeline_started=False, pipeline_stopped=True,
                    finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    aggregate_saved_valid_pixel_ratio=float(np.mean([f['saved_valid_pixel_ratio'] for f in selected])))
    metadata['bag_recording'] = dict(enabled=False, file=None,
        scope='Native recordings remain in the two immutable source scenes; no composed or continuous bag exists',
        source_files=[str(p/'raw_streams.bag') for p in (source, retake) if (p/'raw_streams.bag').exists()])
    metadata['warnings'].append('The last pair was recaptured in a new session; SDK frame counters reset, and host elapsed times are local to each source. Planned355 is not GT.')
    write(output/'metadata.json', metadata)
    write(output/'report.json', {k:v for k,v in metadata.items() if k != 'frames'})
    write(output/'timestamps.json', selected)
    fields = list(selected[0])
    fields += sorted(set().union(*(set(f) for f in selected))-set(fields))
    with (output/'timestamps.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    manifest = dict(source_scene=str(source), retake_scene=str(retake), output_scene=str(output),
                    replaced_frame=target['rgb'].split('/')[-1], original_bad_pair_retained=True,
                    source_originals_unmodified_verified=True, unchanged_pairs=len(frames)-1,
                    files=evidence, rejected_original_last_pair={k:dict(path=str(source/target[k]),sha256=sha(source/target[k])) for k in ('rgb','depth')},
                    replacement_capture_metadata_sha256=sha(retake/'metadata.json'),
                    physical_geometry_accepted=False, planned_angle_is_measured=False)
    write(output/'replacement_manifest.json', manifest)
    write(output/'transfer_manifest.json', dict(files=[dict(path=p.relative_to(output).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
        for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'transfer_manifest.json']))
    print(json.dumps(dict(passed=True, output=str(output), pairs=len(selected), replaced_frame=target['rgb'],
                         unchanged_pairs=len(frames)-1, original_source_modified=False)))


if __name__ == '__main__':
    main()
