"""Export actual historical loss/reinitialization RGB and overlay for inspection."""
import json
from pathlib import Path
import cv2
import numpy as np

root = Path('/data/ZJC/foundationPos')
session = root / 'foundationpose_data/live_sessions/cup_fast_20261015_105319_214e4f54'
output = root / 'foundationpose_data/derived/reacquisition_actual_frames_20261015'
output.mkdir(exist_ok=False)
panels = []
for frame in ['000000', '000676', '000677', '000678', '000679', '001109', '001110']:
    folder = session / 'frames' / frame
    if not folder.exists():
        continue
    rgb = np.load(folder / 'rgb.npy', allow_pickle=False)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.putText(bgr, frame, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, .9, (0, 0, 255), 2)
    cv2.imwrite(str(output / (frame + '_rgb.jpg')), bgr)
    if (folder / 'overlay.jpg').exists():
        cv2.imwrite(str(output / (frame + '_overlay.jpg')), cv2.imread(str(folder / 'overlay.jpg')))
    panels.append(cv2.resize(bgr, (320, 240)))
cv2.imwrite(str(output / 'contact.jpg'), np.concatenate(panels, axis=1))
print(output)
