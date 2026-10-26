"""Offline SB versus classic/subpixel IR correspondence diagnostics.

Never changes source images, original acceptance, calibration or pixel positions.
Only exact discrete 180-degree lattice ordering is allowed for comparison.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def stats(values):
    a = np.asarray(values, dtype=float).ravel()
    if not a.size or not np.isfinite(a).all():
        raise ValueError('Missing or nonfinite metric')
    return dict(n=int(a.size), mean=float(a.mean()), median=float(np.median(a)),
                p95=float(np.percentile(a, 95)), rms=float(np.sqrt(np.mean(a*a))),
                std_population=float(a.std()), minimum=float(a.min()), maximum=float(a.max()))


def orient(points, target, rows, cols):
    grid = np.asarray(points, np.float32).reshape(rows, cols, 2)
    variants = [grid.reshape(-1, 2), grid[::-1, ::-1].reshape(-1, 2)]
    rms = [float(np.sqrt(np.mean(np.sum((v-target)**2, axis=1)))) for v in variants]
    chosen = int(np.argmin(rms))
    if abs(rms[0]-rms[1]) < 3.:
        raise ValueError('Ambiguous discrete orientation')
    return variants[chosen].copy(), dict(choice=chosen, candidate_rms_px=rms,
                                        operation='identity or full grid order reversal; no coordinate shift or fit')


def deltas(points, target):
    delta = np.asarray(points)-np.asarray(target)
    return dict(dx_px=stats(delta[:, 0]), dy_px=stats(delta[:, 1]),
                euclidean_px=stats(np.linalg.norm(delta, axis=1)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--analysis', type=Path, required=True)
    p.add_argument('--epipolar', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'source').mkdir()
    shutil.copy2(__file__, args.output/'source'/Path(__file__).name)
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)
    factory = read(args.input/'factory.json')
    analysis, previous = read(args.analysis), read(args.epipolar)
    if sha(args.input/'factory.json') != analysis['source_factory_sha256'] or sha(args.input/'factory.json') != previous['factory_sha256']:
        raise ValueError('Factory provenance mismatch')
    if sha(args.analysis) != previous['analysis_sha256']:
        raise ValueError('Analysis provenance mismatch')
    provenance = {x['trial']: x for x in previous['trial_sources']}
    accepted = []
    rows, cols = factory['board']['rows'], factory['board']['cols']
    spacing = factory['board']['square_mm']/1000.
    board_center = np.array([(cols-1)*spacing/2., (rows-1)*spacing/2., 0.])
    for index, name in enumerate(analysis['view_names']):
        folder = args.input/'trials'/name
        trial = read(folder/'trial.json')
        if not trial['accepted'] or sha(folder/'trial.json') != provenance[name]['sha256']:
            raise ValueError('Trial acceptance/provenance mismatch: '+name)
        T = np.asarray(trial['factory_T_rgb_from_board'], float)
        center = T[:3, :3]@board_center + T[:3, 3]
        n = T[:3, 2]
        tilt = float(np.degrees(np.arccos(np.clip(abs(n[2]), 0., 1.))))
        accepted.append(dict(name=name, index=index, trial=trial,
                             estimated_board_center_z_m=float(center[2]), normal_tilt_deg=tilt,
                             split='holdout' if index in analysis['split']['holdout'] else 'train'))
    selections = []
    def select(item, reason):
        for existing in selections:
            if existing['name'] == item['name']:
                existing['selection_reasons'].append(reason)
                return
        selections.append(dict(item, selection_reasons=[reason]))
    select(accepted[0], 'earliest accepted view')
    select(accepted[-1], 'latest accepted view; inspect far-range end of capture')
    remaining = [v for v in accepted if v['name'] not in {s['name'] for s in selections}]
    select(min(remaining, key=lambda v:v['estimated_board_center_z_m']), 'smallest factory-pose estimated board-center Z after reserving first/last views')
    held = [v for v in accepted if v['split']=='holdout' and v['name'] not in {s['name'] for s in selections}]
    select(min(held, key=lambda v:abs(v['index']-(len(accepted)-1)/2.)), 'chronologically central remaining existing holdout view')
    held = [v for v in held if v['name'] not in {s['name'] for s in selections}]
    select(max(held, key=lambda v:v['normal_tilt_deg']), 'largest factory-pose normal tilt among remaining existing holdout views')
    if len(selections) != 5:
        raise ValueError('Selection rules did not produce five distinct views; do not silently substitute')
    selections.sort(key=lambda v:v['index'])
    report = dict(scope='offline_corner_detector_consistency_only_not_physical_calibration_acceptance',
                  input=str(args.input.resolve()), opencv=cv2.__version__, opencl_enabled=False,
                  source_script_sha256=sha(__file__), factory_sha256=sha(args.input/'factory.json'),
                  analysis_sha256=sha(args.analysis), epipolar_sha256=sha(args.epipolar),
                  all_accepted_trial_jsons_verified=len(accepted), source_files_verified=[],
                  selection_rule='five predefined coverage rules based only on chronology, existing holdout indices, factory-pose center Z and normal tilt; no corner residual selected',
                  selected=[], notes=[
                      'Existing board poses are used only to select near/far/tilted coverage; they are estimates, not measured ground truth.',
                      'SB re-execution: findChessboardCornersSB with CALIB_CB_NORMALIZE_IMAGE on unmodified uint8 native IR images.',
                      'Classic: findChessboardCorners with ADAPTIVE_THRESH|NORMALIZE_IMAGE, then cornerSubPix on the same original grayscale, window 5x5, no zero zone, max 50 iterations and epsilon 0.001.',
                      'All raw NPY and PNG source values are checked for exact equality; all trial files in the five selected views are SHA verified.',
                      'Detector ordering can only be identity or 180-degree reversal; aligning order to saved SB points does not fit or shift coordinates.',
                      'Both algorithms use OpenCV and the same optical images; agreement weakens a detector-specific explanation but is not independent physical ground truth.',
                      'No board pose, intrinsics, extrinsics, distortion, epipolar geometry or vertical translation is fitted here.',
                      'Original frames, accepted flags, factory parameters and devices remain unchanged.',
                      'No natural edge-matching step is included: perspective-dependent edge pairing would add unnecessary assumptions for this minimal cross-detector check.'])
    per_point, aggregate = [], {det:[] for det in ('saved_sb', 'rerun_sb', 'classic_subpix')}
    contact_rows = []
    for selection in selections:
        name, trial = selection['name'], selection['trial']
        folder = args.input/'trials'/name
        for item in trial['files']:
            path = folder/item['name']
            if sha(path) != item['sha256']:
                raise ValueError('Source SHA mismatch '+str(path))
            report['source_files_verified'].append(dict(trial=name, name=item['name'], sha256=item['sha256']))
        result = {k:selection[k] for k in ('name','index','selection_reasons','split','estimated_board_center_z_m','normal_tilt_deg')}
        result.update(streams={}, stereo_dy={})
        detectors, panels = {}, []
        for stream in ('ir1','ir2'):
            raw = np.load(folder/(stream+'.npy'), allow_pickle=False)
            png = cv2.imread(str(folder/(stream+'.png')), cv2.IMREAD_UNCHANGED)
            if raw.dtype != np.uint8 or raw.shape != (480,640) or not np.array_equal(raw,png):
                raise ValueError('Original IR input mismatch: '+name+' '+stream)
            target = np.asarray(trial['corners'][stream+'_ordered'], np.float32)
            t0 = time.perf_counter()
            sb_ok, sb = cv2.findChessboardCornersSB(raw, (cols,rows), cv2.CALIB_CB_NORMALIZE_IMAGE)
            classic_ok, classic = cv2.findChessboardCorners(raw, (cols,rows), cv2.CALIB_CB_ADAPTIVE_THRESH|cv2.CALIB_CB_NORMALIZE_IMAGE)
            if not sb_ok or not classic_ok:
                raise ValueError('Full lattice not detected: '+name+' '+stream+' sb='+str(sb_ok)+' classic='+str(classic_ok))
            classic = cv2.cornerSubPix(raw, classic, (5,5), (-1,-1), (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,50,0.001))
            sb, sb_order = orient(sb,target,rows,cols)
            classic, classic_order = orient(classic,target,rows,cols)
            detectors[stream] = dict(saved_sb=target, rerun_sb=sb, classic_subpix=classic)
            result['streams'][stream] = dict(seconds=time.perf_counter()-t0, original_npy_png_exact_equal=True,
                rerun_sb_order=sb_order, classic_order=classic_order,
                rerun_sb_minus_saved=deltas(sb,target), classic_minus_saved=deltas(classic,target),
                classic_minus_rerun_sb=deltas(classic,sb))
            canvas = cv2.cvtColor(raw,cv2.COLOR_GRAY2BGR)
            for point in target:
                cv2.circle(canvas, tuple(np.rint(point).astype(int)),3,(0,0,255),1)
            for point in classic:
                cv2.drawMarker(canvas, tuple(np.rint(point).astype(int)),(0,255,0),cv2.MARKER_CROSS,5,1)
            cv2.putText(canvas,name+' '+stream+' red=SB green=classic',(8,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,255,255),1)
            panels.append(canvas)
        for det in aggregate:
            dy = detectors['ir2'][det][:,1]-detectors['ir1'][det][:,1]
            aggregate[det].append(dy)
            result['stereo_dy'][det] = dict(signed=stats(dy),absolute=stats(np.abs(dy)))
        for i in range(rows*cols):
            row = dict(trial=name,split=selection['split'],corner=i)
            for stream in ('ir1','ir2'):
                for det in aggregate:
                    xy = detectors[stream][det][i]
                    row[stream+'_'+det+'_x_px'],row[stream+'_'+det+'_y_px'] = map(float,xy)
                delta = detectors[stream]['classic_subpix'][i]-detectors[stream]['saved_sb'][i]
                row[stream+'_classic_minus_saved_dx_px'],row[stream+'_classic_minus_saved_dy_px'] = map(float,delta)
            for det in aggregate:
                row[det+'_stereo_dy_px'] = float(detectors['ir2'][det][i,1]-detectors['ir1'][det][i,1])
            per_point.append(row)
        contact_rows.append(np.hstack(panels))
        report['selected'].append(result)
        print(json.dumps(dict(trial=name, split=selection['split'], center_z_m=selection['estimated_board_center_z_m'], tilt_deg=selection['normal_tilt_deg'], stereo_dy={k:v['signed']['mean'] for k,v in result['stereo_dy'].items()})),flush=True)
    report['aggregate_stereo_dy'] = {det:dict(signed=stats(np.concatenate(v)),absolute=stats(np.abs(np.concatenate(v)))) for det,v in aggregate.items()}
    report['aggregate_localization_classic_minus_saved_sb'] = {
        stream:deltas(np.array([[r[stream+'_classic_subpix_x_px'],r[stream+'_classic_subpix_y_px']] for r in per_point]),
                      np.array([[r[stream+'_saved_sb_x_px'],r[stream+'_saved_sb_y_px']] for r in per_point]))
        for stream in ('ir1','ir2')}
    report['original_data_modified'] = False
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (args.output/'per_point.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(per_point[0]))
        writer.writeheader(); writer.writerows(per_point)
    cv2.imwrite(str(args.output/'detector_contact_sheet.jpg'),np.vstack(contact_rows),[cv2.IMWRITE_JPEG_QUALITY,94])
    lines=['# Offline IR corner-detector consistency','',
           'Five coverage-selected views; no acceptance, camera or calibration changes. Signed dy = IR2 y − IR1 y.','',
           '|Trial|Subset|Selection|Estimated center Z(m)|Normal tilt(deg)|SB mean dy(px)|Classic mean dy(px)|Classic median dy(px)|',
           '|---|---|---|---:|---:|---:|---:|---:|']
    for v in report['selected']:
        lines.append('|%s|%s|%s|%.4f|%.2f|%.4f|%.4f|%.4f|'%(v['name'],v['split'],'; '.join(v['selection_reasons']),v['estimated_board_center_z_m'],v['normal_tilt_deg'],v['stereo_dy']['saved_sb']['signed']['mean'],v['stereo_dy']['classic_subpix']['signed']['mean'],v['stereo_dy']['classic_subpix']['signed']['median']))
    lines += ['','## Aggregate signed dy','', '|Detector|N|Mean(px)|Median(px)|RMS(px)|P95(px)|','|---|---:|---:|---:|---:|---:|']
    for det,v in report['aggregate_stereo_dy'].items():
        s=v['signed'];lines.append('|%s|%d|%.4f|%.4f|%.4f|%.4f|'%(det,s['n'],s['mean'],s['median'],s['rms'],s['p95']))
    lines += ['','## Classic localization minus saved SB','', '|IR stream|Mean dx(px)|Mean dy(px)|2D RMS(px)|2D median(px)|2D P95(px)|','|---|---:|---:|---:|---:|---:|']
    for stream,v in report['aggregate_localization_classic_minus_saved_sb'].items():
        lines.append('|%s|%.4f|%.4f|%.4f|%.4f|%.4f|'%(stream,v['dx_px']['mean'],v['dy_px']['mean'],v['euclidean_px']['rms'],v['euclidean_px']['median'],v['euclidean_px']['p95']))
    lines += ['','## Scope and limits','']+['- '+note for note in report['notes']]
    (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    outputs=[dict(name=str(x.relative_to(args.output)),sha256=sha(x)) for x in sorted(args.output.rglob('*')) if x.is_file()]
    (args.output/'manifest.json').write_text(json.dumps(dict(files=outputs),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(args.output.resolve()),aggregate_stereo_dy=report['aggregate_stereo_dy'])),flush=True)
    return 0


if __name__=='__main__':
    sys.exit(main())
