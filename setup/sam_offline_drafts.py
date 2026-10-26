"""Batch official SAM drafts in the existing GPU container; never human labels."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
from contextlib import nullcontext


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_head(git_dir):
    """Read clone HEAD without invoking Git ownership/configuration machinery."""
    head = (git_dir / 'HEAD').read_text().strip()
    if head.startswith('ref: '):
        ref = head[5:]
        if not ref.startswith('refs/') or '..' in Path(ref).parts:
            raise ValueError('Unexpected source reference')
        loose = git_dir / ref
        if loose.exists():
            head = loose.read_text().strip()
        else:
            head = next(line.split()[0] for line in (git_dir/'packed-refs').read_text().splitlines()
                        if line and not line.startswith(('#','^')) and line.split()[1] == ref)
    if len(head) != 40 or any(c not in '0123456789abcdef' for c in head):
        raise ValueError('Unexpected source commit')
    return head


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--indices', type=int, nargs='*')
    args = parser.parse_args()
    job = args.job.resolve(strict=True)
    data = Path('/data') if Path('/data/tools/segment-anything').is_dir() else Path('/data/ZJC/foundationPos/foundationpose_data')
    job.relative_to(data / 'offline_masks')
    output = args.output.resolve()
    output.relative_to(job)
    output.mkdir(exist_ok=False)
    (output / 'masks').mkdir()
    started = time.monotonic()
    report = dict(passed=False, draft_only=True, human_confirmed=False,
                  masks_are_pose_ground_truth=False, backend='official SAM ViT-B', frames=[], failures=[])
    try:
        import cv2
        import numpy as np
        import torch
        request = json.loads((job / 'request.json').read_text())
        backend = request.get('backend', 'sam')
        source = data / 'tools' / ('sam2' if backend == 'sam2' else 'segment-anything')
        install = json.loads((data / 'checkpoints' / backend / 'installation.json').read_text())
        checkpoint = data / 'checkpoints' / backend / ('sam2.1_hiera_tiny.pt' if backend == 'sam2' else 'sam_vit_b_01ec64.pth')
        commit = source_head(source / '.git')
        if sha(checkpoint) != install['checkpoint_sha256'] or commit != install['commit']:
            raise ValueError('Official source/checkpoint differs from retained installation')
        sys.path.insert(0, str(source))
        if backend == 'sam2':
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            model = build_sam2(install['config'], str(checkpoint), device='cuda')
            predictor = SAM2ImagePredictor(model, max_hole_area=0, max_sprinkle_area=0)
            report['backend'] = 'official SAM2.1 Hiera Tiny'
        else:
            from segment_anything import SamPredictor, sam_model_registry
            model = sam_model_registry['vit_b'](checkpoint=str(checkpoint)).to('cuda').eval()
            predictor = SamPredictor(model)
        report.update(installation=install, source_commit=commit, request_sha256=sha(job / 'request.json'),
                      gpu=torch.cuda.get_device_name(), torch=torch.__version__, prompts=request['prompts'])
        frames = request['frames'] if args.indices is None else [request['frames'][i] for i in args.indices]
        for count, frame in enumerate(frames):
            try:
                source = job / 'rgb' / frame['frame']
                if sha(source) != frame['source_rgb_sha256']:
                    raise ValueError('Source RGB SHA differs')
                image = cv2.imread(str(source))
                if image is None or image.shape != (480, 640, 3):
                    raise ValueError('Expected native 640x480 RGB')
                prompts = request['prompts']
                begin = time.monotonic()
                precision = torch.autocast('cuda',dtype=torch.bfloat16) if backend == 'sam2' else nullcontext()
                with torch.inference_mode(), precision:
                    predictor.set_image(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                    masks, scores, _ = predictor.predict(
                        box=np.asarray(prompts['box_xyxy'], np.float32),
                        point_coords=np.asarray(prompts['points'], np.float32),
                        point_labels=np.asarray(prompts['labels'], np.int32), multimask_output=False)
                torch.cuda.synchronize()
                mask = masks[0].astype(np.uint8) * 255
                if not mask.any():
                    raise ValueError('Empty SAM proposal')
                path = output / 'masks' / frame['frame']
                if not cv2.imwrite(str(path), mask):
                    raise RuntimeError('Mask PNG write failed')
                report['frames'].append(dict(frame, mask_file='masks/' + frame['frame'], mask_sha256=sha(path),
                    predicted_iou=float(scores[0]), predicted_iou_is_measured_accuracy=False,
                    foreground_pixels=int(np.count_nonzero(mask)), inference_seconds=time.monotonic()-begin,
                    prompt_agreement=[bool(masks[0,y,x]) == bool(v) for (x,y),v in zip(prompts['points'],prompts['labels'])]))
            except Exception as error:
                report['failures'].append(dict(frame=frame['frame'], error=str(error)))
                traceback.print_exc()
            if count == 0 or (count+1) % 10 == 0 or count+1 == len(frames):
                print(json.dumps(dict(processed=count+1, requested=len(frames), failures=len(report['failures']))), flush=True)
        report['passed'] = len(report['frames']) == len(frames) and not report['failures']
    except Exception as error:
        report['error'] = str(error)
        traceback.print_exc()
    report['seconds'] = time.monotonic() - started
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:report[k] for k in ('passed','draft_only','human_confirmed','seconds')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
