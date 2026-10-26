"""One-shot official SAM inference inside the existing GPU container, no pip changes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True, type=Path)
    args = parser.parse_args()
    folder = args.attempt.resolve(strict=True)
    folder.relative_to(Path('/data'))
    if folder.parent.name != 'mask_attempts':
        raise ValueError('SAM writes only to explicit mask_attempts directories')
    started = time.monotonic()
    result = dict(passed=False, mask_is_ground_truth=False, backend='official SAM ViT-B')
    try:
        import cv2
        import numpy as np
        import torch
        sys.path.insert(0, '/data/tools/segment-anything')
        from segment_anything import SamPredictor, sam_model_registry
        install = json.loads(Path('/data/checkpoints/sam/installation.json').read_text())
        checkpoint = Path('/data/checkpoints/sam/sam_vit_b_01ec64.pth')
        if digest(checkpoint) != install['checkpoint_sha256']:
            raise ValueError('SAM checkpoint SHA mismatch')
        request = json.loads((folder / 'request.json').read_text())
        rgb = np.load(str(folder / 'rgb.npy'), allow_pickle=False)
        if rgb.shape != (480, 640, 3) or rgb.dtype != np.uint8:
            raise ValueError('Expected native 640x480 uint8 RGB')
        sam = sam_model_registry['vit_b'](checkpoint=str(checkpoint)).to(device='cuda').eval()
        predictor = SamPredictor(sam)
        torch.cuda.synchronize()
        inference_start = time.monotonic()
        x, y, w, h = request['rect']
        with torch.inference_mode():
            predictor.set_image(rgb, image_format='RGB')
            masks, scores, _ = predictor.predict(
                box=np.array([x, y, x + w, y + h], dtype=np.float32),
                point_coords=np.array(request['points'], dtype=np.float32) if request['points'] else None,
                point_labels=np.array(request['labels'], dtype=np.int32) if request['labels'] else None,
                multimask_output=False)
        torch.cuda.synchronize()
        binary = masks[0].astype(np.uint8) * 255
        if not binary.any():
            raise ValueError('SAM returned empty mask; adjust box/points')
        if not cv2.imwrite(str(folder / 'mask.png'), binary):
            raise RuntimeError('Mask PNG write failed')
        result.update(passed=True, sam_predicted_iou=float(scores[0]), score_is_pose_accuracy=False,
                      prompt_agreement=[bool(masks[0, p[1], p[0]]) == bool(label) for p, label in zip(request['points'], request['labels'])],
                      installation=install, rgb_sha256=digest(folder / 'rgb.npy'),
                      request_sha256=digest(folder / 'request.json'), mask_sha256=digest(folder / 'mask.png'),
                      inference_seconds=time.monotonic() - inference_start,
                      cuda_peak_allocated_mb=torch.cuda.max_memory_allocated() / 1024 ** 2,
                      torch=torch.__version__, gpu=torch.cuda.get_device_name())
    except Exception as error:
        result['error'] = str(error)
        traceback.print_exc()
    result['worker_seconds'] = time.monotonic() - started
    (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
