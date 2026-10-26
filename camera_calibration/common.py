"""Shared calibration math. Transforms are T_destination_from_source, meters."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_sources(output):
    source_dir = Path(output) / 'source'
    source_dir.mkdir(exist_ok=False)
    files = []
    for source in sorted(Path(__file__).parent.iterdir()):
        if source.is_file() and source.suffix in ('.py', '.json', '.sh', '.ps1', '.cmd', '.md'):
            target = source_dir / source.name
            shutil.copy2(source, target)
            files.append(dict(name=source.name, bytes=target.stat().st_size, sha256=sha(target)))
    write_json(Path(output) / 'source_manifest.json', dict(files=files))
    return files


def intrinsic(profile):
    v = profile.as_video_stream_profile().get_intrinsics()
    return dict(width=v.width, height=v.height, fx=v.fx, fy=v.fy, cx=v.ppx, cy=v.ppy,
                model=str(v.model), coeffs=list(v.coeffs))


def extrinsic(source, destination, rs):
    e = source.get_extrinsics_to(destination)
    # Preserve the exact factory coefficients; SDK rotation is column-major.
    origin = np.array(rs.rs2_transform_point_to_point(e, [0., 0., 0.]))
    R = np.array(e.rotation).reshape(3, 3, order='F')
    sdk_columns = np.column_stack([np.array(rs.rs2_transform_point_to_point(e, v)) - origin
                                   for v in ([1., 0., 0.], [0., 1., 0.], [0., 0., 1.])])
    if not np.allclose(R, sdk_columns, atol=2e-7, rtol=0):
        raise ValueError('SDK extrinsic rotation order failed basis-vector verification')
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, origin
    return dict(T_destination_from_source=T.tolist(), translation_unit='meter',
                sdk_basis_vector_check_passed=True,
                rotation_sdk_column_major=list(e.rotation), translation_sdk=list(e.translation))


def camera_model(v):
    K = np.array([[v['fx'], 0, v['cx']], [0, v['fy'], v['cy']], [0, 0, 1.]], float)
    d = np.array(v['coeffs'], float)
    if not np.any(d):
        return K, np.zeros(5)
    if v['model'] != 'distortion.brown_conrady':
        raise ValueError('Nonzero SDK distortion is not OpenCV Brown-Conrady: ' + v['model'])
    return K, d


def board_points(board):
    obj = np.zeros((board['rows'] * board['cols'], 3), np.float32)
    obj[:, :2] = np.mgrid[:board['cols'], :board['rows']].T.reshape(-1, 2)
    obj *= board['square_mm'] / 1000.
    return obj


def detect(image, board):
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    found, points = cv2.findChessboardCornersSB(gray, (board['cols'], board['rows']),
                                               cv2.CALIB_CB_NORMALIZE_IMAGE)
    return points.reshape(-1, 2).astype(np.float32) if found else None


def pose(obj, corners, K, d):
    ok, r, t = cv2.solvePnP(obj, corners, K, d, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError('Chessboard pose could not be fitted')
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = cv2.Rodrigues(r)[0], t.ravel()
    if np.min((obj @ T[:3, :3].T + T[:3, 3])[:, 2]) <= 0:
        raise ValueError('Chessboard pose is behind camera')
    return T


def project(obj, T, K, d):
    return cv2.projectPoints(obj, cv2.Rodrigues(T[:3, :3])[0], T[:3, 3], K, d)[0].reshape(-1, 2)


def rms(a, b):
    return float(np.sqrt(np.mean(np.sum((np.asarray(a) - np.asarray(b)) ** 2, axis=-1))))


def orient_corners(corners, predicted, board):
    # Only resolve the physical board's discrete 180/90-degree symmetry;
    # never fit an arbitrary pixel shift to make factory extrinsics look better.
    grid = corners.reshape(board['rows'], board['cols'], 2)
    choices = [grid.reshape(-1, 2), grid[::-1, ::-1].reshape(-1, 2)]
    if board['rows'] == board['cols']:
        choices += [np.rot90(grid, k).reshape(-1, 2) for k in (1, 3)]
    scores = [rms(p, predicted) for p in choices]
    order = np.argsort(scores)
    if scores[order[1]] - scores[order[0]] < 3.:
        raise ValueError('Ambiguous RGB/IR board orientation; use a larger, tilted board view')
    return choices[order[0]].copy(), dict(choice=int(order[0]), candidate_rms_px=scores,
                                         rule='discrete board symmetry chosen using factory geometry')


def distribution(values):
    x = np.asarray(values, float)
    x = x[np.isfinite(x)]
    if not len(x):
        return None
    return dict(n=int(len(x)), mean=float(x.mean()), median=float(np.median(x)),
                p95=float(np.percentile(x, 95)), rms=float(np.sqrt(np.mean(x*x))),
                minimum=float(x.min()), maximum=float(x.max()))


def depth_panel(rgb, depth, scale):
    valid = depth > 0
    z = depth.astype(float) * scale
    gray = np.zeros(depth.shape, np.uint8)
    if valid.any():
        lo, hi = np.percentile(z[valid], [2, 98])
        gray[valid] = np.clip((z[valid] - lo) / max(hi-lo, .001) * 255, 0, 255).astype(np.uint8)
    color = cv2.applyColorMap(gray, cv2.COLORMAP_TURBO)
    color[~valid] = 0
    overlay = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    # Physical depth boundaries, not black/white texture lines.
    edges = np.zeros(depth.shape, bool)
    edges[:, 1:] |= valid[:, 1:] & valid[:, :-1] & (np.abs(np.diff(z, axis=1)) > .02)
    edges[1:] |= valid[1:] & valid[:-1] & (np.abs(np.diff(z, axis=0)) > .02)
    overlay[edges] = (0, 255, 0)
    rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return np.hstack([rgb_bgr, color, overlay])
