#!/usr/bin/env python3
"""Read-only handle RGB/mask/raw-depth diagnostics on sparse reviewed surface ROIs.

ROIs are samples of visible handle material, not independent full-handle GT.
Never change annotations, camera parameters, depth, or reconstruction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--masks', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    # Hand-picked on the original RGB, before inspecting sample depth values.
    samples = [(0, [246, 373, 255, 392]), (18, [347, 385, 357, 411]),
               (36, [423, 310, 432, 332])]
    rows, provenance = [], []
    panels = Image.new('RGB', (1290, len(samples) * 450), 'white')
    draw = ImageDraw.Draw(panels)
    for row, (number, box) in enumerate(samples):
        name = '%06d.png' % number
        files = [args.scene/'rgb'/name, args.scene/'depth'/name, args.masks/'masks'/name]
        rgb = cv2.cvtColor(cv2.imread(str(files[0])), cv2.COLOR_BGR2RGB)
        depth = cv2.imread(str(files[1]), cv2.IMREAD_UNCHANGED)
        mask = cv2.imread(str(files[2]), 0) > 0
        if rgb.shape != (480, 640, 3) or depth.shape != (480, 640) or depth.dtype != np.uint16:
            raise ValueError('Expected original 640x480 RGB and uint16 millimeter depth')
        x0,y0,x1,y1 = box
        region = np.zeros(depth.shape, bool); region[y0:y1,x0:x1] = True
        sampled_depth = depth[region]
        stats = dict(frame=name, sample_roi_xyxy=box, sample_pixels=int(region.sum()),
            mask_included_fraction=float(mask[region].mean()),
            raw_nonzero_depth_fraction=float((sampled_depth>0).mean()),
            reconstruction_range_350_520mm_fraction=float(((sampled_depth>=350)&(sampled_depth<=520)).mean()),
            raw_zero_depth_fraction=float((sampled_depth==0).mean()),
            raw_farther_than_520mm_fraction=float((sampled_depth>520).mean()),
            nonzero_depth_median_mm=float(np.median(sampled_depth[sampled_depth>0])) if np.any(sampled_depth>0) else None)
        rows.append(stats)
        original = rgb.copy()
        cv2.rectangle(original, (x0,y0), (x1-1,y1-1), (255,255,0), 1)
        contour = rgb.copy()
        contours,_ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(contour, contours, -1, (255,255,0), 1)
        status = rgb.copy()
        status[mask&(depth==0)] = (70,70,255)
        status[mask&(depth>0)&((depth<350)|(depth>520))] = (255,70,70)
        cv2.drawContours(status, contours, -1, (255,255,0), 1)
        for column, image in enumerate((original, contour, status)):
            crop = Image.fromarray(image).crop((235,250,450,450)).resize((430,400))
            panels.paste(crop, (column*430,row*450+35))
        draw.text((5,row*450+4), '%s | yellow box: visible handle sample' % name, fill='black')
        draw.text((435,row*450+4), 'Yellow: reviewed mask contours', fill='black')
        draw.text((865,row*450+4), 'Blue: depth=0 | red: outside 350-520mm', fill='black')
        draw.text((5,row*450+436), 'Sample mask %.1f%% | raw depth %.1f%% | retained %.1f%% (not full-handle GT)' %
                  (100*stats['mask_included_fraction'],100*stats['raw_nonzero_depth_fraction'],
                   100*stats['reconstruction_range_350_520mm_fraction']), fill='black')
        provenance.extend(dict(path=str(path),sha256=sha(path)) for path in files)
    image_path = args.output/'handle_mask_depth_samples.png'
    panels.save(image_path)
    report = dict(scope='Sparse manually selected visible-handle surface sample diagnostics; not full-handle segmentation or depth accuracy GT',
        samples=rows, source_files=provenance, source_files_unchanged=all(sha(Path(x['path']))==x['sha256'] for x in provenance),
        source_depth_unit='millimeters from saved depth_scale metadata; current reconstruction range reported for comparison',
        image=dict(path=str(image_path),sha256=sha(image_path)),
        limitations=['Samples do not represent every handle view or its full area',
                     'Nonzero depth can contain occlusion/background returns and does not prove accurate range',
                     'Missing surfaces and registration errors cannot be resolved by enlarging a mask alone'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(samples=rows,output=str(args.output),source_files_unchanged=report['source_files_unchanged'])))


if __name__=='__main__':main()
