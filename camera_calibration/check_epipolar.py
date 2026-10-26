"""Compare saved correspondences with fixed epipolar geometry, without PnP.

Only reads an ended session and an existing analysis. Never fits parameters or
changes source trials. Pixel distances are consistency diagnostics, not GT.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stats(values):
    a = np.asarray(values, dtype=float)
    if not a.size or not np.isfinite(a).all():
        raise ValueError("Missing or nonfinite metric")
    return dict(n=int(a.size), mean=float(a.mean()), median=float(np.median(a)),
                p95=float(np.percentile(a, 95)), rms=float(np.sqrt(np.mean(a*a))),
                std_population=float(a.std()), minimum=float(a.min()), maximum=float(a.max()))


def model(meta):
    K = np.array([[meta['fx'], 0., meta['cx']], [0., meta['fy'], meta['cy']], [0., 0., 1.]])
    d = np.asarray(meta['coeffs'], dtype=float)
    if np.any(d) and meta['model'] != 'distortion.brown_conrady':
        raise ValueError("Unsupported nonzero distortion model: " + meta['model'])
    return K, d


def pixel_points(points, meta):
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    if not np.isfinite(p).all():
        raise ValueError("Nonfinite saved corners")
    K, d = model(meta)
    return cv2.undistortPoints(p.reshape(-1, 1, 2), K, d, P=K).reshape(-1, 2)


def fundamental(Ks, Kd, T):
    T = np.asarray(T, dtype=float)
    if T.shape != (4, 4) or not np.isfinite(T).all():
        raise ValueError("Invalid transform")
    R, t = T[:3, :3], T[:3, 3]
    if not np.allclose(R.T @ R, np.eye(3), atol=1e-3) or np.linalg.norm(t) < 1e-6:
        raise ValueError("Transform not suitable for epipolar distances")
    tx = np.array([[0., -t[2], t[1]], [t[2], 0., -t[0]], [-t[1], t[0], 0.]])
    F = np.linalg.inv(Kd).T @ tx @ R @ np.linalg.inv(Ks)
    return F / np.linalg.norm(F)


def distances(src, dst, F):
    s, d = np.column_stack([src, np.ones(len(src))]), np.column_stack([dst, np.ones(len(dst))])
    ld, ls = s @ F.T, d @ F
    residual = np.sum(d * ld, axis=1)
    nd, ns = np.linalg.norm(ld[:, :2], axis=1), np.linalg.norm(ls[:, :2], axis=1)
    if min(nd.min(), ns.min()) <= 1e-15:
        raise ValueError("Degenerate epipolar line")
    dd, ds = residual / nd, residual / ns
    return ds, dd, (np.abs(ds) + np.abs(dd)) / 2.


def summarize(rows):
    return dict(n_views=len(rows), n_points=sum(len(r['symmetric']) for r in rows),
                symmetric_mean_absolute_line_distance_px=stats(np.concatenate([r['symmetric'] for r in rows])),
                source_signed_line_distance_px=stats(np.concatenate([r['src_signed'] for r in rows])),
                destination_signed_line_distance_px=stats(np.concatenate([r['dst_signed'] for r in rows])),
                per_view_symmetric_rms_px=stats([np.sqrt(np.mean(r['symmetric']**2)) for r in rows]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    meta, analysis = read(args.input / 'factory.json'), read(args.analysis)
    if sha(args.input / 'factory.json') != analysis['source_factory_sha256']:
        raise ValueError("Factory evidence differs from existing analysis")
    if not analysis.get('analysis_completed'):
        raise ValueError("Existing analysis incomplete")
    source = args.output / 'source'
    source.mkdir()
    shutil.copy2(__file__, source / Path(__file__).name)
    accepted = []
    trial_sources, verified_files = [], 0
    for folder in sorted((args.input / 'trials').iterdir()):
        p = folder / 'trial.json'
        if not p.is_file():
            continue
        trial = read(p)
        trial_sources.append(dict(trial=folder.name, path=str(p.resolve()), sha256=sha(p), accepted=trial['accepted']))
        if not trial['accepted']:
            continue
        for item in trial['files']:
            if sha(folder / item['name']) != item['sha256']:
                raise ValueError("Source file SHA mismatch: " + str(folder / item['name']))
            verified_files += 1
        accepted.append((folder.name, trial))
    if [name for name, _ in accepted] != analysis['view_names']:
        raise ValueError("Accepted order differs from analysis split")
    train, holdout = set(analysis['split']['train']), set(analysis['split']['holdout'])
    if train & holdout or train | holdout != set(range(len(accepted))):
        raise ValueError("Incomplete/overlapping split")
    report = dict(
        input=str(args.input.resolve()), existing_analysis=str(args.analysis.resolve()),
        physical_accuracy_accepted=False, parameters_fitted=False,
        factory_sha256=sha(args.input / 'factory.json'), analysis_sha256=sha(args.analysis),
        executed_source_sha256=sha(__file__), verified_original_frame_files=verified_files,
        trial_sources=trial_sources, definitions=dict(
            correspondence='x_destination.T F x_source = 0; T maps source camera coordinates to destination camera coordinates',
            fundamental='F = inverse(K_destination).T [t]_cross R inverse(K_source), normalized by Frobenius norm',
            destination_signed_distance='(x_destination.T F x_source) / norm((F x_source)[:2])',
            source_signed_distance='(x_destination.T F x_source) / norm((F.T x_destination)[:2])',
            symmetric_distance='(abs(source_signed_distance) + abs(destination_signed_distance)) / 2; mean of two point-to-line distances in their respective pixel coordinate systems',
            ir_raw_dy='raw y_IR2 - raw y_IR1, pixels; independent of fitted board poses',
            aggregate='point-level statistics concatenate all 66 corners of each included view; per-view RMS summarized separately',
            distortion='Saved factory camera coefficients undistort points to pixels with P=K; this session all factory coefficients are zero',
            split=analysis['split']), pairs={}, ir1_to_ir2_raw_dy={}, notes=[
            'No chessboard 3D points, board spacing, plane model or PnP is used in these distance calculations.',
            'Factory K is used for both factory and existing candidate extrinsics; candidate extrinsics were fitted previously, never refitted here.',
            'The training subset is in-sample for candidate extrinsics; only its existing holdout subset is out-of-sample within this session.',
            'Epipolar distances measure 2D correspondence consistency, not absolute physical calibration error, depth accuracy or a ground truth pose.',
            'Corner localization, exposure/motion timing, image camera-model errors and saved correspondence ordering may affect residuals.',
            'Saved IR ordering previously selected only discrete board symmetry using factory geometry; this is not wholly independent correspondence establishment.',
            'Signed distances depend on the fixed F sign convention; magnitudes are used for geometric comparison.',
            'The five holdout views have limited coverage; results do not certify the entire field of view, all ranges or production projector-on depth.',
            'Candidate translation magnitude is not constrained by epipolar distances, which are invariant to nonzero uniform scaling of t.',
            'No settings, camera parameters, original files or acceptance flags were modified.'])
    per_view, per_point = [], []
    for pair, dst_name in [('ir1_to_ir2', 'ir2'), ('ir1_to_rgb', 'rgb')]:
        Ks, Kd = model(meta['intrinsics']['ir1'])[0], model(meta['intrinsics'][dst_name])[0]
        factory_T = meta['extrinsics'][pair]['T_destination_from_source']
        candidate = analysis['candidate_extrinsics'][pair]
        if not np.allclose(factory_T, candidate['factory_T_destination_from_source'], atol=1e-12):
            raise ValueError("Candidate factory provenance differs")
        report['pairs'][pair] = dict(fundamental_matrices={}, geometry={})
        for geometry, T in [('factory', factory_T), ('candidate_existing', candidate['fitted_T_destination_from_source'])]:
            F = fundamental(Ks, Kd, T)
            report['pairs'][pair]['fundamental_matrices'][geometry] = F.tolist()
            rows = []
            for index, (name, trial) in enumerate(accepted):
                key = 'rgb' if dst_name == 'rgb' else 'ir2_ordered'
                if trial['corners']['ir1_ordered'] is None or trial['corners'].get(key) is None:
                    raise ValueError("This comparison requires every saved correspondence: " + name)
                src_raw = np.asarray(trial['corners']['ir1_ordered'], dtype=float)
                dst_raw = np.asarray(trial['corners'][key], dtype=float)
                src = pixel_points(src_raw, meta['intrinsics']['ir1'])
                dst = pixel_points(dst_raw, meta['intrinsics'][dst_name])
                if src.shape != dst.shape or len(src) != meta['board']['rows'] * meta['board']['cols']:
                    raise ValueError("Corner correspondence shape mismatch")
                ds, dd, symmetric = distances(src, dst, F)
                split = 'train' if index in train else 'holdout'
                row = dict(index=index, trial=name, split=split, src_signed=ds, dst_signed=dd, symmetric=symmetric)
                rows.append(row)
                per_view.append(dict(pair=pair, geometry=geometry, trial=name, accepted_index=index, split=split,
                                     points=len(src), symmetric_mean_px=float(symmetric.mean()),
                                     symmetric_rms_px=float(np.sqrt(np.mean(symmetric**2))),
                                     symmetric_p95_px=float(np.percentile(symmetric, 95)),
                                     symmetric_max_px=float(symmetric.max()),
                                     source_signed_mean_px=float(ds.mean()), destination_signed_mean_px=float(dd.mean())))
                for i in range(len(src)):
                    per_point.append(dict(pair=pair, geometry=geometry, trial=name, accepted_index=index, split=split,
                                          corner=i, source_x_px=float(src[i, 0]), source_y_px=float(src[i, 1]),
                                          destination_x_px=float(dst[i, 0]), destination_y_px=float(dst[i, 1]),
                                          source_signed_distance_px=float(ds[i]), destination_signed_distance_px=float(dd[i]),
                                          symmetric_distance_px=float(symmetric[i])))
                if pair == 'ir1_to_ir2' and geometry == 'factory':
                    row['raw_dy'] = dst_raw[:, 1] - src_raw[:, 1]
            report['pairs'][pair]['geometry'][geometry] = {
                group: summarize(rows if group == 'all' else [r for r in rows if r['split'] == group])
                for group in ('all', 'train', 'holdout')}
            if pair == 'ir1_to_ir2' and geometry == 'factory':
                for group in ('all', 'train', 'holdout'):
                    chosen = rows if group == 'all' else [r for r in rows if r['split'] == group]
                    dy = np.concatenate([r['raw_dy'] for r in chosen])
                    report['ir1_to_ir2_raw_dy'][group] = dict(signed=stats(dy), absolute=stats(np.abs(dy)),
                        per_view_signed_mean_px=[dict(trial=r['trial'], value=float(r['raw_dy'].mean())) for r in chosen])
    for name, rows in [('per_view.csv', per_view), ('per_point.csv', per_point)]:
        with (args.output / name).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    lines = ['# Fixed-geometry epipolar consistency check', '',
             'No PnP, board plane or square-size model is used. This does not establish physical calibration accuracy.', '',
             'Symmetric distance = mean of absolute source and destination point-to-epipolar-line distances (pixels).', '',
             '|Pair|Subset|Geometry|Views|Mean(px)|RMS(px)|P95(px)|Max(px)|',
             '|---|---|---|---:|---:|---:|---:|---:|']
    compact = []
    for pair, block in report['pairs'].items():
        for group in ('all', 'train', 'holdout'):
            for geometry in ('factory', 'candidate_existing'):
                r = block['geometry'][geometry][group]
                d = r['symmetric_mean_absolute_line_distance_px']
                lines.append('|%s|%s|%s|%d|%.4f|%.4f|%.4f|%.4f|' %
                             (pair, group, geometry, r['n_views'], d['mean'], d['rms'], d['p95'], d['maximum']))
                if group == 'holdout':
                    compact.append(dict(pair=pair, geometry=geometry, views=r['n_views'], **d))
    lines += ['', '## Limits', ''] + ['- '+note for note in report['notes']]
    (args.output / 'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    outputs = [dict(name=str(p.relative_to(args.output)), sha256=sha(p))
               for p in sorted(args.output.rglob('*')) if p.is_file()]
    (args.output / 'manifest.json').write_text(json.dumps(dict(files=outputs), indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(args.output.resolve()), accepted_views=len(accepted),
                         original_frame_files_verified=verified_files, holdout=compact), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
