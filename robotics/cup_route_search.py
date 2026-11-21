"""Bounded full-route search with radial grasps, multiple IK seeds and preparation paths."""

import math
import time

import numpy as np

from cup_ik_search import search_solutions, SearchDeadlineExceeded
from joint_motion import quintic_samples, resample_limited_samples, retime_samples


def perpendicular_direction(tcp, center, config):
    from cup_approach_route import ApproachRouteRejected

    axis, direction = center[:3, 2], tcp[:3, 2]
    if abs(float(direction @ axis)) > 1e-6 or abs(float(tcp[:3, 1] @ axis)) > 1e-6:
        raise ApproachRouteRejected('完整搜索要求夹爪接近轴及闭合轴垂直杯轴')
    if direction[2] > 0.15 + 1e-8:
        raise ApproachRouteRejected('完整搜索拒绝明显从下方接近')

    reference = center[:3, 3].copy()
    vertical = abs(float(axis[2])) >= math.cos(math.radians(20.0))
    if (
        vertical
        or config.get('pregrasp_height_correction_scope', 'vertical_only') == 'all_postures'
    ):
        reference[2] += float(config.get('pregrasp_height_correction_m', 0.0))
    expected = reference - float(config['pregrasp_distance_m']) * direction
    if np.linalg.norm(tcp[:3, 3] - expected) > 1e-6:
        raise ApproachRouteRejected('完整搜索预抓取点与配置退距/高度补偿不一致')
    return direction.copy()


def plan_search_pregrasp(solver, start, target, center, config):
    """Keep bounded search diagnostics available on both success and rejection."""
    from cup_approach_route import ApproachRouteRejected

    began = time.monotonic()
    statistics = dict(ik_calls=0, seed_attempts=0, path_attempts=[], endpoint_checks=[])
    try:
        return _search_pregrasp(solver, start, target, center, config, statistics)
    except (ApproachRouteRejected, SearchDeadlineExceeded) as error:
        error.search_statistics = statistics
        raise
    finally:
        statistics['elapsed_s'] = time.monotonic() - began


