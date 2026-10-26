"""Bounded native SAM2 process and hashed retained artifacts."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid
import cv2
import numpy as np
from sam2_runtime_environment import sam2_runtime_environment


def run_sam2(root, output, rgb, rect=None, points=None, labels=None, capture=None, mode='prompt', depth=None):
    folder = output / 'mask_attempts' / ('sam2_' + time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    np.save(folder / 'rgb.npy', rgb, allow_pickle=False)
    if depth is not None:
        np.save(folder / 'depth.npy', depth, allow_pickle=False)
    (folder / 'capture.json').write_text(json.dumps({k: v for k, v in (capture or {}).items() if k not in ('rgb', 'depth', 'mask')}, indent=2))
    request = dict(mode=mode, rect=rect, points=points or [], labels=labels or [],
                   source_sequence=(capture or {}).get('sequence'), mask_is_ground_truth=False,
                   capture_sha256=hashlib.sha256((folder / 'capture.json').read_bytes()).hexdigest(),
                   depth_sha256=hashlib.sha256((folder / 'depth.npy').read_bytes()).hexdigest() if depth is not None else None)
    (folder / 'request.json').write_text(json.dumps(request, indent=2))
    exe = root / 'foundationpose_data/environments/sam2/bin/python'
    code = output / 'worker_code/cup_sam2_worker.py'
    start = time.monotonic()
    child, libraries = sam2_runtime_environment(root)
    with (folder / 'worker.log').open('w') as stream:
        process = subprocess.Popen([str(exe), '-B', '-u', str(code), '--attempt', str(folder)], stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, env=child)
        try:
            result = process.wait(timeout=100)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            (folder / 'host_failure.json').write_text(json.dumps(dict(error='SAM2 timeout', timeout_seconds=100)))
            raise RuntimeError('SAM2 timed out; attempt retained')
    if result:
        raise RuntimeError('SAM2失败，查看 ' + str(folder / 'worker.log'))
    metadata = json.loads((folder / 'result.json').read_text())
    for name, key in [('rgb.npy', 'rgb_sha256'), ('request.json', 'request_sha256'), (metadata['artifact'], 'artifact_sha256')]:
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != metadata[key]:
            raise ValueError('SAM2 artifact SHA mismatch')
    if hashlib.sha256((folder / 'capture.json').read_bytes()).hexdigest() != request['capture_sha256']:
        raise ValueError('Capture evidence changed during SAM2 inference')
    if depth is not None and hashlib.sha256((folder / 'depth.npy').read_bytes()).hexdigest() != request['depth_sha256']:
        raise ValueError('Depth evidence changed during SAM2 inference')
    metadata.update(host_seconds=time.monotonic() - start, attempt=str(folder.relative_to(output)), runtime_library_directories=libraries)
    if mode == 'search':
        with np.load(folder / 'proposals.npz', allow_pickle=False) as data:
            return data['masks'], metadata
    return cv2.imread(str(folder / 'mask.png'), cv2.IMREAD_UNCHANGED), metadata
