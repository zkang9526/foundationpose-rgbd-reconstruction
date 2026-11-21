"""Bounded FK refinement for an IK candidate, without controller interfaces."""
import math
import time

import numpy as np

from cup_ik_search import SearchDeadlineExceeded


BOUNDARY_ROUNDOFF_RAD = 1e-6
MAX_FUNCTION_EVALUATIONS = 60


def _check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise SearchDeadlineExceeded('容差归一化逆解细化共享规划时限已到')


def _rigid_pose(value, label):
    pose = np.asarray(value, dtype=float)
    if (pose.shape != (4, 4) or not np.all(np.isfinite(pose))
            or not np.allclose(pose[3], [0., 0., 0., 1.], atol=1e-8, rtol=0.)
            or not np.allclose(pose[:3, :3].T @ pose[:3, :3],
                               np.eye(3), atol=1e-5, rtol=0.)
            or np.linalg.det(pose[:3, :3]) < .99):
        raise ValueError(label + '必须为有效刚体矩阵')
    return pose.copy()


def refine_solution(solver, target, seed, position_tolerance, rotation_tolerance, deadline):
    """Return a tolerance-checked joint vector or ``None``, with diagnostics.

    Position and rotation residuals are divided by their acceptance tolerances.
    Only at most 1e-6 rad of seed limit roundoff is clipped. The optimizer keeps
    the model limits unchanged. Two bounded attempts use position residual
    scales 1.0 then 0.5, each with at most 60 function evaluations. Every FK
    evaluation checks the caller's shared monotonic deadline first.

    This function checks numerical pose residuals and joint bounds. Its caller
    must still validate self-collision and the complete scene/path. Invalid
    inputs raise ValueError. Deadline expiration always propagates directly as
    SearchDeadlineExceeded, including expiration during optimization.
    """
    target = _rigid_pose(target, '细化目标')
    for value, name in ((position_tolerance, '位置容差'),
                        (rotation_tolerance, '旋转容差')):
        if (isinstance(value, bool) or not isinstance(value, (float, int, np.number))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(name + '必须为正有限数值')
    if (isinstance(deadline, bool) or not isinstance(deadline, (float, int, np.number))
            or not math.isfinite(deadline)):
        raise ValueError('细化必须具有有限共享规划期限')
    lower = np.asarray(solver.reduced_robot.model.lowerPositionLimit, dtype=float)
    upper = np.asarray(solver.reduced_robot.model.upperPositionLimit, dtype=float)
    seed = np.asarray(seed, dtype=float)
    if (lower.shape != (6,) or upper.shape != (6,) or seed.shape != (6,)
            or not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper))
            or not np.all(np.isfinite(seed)) or np.any(lower >= upper)):
        raise ValueError('细化初值和模型限位必须为有限六关节向量')
    if (np.any(seed < lower - BOUNDARY_ROUNDOFF_RAD)
            or np.any(seed > upper + BOUNDARY_ROUNDOFF_RAD)):
        raise ValueError('细化初值越限超过允许的数值浮差')
    clipped_seed = np.clip(seed, lower, upper)
    began = time.monotonic()
    _check_deadline(deadline)

    # Keep SciPy optional until the refinement is explicitly requested.
    from scipy.optimize import least_squares
    from scipy.spatial.transform import Rotation

    fk_evaluations = 0

    def pose_components(q):
        nonlocal fk_evaluations
        _check_deadline(deadline)
        actual = _rigid_pose(solver.forward_pose(q), '细化正运动学输出')
        fk_evaluations += 1
        translation = actual[:3, 3] - target[:3, 3]
        rotation = Rotation.from_matrix(target[:3, :3].T @ actual[:3, :3]).as_rotvec()
        return translation, rotation

    initial_translation, initial_rotation = pose_components(clipped_seed)
    diagnostics = dict(
        accepted=False,
        position_tolerance_m=float(position_tolerance),
        rotation_tolerance_rad=float(rotation_tolerance),
        initial_position_error_m=float(np.linalg.norm(initial_translation)),
        initial_rotation_error_rad=float(np.linalg.norm(initial_rotation)),
        seed_clipped_for_roundoff=bool(np.any(clipped_seed != seed)),
        max_nfev=MAX_FUNCTION_EVALUATIONS,
        max_attempts=2, attempts=[],
    )
    if (diagnostics['initial_position_error_m'] <= position_tolerance
            and diagnostics['initial_rotation_error_rad'] <= rotation_tolerance):
        diagnostics.update(
            accepted=True, reason='seed_already_within_tolerance',
            position_error_m=diagnostics['initial_position_error_m'],
            rotation_error_rad=diagnostics['initial_rotation_error_rad'],
            nfev=0, optimizer_success=True, optimizer_status=None,
            optimizer_message='Initial candidate already meets numerical tolerances.',
            fk_evaluations=fk_evaluations, elapsed_s=time.monotonic() - began)
        _check_deadline(deadline)
        return clipped_seed.copy(), diagnostics

    total_nfev = 0
    for position_scale in (1., .5):
        _check_deadline(deadline)

        def residual(q):
            translation, rotation = pose_components(q)
            return np.r_[position_scale * translation / position_tolerance,
                         rotation / rotation_tolerance]

        optimized = least_squares(
            residual, clipped_seed, bounds=(lower, upper),
            max_nfev=MAX_FUNCTION_EVALUATIONS,
            ftol=1e-9, xtol=1e-9, gtol=1e-9,
        )
        candidate = np.asarray(optimized.x, dtype=float)
        total_nfev += int(optimized.nfev)
        attempt = dict(
            position_residual_scale=position_scale, nfev=int(optimized.nfev),
            optimizer_success=bool(optimized.success), optimizer_status=int(optimized.status),
            optimizer_message=str(optimized.message))
        if (candidate.shape != (6,) or not np.all(np.isfinite(candidate))
                or np.any(candidate < lower) or np.any(candidate > upper)):
            _check_deadline(deadline)
            attempt['reason'] = 'optimizer_returned_invalid_or_out_of_bounds_joints'
            diagnostics['attempts'].append(attempt)
            diagnostics.update(attempt, nfev=total_nfev, fk_evaluations=fk_evaluations,
                               elapsed_s=time.monotonic() - began)
            return None, diagnostics

        translation, rotation = pose_components(candidate)
        position_error = float(np.linalg.norm(translation))
        rotation_error = float(np.linalg.norm(rotation))
        accepted = position_error <= position_tolerance and rotation_error <= rotation_tolerance
        attempt.update(
            accepted=accepted, reason='within_tolerance' if accepted else 'residual_exceeds_tolerance',
            position_error_m=position_error, rotation_error_rad=rotation_error,
            normalized_residual_norm=float(np.linalg.norm(
                np.r_[translation / position_tolerance, rotation / rotation_tolerance])))
        diagnostics['attempts'].append(attempt)
        if accepted:
            diagnostics.update(attempt, nfev=total_nfev, fk_evaluations=fk_evaluations,
                               elapsed_s=time.monotonic() - began)
            _check_deadline(deadline)
            return candidate.copy(), diagnostics

    best = min(diagnostics['attempts'], key=lambda attempt: max(
        attempt['position_error_m'] / position_tolerance,
        attempt['rotation_error_rad'] / rotation_tolerance))
    diagnostics.update(best, nfev=total_nfev, fk_evaluations=fk_evaluations,
                       elapsed_s=time.monotonic() - began)
    _check_deadline(deadline)
    return None, diagnostics