def _search_pregrasp(solver, start, target, center, config, stats):
    from cup_approach_route import rigid, pose_error, CupCollisionProxy, ApproachRouteRejected

    if config.get('pregrasp_search_enabled', False) is not True:
        raise ApproachRouteRejected('未启用完整正交预抓取搜索')
    maximum_solutions = config.get('search_ik_solutions', 3)
    if (
        isinstance(maximum_solutions, bool)
        or not isinstance(maximum_solutions, int)
        or not 1 <= maximum_solutions <= 3
    ):
        raise ApproachRouteRejected('search_ik_solutions必须为1至3的整数')

    target, center, tool = rigid(target), rigid(center), rigid(config['T_ee_tcp'])
    direction = perpendicular_direction(target @ tool, center, config)
    start = np.asarray(start, dtype=float)
    lower, upper = (
        solver.reduced_robot.model.lowerPositionLimit,
        solver.reduced_robot.model.upperPositionLimit,
    )
    if (
        start.shape != (6,)
        or not np.all(np.isfinite(start))
        or np.any(start < lower)
        or np.any(start > upper)
    ):
        raise ApproachRouteRejected('搜索起点关节无效')

    began = time.monotonic()
    budget = float(config.get('pregrasp_search_route_budget_s', 8.0))
    if not math.isfinite(budget) or not 1.0 <= budget <= 30.0:
        raise ApproachRouteRejected('每候选搜索时限必须为1至30秒')
    deadline = began + min(
        budget, float(config.get('pregrasp_route_planning_timeout_s', 30.0))
    )
    opening = float(config['pregrasp_measured_opening_m'])
    collision = CupCollisionProxy(solver, center, config)
    position_limit = float(config.get('solution_position_tolerance_m', 0.002))
    rotation_limit = float(config.get('solution_rotation_tolerance_rad', 0.02))
    workspace_min = np.asarray(config['workspace_min_m'])
    workspace_max = np.asarray(config['workspace_max_m'])
    errors = [0.0, 0.0]

    def check(q, desired=None):
        if time.monotonic() >= deadline:
            raise SearchDeadlineExceeded('完整正交路径搜索时限已到')
        if np.any(q < lower - 1e-6) or np.any(q > upper + 1e-6):
            raise ApproachRouteRejected('搜索关节越限')

        actual = solver.forward_pose(q)
        if desired is not None:
            pe, re = pose_error(actual, desired)
            if pe > position_limit or re > rotation_limit:
                raise ApproachRouteRejected(
                    '搜索目标残差超限{:.2f}mm/{:.4f}rad'.format(pe * 1000, re)
                )
            errors[0] = max(errors[0], pe)
            errors[1] = max(errors[1], re)

        if np.any(actual[:3, 3] < workspace_min) or np.any(actual[:3, 3] > workspace_max):
            raise ApproachRouteRejected('搜索路径超出工作空间')
        if solver.check_self_collision(q, np.array([opening / 2.0, -opening / 2.0])):
            raise ApproachRouteRejected('搜索路径自碰撞')
        collision.check(q)
        return actual

    def solve_many(desired, reference, maximum, endpoint=False):
        solutions, detail = search_solutions(
            solver,
            desired,
            reference,
            opening,
            dict(config, search_ik_solutions=maximum),
            deadline,
            check,
        )
        stats['ik_calls'] += 1
        stats['seed_attempts'] += detail['attempted_seeds']
        if not solutions or endpoint:
            stats['endpoint_checks'].append(dict(target=desired.tolist(), **detail))
        return solutions

    def preparation_solutions(desired):
        first = solve_many(desired, start, 1, endpoint=True)
        yield from first
        # Resume seed expansion only when the first complete path was rejected.
        if first and maximum_solutions > 1:
            for alternative in solve_many(desired, start, maximum_solutions, endpoint=True):
                if not any(
                    np.max(np.abs(alternative - previous)) < 1e-4 for previous in first
                ):
                    yield alternative

    check(start)
    final_solutions = solve_many(target, start, 1, endpoint=True)
    if not final_solutions:
        detail = stats['endpoint_checks'][-1]
        best = detail['best_position_error_m']
        reason = '无返回解' if best is None else '最佳残差{:.1f}mm'.format(best * 1000)
        raise ApproachRouteRejected('最终预抓取目标多初值逆解未通过，' + reason)

    tcp = target @ tool
    preferred = float(config.get('pregrasp_staging_distance_m', 0.10))
    standoff = float(config['pregrasp_distance_m'])
    distances = []
    for value in (preferred, standoff + 0.020, standoff + 0.002, preferred + 0.04):
        if standoff < value <= 0.35 and not any(abs(value - x) < 1e-6 for x in distances):
            distances.append(value)

    speed = float(config.get('joint_velocity_rad_s', 0.25))
    accel = float(config.get('joint_acceleration_rad_s2', 0.5))
    rate = float(config.get('rate_hz', 50.0))
    output_rate = float(config.get('pregrasp_output_rate_hz', rate))
    cart_speed = float(config.get('pregrasp_side_speed_m_s', 0.02))
    if not (
        0 < speed
        and 0 < accel
        and 10 <= rate <= 100
        and 10 <= output_rate <= 100
        and 0.005 <= cart_speed <= 0.05
    ):
        raise ApproachRouteRejected('完整搜索运动参数无效')

    max_step = float(config.get('max_joint_step_rad', 0.35))
    inverse_tool = np.linalg.inv(tool)
    offsets = ((0.0, 0.0), (0.04, 0.0), (0.08, 0.0), (0.04, 0.06), (0.04, -0.06))
    for distance in distances:
        low_tcp = tcp.copy()
        low_tcp[:3, 3] -= (distance - standoff) * direction
        low = low_tcp @ inverse_tool
        for height, lateral in offsets:
            high_tcp = low_tcp.copy()
            high_tcp[2, 3] += height
            high_tcp[:3, 3] += lateral * tcp[:3, 1]
            high = high_tcp @ inverse_tool
            for high_q in preparation_solutions(high):
                attempt = dict(
                    staging_distance_m=distance,
                    height_m=height,
                    lateral_m=lateral,
                    passed=False,
                )
                stats['path_attempts'].append(attempt)
                try:
                    times, positions, _ = quintic_samples(start, high_q, speed, rate, accel)
                    times, positions, timing = resample_limited_samples(
                        times, positions, speed, accel, output_rate
                    )
                    for q in positions:
                        check(q)
                    phases = [
                        dict(
                            name='align_outside_cup',
                            first=0,
                            last=len(positions) - 1,
                            timing=timing,
                        )
                    ]
                    all_times = list(times)
                    all_q = list(positions)
                    previous = high_q.copy()
                    phase_start = high
                    for name, end in (
                        ('prepare_radial_line', low),
                        ('perpendicular_approach', target),
                    ):
                        length = float(np.linalg.norm(end[:3, 3] - phase_start[:3, 3]))
                        if length < 1e-9:
                            continue

                        duration = max(1.875 * length / cart_speed, 0.1)
                        count = max(1, int(math.ceil(duration * rate)))
                        qs = [previous.copy()]
                        for i in range(1, count + 1):
                            s = i / count
                            alpha = s**3 * (10.0 + s * (-15.0 + 6.0 * s))
                            desired = end.copy()
                            desired[:3, 3] = phase_start[:3, 3] + alpha * (
                                end[:3, 3] - phase_start[:3, 3]
                            )
                            options = solve_many(desired, previous, 1)
                            if not options:
                                raise ApproachRouteRejected(name + '多初值逆解失败')
                            q = options[0]
                            if np.max(np.abs(q - previous)) > max_step:
                                raise ApproachRouteRejected('完整搜索路径关节跳变')
                            qs.append(q.copy())
                            previous = q

                        phase_t, phase_q, timing = resample_limited_samples(
                            np.linspace(0.0, duration, count + 1),
                            qs,
                            speed,
                            accel,
                            output_rate,
                        )
                        first = len(all_q) - 1
                        offset = all_times[-1]
                        for stamp, q in zip(phase_t[1:], phase_q[1:]):
                            s = float(stamp / phase_t[-1])
                            alpha = s**3 * (10.0 + s * (-15.0 + 6.0 * s))
                            desired = end.copy()
                            desired[:3, 3] = phase_start[:3, 3] + alpha * (
                                end[:3, 3] - phase_start[:3, 3]
                            )
                            check(q, desired)

                        all_times.extend(offset + phase_t[1:])
                        all_q.extend(phase_q[1:])
                        phases.append(
                            dict(name=name, first=first, last=len(all_q) - 1, timing=timing)
                        )
                        phase_start = end

                    _, limits = retime_samples(all_times, all_q, speed, accel)
                    if (
                        limits['time_scale'] > 1.0 + 1e-8
                        or np.max(np.abs(np.diff(all_q, axis=0))) > max_step
                        or np.max(np.diff(all_times)) >= 0.2
                    ):
                        raise ApproachRouteRejected('完整搜索轨迹拼接速度/加速度或步长超限')

                    attempt['passed'] = True
                    margins = np.min(
                        np.minimum(np.asarray(all_q) - lower, upper - np.asarray(all_q)),
                        axis=0,
                    )
                    summary = dict(
                        route_mode='perpendicular',
                        samples=len(all_q),
                        duration_s=float(all_times[-1]),
                        output_rate_hz=output_rate,
                        planning_rate_hz=rate,
                        planning_elapsed_s=time.monotonic() - began,
                        staging_distance_m=distance,
                        preferred_staging_distance_m=preferred,
                        final_standoff_m=standoff,
                        preparation_height_m=height,
                        preparation_lateral_m=lateral,
                        phases=phases,
                        max_position_error_m=errors[0],
                        max_rotation_error_rad=errors[1],
                        translation_approach_axis_base=direction.tolist(),
                        joint_limit_margin_min_deg=np.degrees(margins).tolist(),
                        search_statistics=stats,
                        scene_table_obstacles_checked=False,
                        collision_model='URDF robot vs inflated cup cylinder and handle box',
                        **limits,
                    )
                    return all_times, np.asarray(all_q), summary
                except SearchDeadlineExceeded:
                    raise
                except (RuntimeError, ValueError) as error:
                    attempt['reason'] = str(error)

    raise ApproachRouteRejected(
        '多初值与杯外准备路径组合均未通过，尝试完整路径{}组，逆解初值{}次'.format(
            len(stats['path_attempts']), stats['seed_attempts']
        )
    )
