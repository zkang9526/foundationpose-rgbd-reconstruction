"""ADD/ADD-S on a fixed meter-scale point set and independently supplied poses.

This module performs numerical evaluation only. It does not create ground truth
or determine whether the reference or mesh is physically accurate.
"""
import math

import numpy as np


def _real_array(value, name):
    array = np.asarray(value)
    if np.iscomplexobj(array):
        raise ValueError(name + " must be real-valued")
    try:
        array = np.asarray(array, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(name + " must be numeric") from error
    if not np.isfinite(array).all():
        raise ValueError(name + " contains nonfinite values")
    return array


def validated_transform(value, rotation_atol=1e-3):
    """Return a copy of a valid T_camera_from_model with rotation on SO(3).

    Translation and model points must use meters, as declared by the caller.
    Only small float32 rotation residuals are corrected. Reflections, scale,
    gross non-rigid matrices, and a non-homogeneous last row are rejected.
    """
    if not np.isfinite(rotation_atol) or not 0 < rotation_atol <= 1e-2:
        raise ValueError("rotation_atol must lie in (0, 0.01]")
    transform = _real_array(value, "transform")
    if transform.shape != (4, 4):
        raise ValueError("transform must be 4x4")
    if not np.allclose(transform[3], [0, 0, 0, 1], rtol=0, atol=1e-7):
        raise ValueError("transform must have homogeneous last row [0,0,0,1]")
    rotation = transform[:3, :3]
    determinant = float(np.linalg.det(rotation))
    orthogonality_error = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
    if determinant <= 0 or abs(determinant - 1) > rotation_atol or orthogonality_error > rotation_atol:
        raise ValueError("transform rotation must be a proper near-orthonormal SO(3) matrix")
    left, _, right = np.linalg.svd(rotation)
    corrected = left @ right
    if np.linalg.det(corrected) <= 0:
        raise ValueError("transform rotation is a reflection")
    result = transform.copy()
    result[:3, :3] = corrected
    result[3] = [0, 0, 0, 1]
    return result


def _points(value, name="model points"):
    points = _real_array(value, name)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points):
        raise ValueError(name + " must be a nonempty Nx3 array")
    return points


def transform_model_points(points_m, camera_from_model):
    """Apply a meter-scale object-to-camera rigid transform to row-vector points."""
    points = _points(points_m)
    transform = validated_transform(camera_from_model)
    return points @ transform[:3, :3].T + transform[:3, 3]


def add_error(points_m, estimated, reference):
    """Mean corresponding model-point distance, in meters (ADD)."""
    points = _points(points_m)
    est = validated_transform(estimated)
    ref = validated_transform(reference)
    delta = points @ (est[:3, :3] - ref[:3, :3]).T + (est[:3, 3] - ref[:3, 3])
    return float(np.linalg.norm(delta, axis=1).mean())


def adds_error(points_m, estimated, reference):
    """One-way nearest-neighbor distance, in meters (ADD-S / BOP ADI).

    Direction matches bop_toolkit.pose_error.adi: each reference-transformed
    point queries its nearest neighbor among estimated-transformed points.
    The metric is not a symmetric Chamfer distance and can understate errors
    for nearly symmetric shapes.
    """
    from scipy.spatial import cKDTree

    points = _points(points_m)
    est = validated_transform(estimated)
    ref = validated_transform(reference)
    estimated_points = points @ est[:3, :3].T + est[:3, 3]
    reference_points = points @ ref[:3, :3].T + ref[:3, 3]
    distances, _ = cKDTree(estimated_points).query(reference_points, k=1)
    return float(np.asarray(distances, dtype=np.float64).mean())


def pose_error_mm_deg(estimated, reference):
    """Object-origin translation norm in mm and SO(3) geodesic angle in degrees."""
    est = validated_transform(estimated)
    ref = validated_transform(reference)
    difference = est[:3, :3] @ ref[:3, :3].T
    cosine = float(np.clip((np.trace(difference) - 1) / 2, -1, 1))
    return {
        "translation_error_mm": float(np.linalg.norm(est[:3, 3] - ref[:3, 3]) * 1000),
        "rotation_error_deg": float(math.degrees(math.acos(cosine))),
    }


def stats_mm(values_m):
    """Describe nonnegative finite errors supplied in meters; output is mm.

    Empty input returns None. Invalid values are rejected, never silently
    dropped; missing/rejected frames and coverage belong in the caller report.
    """
    values = _real_array(values_m, "errors").reshape(-1)
    if not len(values):
        return None
    if np.any(values < 0):
        raise ValueError("errors must be nonnegative")
    mm = values * 1000
    if not np.isfinite(mm).all():
        raise ValueError("errors overflow after conversion to millimeters")
    return {
        "count": int(len(mm)),
        "mean": float(np.mean(mm)),
        "median": float(np.median(mm)),
        "p95": float(np.percentile(mm, 95)),
        "rmse": float(np.linalg.norm(mm) / math.sqrt(len(mm))),
        "max": float(np.max(mm)),
    }


def sample_mesh_surface(vertices_m, faces, count=10000, seed=0):
    """Return a reproducible area-uniform Nx3 sample of a triangle surface.

    Zero-area faces receive no samples. This fixes evaluation point density
    independently of vertex tessellation. Keep the resulting point set and SHA
    fixed across methods; it is an area-sampled ADD protocol, rather than an
    implicit claim to reproduce a benchmark's original vertex set.
    """
    vertices = _points(vertices_m, "vertices")
    indices = np.asarray(faces)
    if indices.ndim != 2 or indices.shape[1] != 3 or not len(indices):
        raise ValueError("faces must be a nonempty Mx3 array")
    if not np.issubdtype(indices.dtype, np.integer):
        raise ValueError("face indices must be integers")
    if np.any(indices < 0) or np.any(indices >= len(vertices)):
        raise ValueError("face indices are outside the vertex array")
    if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or count <= 0:
        raise ValueError("count must be a positive integer")
    triangles = vertices[indices.astype(np.int64)]
    areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1
    ) * 0.5
    if not np.isfinite(areas).all():
        raise ValueError("triangle areas are nonfinite")
    good = areas > 0
    if not good.any():
        raise ValueError("mesh has no positive-area triangles")
    triangles = triangles[good]
    areas = areas[good]
    total = float(areas.sum())
    if not np.isfinite(total) or total <= 0:
        raise ValueError("mesh total surface area is invalid")
    generator = np.random.default_rng(seed)
    selected = triangles[generator.choice(len(triangles), size=int(count), p=areas / total)]
    root = np.sqrt(generator.random(int(count)))
    second = generator.random(int(count))
    return (
        selected[:, 0] * (1 - root)[:, None]
        + selected[:, 1] * (root * (1 - second))[:, None]
        + selected[:, 2] * (root * second)[:, None]
    )
