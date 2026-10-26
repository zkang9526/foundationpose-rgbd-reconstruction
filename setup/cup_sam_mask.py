"""Frozen RGB -> isolated official SAM process; retain every prompt and result."""
import json
import hashlib
from pathlib import Path
import subprocess
import time
import uuid
import cv2
import numpy as np


def validate_prompts(rect, points, labels):
    if not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect):
        raise ValueError('矩形需要四个整数')
    x, y, w, h = rect
    if min(x, y) < 0 or min(w, h) < 12 or x + w > 640 or y + h > 480 or w >= 640 or h >= 480:
        raise ValueError('矩形超出画面或尺寸不合适')
    if not isinstance(points, list) or not isinstance(labels, list) or len(points) != len(labels) or len(points) > 64:
        raise ValueError('最多64个前景/背景点，点和标签必须一一对应')
    for point, label in zip(points, labels):
        if (not isinstance(point, list) or len(point) != 2 or any(type(v) is not int for v in point)
                or not 0 <= point[0] < 640 or not 0 <= point[1] < 480 or type(label) is not int or label not in (0, 1)):
            raise ValueError('提示点坐标或前景/背景标签无效')


def generate_sam_mask(root, output, rgb, rect, points, labels, capture):
    validate_prompts(rect, points, labels)
    folder = output / 'mask_attempts' / (time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    np.save(folder / 'rgb.npy', rgb, allow_pickle=False)
    request = dict(rect=rect, points=points, labels=labels,
                   source_sequence=capture.get('sequence'),
                   source_received_monotonic=capture.get('received_monotonic'),
                   model_type='vit_b', mask_is_ground_truth=False)
    (folder / 'request.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
    relative = folder.relative_to(root / 'foundationpose_data')
    code = output.relative_to(root / 'foundationpose_data') / 'worker_code/cup_sam_worker.py'
    command = ['docker', 'exec', 'foundationpose', '/usr/bin/timeout', '--signal=TERM', '--kill-after=5s', '100s', '/opt/conda/envs/my/bin/python', '-B', '-u',
               str(Path('/data') / code), '--attempt', str(Path('/data') / relative)]
    start = time.monotonic()
    with (folder / 'worker.log').open('w', encoding='utf-8') as stream:
        try:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        except subprocess.TimeoutExpired:
            # docker exec client timeout does not guarantee server-side process cancellation.
            (folder / 'host_failure.json').write_text(json.dumps(dict(error='SAM timeout; inspect worker before retry', timeout_seconds=120)))
            raise RuntimeError('SAM超时，检查该次Mask运行记录后重试')
    if result.returncode != 0:
        raise RuntimeError('SAM生成失败，请查看 ' + str(folder / 'worker.log'))
    metadata = json.loads((folder / 'result.json').read_text())
    if not metadata.get('passed'):
        raise RuntimeError('SAM未返回有效Mask')
    for name, key in [('rgb.npy', 'rgb_sha256'), ('request.json', 'request_sha256'), ('mask.png', 'mask_sha256')]:
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != metadata[key]:
            raise RuntimeError('SAM输入/输出SHA校验失败')
    binary = cv2.imread(str(folder / 'mask.png'), cv2.IMREAD_UNCHANGED)
    if binary is None or binary.shape != rgb.shape[:2] or binary.dtype != np.uint8 or not np.isin(binary, [0, 255]).all():
        raise RuntimeError('SAM输出格式不正确')
    metadata['host_seconds'] = time.monotonic() - start
    metadata['attempt'] = str(folder.relative_to(output))
    return binary, metadata
