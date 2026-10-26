"""Isolated SAM2.1 image prompting or full-image proposals, never 6D ground truth."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import time
import traceback


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', type=Path, required=True)
    args = parser.parse_args()
    folder = args.attempt.resolve(strict=True)
    root = Path('/data/ZJC/foundationPos/foundationpose_data')
    folder.relative_to(root)
    if folder.parent.name != 'mask_attempts':
        raise ValueError('Expected a retained mask attempt')
    started = time.monotonic()
    result = dict(passed=False, backend='SAM2.1 Hiera Tiny', mask_is_ground_truth=False)
    try:
        import cv2
        import numpy as np
        import torch
        sys.path.insert(0, str(root / 'tools/sam2'))
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        install = json.loads((root / 'checkpoints/sam2/installation.json').read_text())
        commit = subprocess.check_output(['git', '-C', str(root / 'tools/sam2'), 'rev-parse', 'HEAD'], text=True).strip()
        if commit != install['commit']:
            raise ValueError('SAM2 source commit differs from installation manifest')
        checkpoint = root / 'checkpoints/sam2/sam2.1_hiera_tiny.pt'
        if digest(checkpoint) != install['checkpoint_sha256']:
            raise ValueError('SAM2 checkpoint SHA mismatch')
        request = json.loads((folder / 'request.json').read_text())
        rgb = np.load(folder / 'rgb.npy', allow_pickle=False)
        if rgb.shape != (480, 640, 3) or rgb.dtype != np.uint8:
            raise ValueError('SAM2 requires native 640x480 uint8 RGB')
        model = build_sam2(install['config'], str(checkpoint), device='cuda')
        torch.cuda.synchronize()
        inference_start = time.monotonic()
        with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
            if request.get('mode') == 'search':
                from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
                generator = SAM2AutomaticMaskGenerator(model, points_per_side=16, points_per_batch=64,
                    pred_iou_thresh=.80, stability_score_thresh=.90, crop_n_layers=0, min_mask_region_area=0)
                proposals = generator.generate(rgb)
                proposals = [v for v in proposals if 300 <= v['area'] <= rgb.shape[0] * rgb.shape[1] * .6]
                masks = np.stack([v['segmentation'] for v in proposals]) if proposals else np.zeros((0, 480, 640), bool)
                np.savez_compressed(folder / 'proposals.npz', masks=masks)
                result['candidates'] = [{k: v[k] for k in ('area', 'bbox', 'predicted_iou', 'stability_score')} for v in proposals]
                artifact = 'proposals.npz'
            else:
                predictor = SAM2ImagePredictor(model, max_hole_area=0, max_sprinkle_area=0)
                predictor.set_image(rgb)
                x, y, w, h = request['rect']
                masks, scores, _ = predictor.predict(box=np.array([x, y, x + w, y + h]),
                    point_coords=np.array(request['points']) if request['points'] else None,
                    point_labels=np.array(request['labels']) if request['labels'] else None, multimask_output=False)
                if not masks[0].any():
                    raise ValueError('SAM2 returned empty mask; adjust prompts')
                if not cv2.imwrite(str(folder / 'mask.png'), masks[0].astype(np.uint8) * 255):
                    raise RuntimeError('Mask write failed')
                result.update(sam_predicted_iou=float(scores[0]), prompt_agreement=[bool(masks[0, p[1], p[0]]) == bool(label) for p, label in zip(request['points'], request['labels'])])
                artifact = 'mask.png'
        torch.cuda.synchronize()
        result.update(passed=True, installation=install, artifact=artifact, artifact_sha256=digest(folder / artifact),
                      rgb_sha256=digest(folder / 'rgb.npy'), request_sha256=digest(folder / 'request.json'),
                      inference_seconds=time.monotonic() - inference_start, torch=torch.__version__,
                      cuda_peak_allocated_mb=torch.cuda.max_memory_allocated() / 1024 ** 2,
                      precision='bfloat16 autocast', optional_connected_component_extension_used=False)
    except Exception as error:
        result['error'] = str(error)
        traceback.print_exc()
    result['worker_seconds'] = time.monotonic() - started
    (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
