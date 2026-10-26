"""Same native image/ROI comparison; cross-model agreement is not GT IoU."""
import argparse
import json
from pathlib import Path
import shutil
import cv2
import numpy as np
from cup_sam_mask import generate_sam_mask
from cup_sam2_mask import run_sam2

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
args = p.parse_args()
root, output = args.root.resolve(), args.output.resolve()
output.relative_to(root / 'foundationpose_data')
output.mkdir(parents=True, exist_ok=False)
(output / 'worker_code').mkdir()
for name in ['cup_sam_worker.py', 'cup_sam2_worker.py']:
    shutil.copy2(root / 'setup' / name, output / 'worker_code' / name)
inputs = []
scene = root / 'foundationpose_data/windows_captures/cup_photos_20261013_204739_875'
masks = root / 'foundationpose_data/derived/cup_masks_test_204739_v2/masks'
for number in range(1, 6):
    frame = '%06d' % number
    rgb = cv2.cvtColor(cv2.imread(str(scene / 'rgb' / (frame + '.png'))), cv2.COLOR_BGR2RGB)
    mask = cv2.imread(str(masks / (frame + '.png')), 0)
    yy, xx = np.nonzero(mask)
    x, y = max(0, int(xx.min()) - 12), max(0, int(yy.min()) - 12)
    rect = [x, y, min(640, int(xx.max()) + 13) - x, min(480, int(yy.max()) + 13) - y]
    inputs.append(('heldout_' + frame, rgb, rect, str(scene / 'rgb' / (frame + '.png'))))
for frame in ['000000', '000678']:
    folder = root / 'foundationpose_data/live_sessions/cup_fast_20261015_105319_214e4f54/frames' / frame
    if folder.exists():
        inputs.append(('real_' + frame, np.load(folder / 'rgb.npy', allow_pickle=False),
                       json.loads((folder / 'capture.json').read_text())['initialization']['roi'], str(folder / 'rgb.npy')))
results = []
for name, rgb, rect, source in inputs:
    sam, old = generate_sam_mask(root, output, rgb, rect, [], [], {})
    sam2, new = run_sam2(root, output, rgb, rect, [], [], {})
    a, b = sam > 0, sam2 > 0
    panels = []
    for label, binary in [('SAM ViT-B', sam), ('SAM2.1 Tiny', sam2)]:
        vis = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        selected = binary > 0
        vis[selected] = (.6 * vis[selected] + .4 * np.array([0, 220, 255])).astype(np.uint8)
        cv2.putText(vis, label, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 255), 2)
        panels.append(vis)
    cv2.imwrite(str(output / (name + '.jpg')), np.concatenate(panels, axis=1))
    results.append(dict(name=name, source=source, same_roi=rect, sam=old, sam2=new,
                        cross_model_mask_iou=float((a & b).sum() / max(1, (a | b).sum())),
                        cross_model_agreement_is_accuracy=False))
    (output / 'report.json').write_text(json.dumps(dict(passed=True, frames=results, physical_accuracy_validated=False), indent=2) + '\n')
    print(name, old['host_seconds'], new['host_seconds'], flush=True)
