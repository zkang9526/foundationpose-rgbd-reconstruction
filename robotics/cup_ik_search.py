"""Bounded, deterministic IK seed search using numerical solver methods only.

The caller supplies one shared monotonic deadline and a collision/path-boundary
check for each candidate. This module opens no ROS, CAN or camera interfaces.
"""
import math
import time

import numpy as np


class SearchDeadlineExceeded(RuntimeError):
    """The shared planning deadline expired; the caller must stop this search."""


def _integer_option(config, name, default, minimum, maximum):
    value = config.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not minimum <= value <= maximum:
        raise ValueError('{}必须为{}至{}的整数'.format(name, minimum, maximum))
    return int(value)


def _positive_option(config, name, default):
    value = config.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (float, int, np.number)) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + '必须为正有限数值')
    return float(value)


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise SearchDeadlineExceeded('多初值逆解共享规划时限已到，停止本轮搜索')


def _seed_vectors(reference, lower, upper, count, random_seed):
    """Reference first, then neutral, wrist alternatives and fixed random seeds."""
    seeds = []

    def append(value):
        value = np.asarray(value, dtype=float)
        if not any(np.max(np.abs(value - previous)) < 1e-8 for previous in seeds):
            seeds.append(value.copy())

    append(reference)
    append(np.clip(np.zeros(6), lower, upper))
    append((lower + upper) / 2.)
    for joint in (3, 4, 5):
        for sign in (-1., 1.):
            changed = reference.copy()
            changed[joint] += sign * math.pi
            append(np.clip(changed, lower, upper))
    random = np.random.default_rng(random_seed)
    while len(seeds) < count:
        append(random.uniform(lower, upper))
    return seeds[:count]


def _pose_errors(actual, desired):
    actual = np.asarray(actual, dtype=float)
    if (actual.shape != (4, 4) or not np.all(np.isfinite(actual))
            or not np.allclose(actual[3], [0., 0., 0., 1.], atol=1e-8)
            or not np.allclose(actual[:3, :3].T @ actual[:3, :3], np.eye(3), atol=1e-5)
            or np.linalg.det(actual[:3, :3]) < .99):
        raise ValueError('逆解正运动学返回无效矩阵')
    translation = float(np.linalg.norm(actual[:3, 3] - desired[:3, 3]))
    cosine = float(np.clip((np.trace(actual[:3, :3].T @ desired[:3, :3]) - 1.) / 2., -1., 1.))
    return translation, math.acos(cosine)


