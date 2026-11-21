"""Retained box/point SAM2 proposals for the local human mask editor."""
import json
from pathlib import Path
import secrets
import threading
import time

from manual_mask_editor import atomic_bytes, atomic_json, mask_bytes, now, sha


class PromptedSam:
    def __init__(self, runtime):
        self.runtime = Path(runtime).resolve(strict=True)
        self.predictor = None
        self.image_sha256 = None
        self.lock = threading.Lock()

    def generate(self, editor, frame, value):
        import numpy as np
        from cup_sam_mask import validate_prompts
        rect = value['rect']
        points, labels = value['points'], value['labels']
        validate_prompts(rect, points, labels)
        x, y, width, height = rect
        if x < 0 or y < 0 or x + width > frame['size'][0] or y + height > frame['size'][1]:
            raise ValueError('矩形框超出原始图像')
        if not self.lock.acquire(blocking=False):
            raise FileExistsError('SAM正在分割，请等待当前请求完成')
        attempt = editor.output / 'sam_attempts' / (time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(8))
        try:
            attempt.mkdir(parents=True, exist_ok=False)
            request = dict(frame=frame, rect=rect, points=points, labels=labels, created_utc=now(),
                           backend='SAM2.1 Hiera Tiny CPU prompted', human_confirmed=False)
            atomic_json(attempt / 'request.json', request)
            source = editor.sources(frame, verify=True)[0]
            started = time.monotonic()
            import sys
            import torch
            from PIL import Image
            sys.path.insert(0, str(self.runtime / 'sam2'))
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            installation = json.loads((self.runtime / 'sam2/checkpoints/installation.json').read_text())
            checkpoint = self.runtime / 'sam2/checkpoints/sam2.1_hiera_tiny.pt'
            if sha(checkpoint) != installation['checkpoint_sha256']:
                raise ValueError('SAM2 checkpoint SHA mismatch')
            if self.predictor is None:
                torch.set_num_threads(4)
                model = build_sam2(installation['config'], str(checkpoint), device='cpu')
                self.predictor = SAM2ImagePredictor(model, max_hole_area=0, max_sprinkle_area=0)
            with torch.inference_mode():
                if self.image_sha256 != frame['source_rgb_sha256']:
                    with Image.open(source) as image:
                        rgb = np.asarray(image.convert('RGB'))
                    self.predictor.set_image(rgb)
                    self.image_sha256 = frame['source_rgb_sha256']
                masks, scores, _ = self.predictor.predict(
                    box=np.asarray([x, y, x + width, y + height]),
                    point_coords=np.asarray(points) if points else None,
                    point_labels=np.asarray(labels) if points else None, multimask_output=False)
            if not masks[0].any():
                raise ValueError('SAM返回空Mask，请调整矩形框或提示点')
            mask = Image.fromarray(masks[0].astype(np.uint8) * 255)
            atomic_bytes(attempt / 'mask.png', mask_bytes(mask))
            result = dict(passed=True, backend=request['backend'], seconds=time.monotonic() - started,
                          source_rgb_sha256=frame['source_rgb_sha256'],
                          source_depth_sha256=frame['source_depth_sha256'],
                          request_sha256=sha(attempt / 'request.json'), mask_sha256=sha(attempt / 'mask.png'),
                          checkpoint_sha256=installation['checkpoint_sha256'],
                          sam_predicted_iou=float(scores[0]), human_confirmed=False)
            atomic_json(attempt / 'result.json', result)
            return dict(frame=frame['frame'], size=frame['size'],
                        source_rgb_sha256=frame['source_rgb_sha256'], source_depth_sha256=frame['source_depth_sha256'],
                        mask_sha256=result['mask_sha256'], backend=result['backend'], human_confirmed=False,
                        artifact=(attempt / 'mask.png').relative_to(editor.output).as_posix(),
                        request_sha256=result['request_sha256'], inference_seconds=result['seconds'])
        except Exception as error:
            if attempt.exists():
                atomic_json(attempt / 'failure.json', dict(error=str(error), human_confirmed=False))
            raise
        finally:
            self.lock.release()
