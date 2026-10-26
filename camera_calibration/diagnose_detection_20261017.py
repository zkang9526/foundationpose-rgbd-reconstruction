"""Offline checkerboard detection diagnostics; never changes capture acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cv2.setNumThreads(1)
    records = []
    panels = []
    for number in ('0001', '0002', '0003'):
        trial = args.session / 'trials' / number
        source = json.loads((trial / 'trial.json').read_text(encoding='utf-8'))
        row = []
        for stream in ('rgb', 'ir1', 'ir2'):
            path = trial / (stream + '.npy')
            raw = np.load(path, allow_pickle=False)
            gray = cv2.cvtColor(raw, cv2.COLOR_RGB2GRAY) if raw.ndim == 3 else raw
            cases = [
                ('sb_original', gray, (6, 11), 'sb'),
                ('classic_original', gray, (6, 11), 'classic'),
                ('sb_gaussian5', cv2.GaussianBlur(gray, (5, 5), 1.2), (6, 11), 'sb'),
                ('sb_gaussian9', cv2.GaussianBlur(gray, (9, 9), 2.0), (6, 11), 'sb'),
                ('classic_gaussian9', cv2.GaussianBlur(gray, (9, 9), 2.0), (6, 11), 'classic'),
                ('sb_transposed_original', gray, (11, 6), 'sb'),
            ]
            results = []
            drawn = cv2.cvtColor(raw, cv2.COLOR_RGB2BGR) if raw.ndim == 3 else cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
            displayed = False
            for name, image, pattern, detector in cases:
                started = time.perf_counter()
                if detector == 'sb':
                    found, corners = cv2.findChessboardCornersSB(image, pattern, cv2.CALIB_CB_NORMALIZE_IMAGE)
                else:
                    found, corners = cv2.findChessboardCorners(image, pattern, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
                    if found:
                        corners = cv2.cornerSubPix(image, corners, (5, 5), (-1, -1), (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, 0.001))
                item = dict(name=name, found=bool(found), pattern=list(pattern), seconds=time.perf_counter()-started)
                if found:
                    pts = corners.reshape(-1, 2)
                    item['corners'] = pts.tolist()
                    item['bounds_px'] = [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()]
                    if not displayed:
                        cv2.drawChessboardCorners(drawn, pattern, corners, True)
                        cv2.putText(drawn, name, (8, 48), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 255), 2)
                        displayed = True
                results.append(item)
                print(json.dumps(dict(trial=number, stream=stream, detector=name, found=bool(found), seconds=round(item['seconds'], 3))), flush=True)
            cv2.putText(drawn, number + ' ' + stream + ' DIAGNOSTIC', (8, 24), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 255, 255), 2)
            cv2.imwrite(str(args.output / (number + '_' + stream + '_diagnostic.png')), drawn)
            row.append(drawn)
            records.append(dict(trial=number, stream=stream, source_npy=str(path), sha256=sha(path), recorded_accepted=source['accepted'], recorded_corner_count=None if source['corners'][stream] is None else len(source['corners'][stream]), gray_percentiles=np.percentile(gray, [0, 1, 50, 99, 100]).tolist(), fraction_saturated_255=float(np.mean(gray==255)), results=results))
        panels.append(np.concatenate(row, axis=1))
    cv2.imwrite(str(args.output / 'diagnostic_contact_sheet.jpg'), np.concatenate(panels, axis=0), [cv2.IMWRITE_JPEG_QUALITY, 92])
    report = dict(scope='offline_diagnostics_only_not_calibration_acceptance', opencv=cv2.__version__, source_script_sha256=sha(__file__), original_acceptance_changed=False, user_conditions='7x12 squares, 6x11 inner corners, square edge 20 mm; user reports 5 horizontal and vertical squares measured 100 mm', records=records)
    (args.output / 'detection_diagnostics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(args.output), report='detection_diagnostics.json')), flush=True)


if __name__ == '__main__':
    main()