def search_solutions(solver, target, reference, opening, config, deadline, check_solution):
    """Return ``(solutions, diagnostics)`` after checking deterministic IK seeds.

    ``reference`` is the actual path start or preceding accepted waypoint. It
    remains the continuity reference for every seed. Returned solutions are
    distinct, bounded six-joint vectors that pass FK residual, self-collision,
    and ``check_solution(q, target)`` checks. The callback should raise
    ``ValueError`` or ``RuntimeError`` for candidate rejections and propagate
    infrastructure failures through another exception type. Shared deadline
    expiration always raises ``SearchDeadlineExceeded`` and is never retried.

    Options are search_ik_seeds (1..32, default12), search_ik_solutions
    (1..3, default3), search_seed (0..2**32-1, default117), and the existing
    solution_position_tolerance_m / solution_rotation_tolerance_rad fields.
    """
    target = np.asarray(target, dtype=float)
    reference = np.asarray(reference, dtype=float)
    if (target.shape != (4, 4) or not np.all(np.isfinite(target))
            or not np.allclose(target[3], [0., 0., 0., 1.], atol=1e-8)
            or not np.allclose(target[:3, :3].T @ target[:3, :3], np.eye(3), atol=1e-5)
            or np.linalg.det(target[:3, :3]) < .99):
        raise ValueError('多初值逆解收到无效目标矩阵')
    lower = np.asarray(solver.reduced_robot.model.lowerPositionLimit, dtype=float)
    upper = np.asarray(solver.reduced_robot.model.upperPositionLimit, dtype=float)
    if (reference.shape != (6,) or lower.shape != (6,) or upper.shape != (6,)
            or not np.all(np.isfinite(reference)) or not np.all(np.isfinite(lower))
            or not np.all(np.isfinite(upper)) or np.any(lower >= upper)
            or np.any(reference < lower - 1e-6) or np.any(reference > upper + 1e-6)):
        raise ValueError('多初值逆解参考关节或模型限位无效')
    if isinstance(opening, bool) or not np.isfinite(opening) or opening <= 0:
        raise ValueError('多初值逆解夹爪几何开口必须为正有限值')
    if isinstance(deadline, bool) or not isinstance(deadline, (float, int)) or not math.isfinite(deadline):
        raise ValueError('多初值逆解必须具有有限共享规划期限')
    count = _integer_option(config, 'search_ik_seeds', 12, 1, 32)
    maximum = _integer_option(config, 'search_ik_solutions', 3, 1, 3)
    random_seed = _integer_option(config, 'search_seed', 117, 0, 2**32 - 1)
    refinement_enabled = config.get('search_ik_tolerance_refinement_enabled', False)
    if not isinstance(refinement_enabled, bool):
        raise ValueError('search_ik_tolerance_refinement_enabled必须为布尔值')
    position_limit = _positive_option(config, 'solution_position_tolerance_m', .002)
    rotation_limit = _positive_option(config, 'solution_rotation_tolerance_rad', .02)
    seeds = _seed_vectors(reference, lower, upper, count, random_seed)
    solutions, trials = [], []
    began = time.monotonic()
    for index, seed in enumerate(seeds):
        _deadline(deadline)
        trial = dict(index=index, seed=seed.tolist(), accepted=False)
        trials.append(trial)
        solver.history_data = seed.copy()
        try:
            candidate, _, accepted = solver.ik_fun(target.copy(), gripper=float(opening),
                motorstate=seed.copy(), reference_configuration=reference.copy())
            _deadline(deadline)
            if candidate is None:
                trial['reason'] = 'solver_returned_no_solution'
                continue
            candidate = np.asarray(candidate, dtype=float)
            if candidate.shape != (6,) or not np.all(np.isfinite(candidate)):
                trial['reason'] = 'invalid_joint_vector'
                continue
            trial['joints_rad'] = candidate.tolist()
            if np.any(candidate < lower - 1e-6) or np.any(candidate > upper + 1e-6):
                trial['reason'] = 'joint_limits'
                continue
            position, rotation = _pose_errors(solver.forward_pose(candidate), target)
            trial.update(position_error_m=position, rotation_error_rad=rotation)
            if position > position_limit or rotation > rotation_limit:
                trial['reason'] = 'solution_residual'
                continue
            if not accepted:
                trial['reason'] = 'solver_rejected_or_self_collision'
                continue
            if solver.check_self_collision(candidate, np.array([opening / 2., -opening / 2.])):
                trial['reason'] = 'self_collision'
                continue
            check_solution(candidate.copy(), target.copy())
            _deadline(deadline)
            if any(np.max(np.abs(candidate - previous)) < 1e-4 for previous in solutions):
                trial['reason'] = 'duplicate_solution'
                continue
            solutions.append(candidate.copy())
            trial.update(accepted=True, reason='checked')
            if len(solutions) >= maximum:
                break
        except SearchDeadlineExceeded:
            raise
        except (ValueError, RuntimeError) as error:
            _deadline(deadline)
            trial['reason'] = type(error).__name__ + ': ' + str(error)
    if not solutions and refinement_enabled:
        from cup_ik_refinement import refine_solution
        approximate = sorted(
            (trial for trial in trials if trial.get('reason') == 'solution_residual'),
            key=lambda trial: ((trial['position_error_m'] / position_limit) ** 2
                               + (trial['rotation_error_rad'] / rotation_limit) ** 2))
        refined_seeds = []
        for previous in approximate:
            seed = np.asarray(previous['joints_rad'], dtype=float)
            if any(np.max(np.abs(seed - used)) < 1e-4 for used in refined_seeds):
                continue
            if len(refined_seeds) >= 3:
                break
            refined_seeds.append(seed)
            _deadline(deadline)
            trial = dict(index=len(trials), seed=seed.tolist(), accepted=False,
                         kind='tolerance_normalized_refinement', parent_seed=previous['index'])
            trials.append(trial)
            try:
                candidate, detail = refine_solution(solver, target, seed, position_limit,
                                                    rotation_limit, deadline)
                trial['refinement'] = detail
                if candidate is None:
                    trial['reason'] = 'refinement_residual'
                    continue
                candidate = np.asarray(candidate, dtype=float)
                if (candidate.shape != (6,) or not np.all(np.isfinite(candidate))
                        or np.any(candidate < lower - 1e-6) or np.any(candidate > upper + 1e-6)):
                    trial['reason'] = 'invalid_refined_joint_vector'
                    continue
                position, rotation = _pose_errors(solver.forward_pose(candidate), target)
                trial.update(joints_rad=candidate.tolist(), position_error_m=position,
                             rotation_error_rad=rotation)
                if position > position_limit or rotation > rotation_limit:
                    trial['reason'] = 'refinement_residual'
                    continue
                if solver.check_self_collision(candidate, np.array([opening / 2., -opening / 2.])):
                    trial['reason'] = 'self_collision'
                    continue
                check_solution(candidate.copy(), target.copy())
                _deadline(deadline)
                if any(np.max(np.abs(candidate - previous)) < 1e-4 for previous in solutions):
                    trial['reason'] = 'duplicate_solution'
                    continue
                solutions.append(candidate.copy())
                trial.update(accepted=True, reason='checked')
                if len(solutions) >= maximum:
                    break
            except SearchDeadlineExceeded:
                raise
            except (ValueError, RuntimeError) as error:
                _deadline(deadline)
                trial['reason'] = type(error).__name__ + ': ' + str(error)
    finite = [trial for trial in trials if 'position_error_m' in trial]
    best = min(finite, key=lambda trial: (trial['position_error_m'], trial['rotation_error_rad']), default=None)
    diagnostics = dict(seed_budget=count, attempted_seeds=len(trials), solutions=len(solutions),
                       elapsed_s=time.monotonic() - began, trials=trials,
                       best_position_error_m=None if best is None else best['position_error_m'],
                       best_rotation_error_rad=None if best is None else best['rotation_error_rad'])
    return solutions, diagnostics
