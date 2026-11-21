"""Plan an outer alignment, outer descent and horizontal pregrasp approach."""
import math
import time
import numpy as np
from joint_motion import quintic_samples, retime_samples, resample_limited_samples


class ApproachRouteRejected(RuntimeError):
    pass


def rigid(value):
    pose = np.asarray(value, dtype=float)
    if (pose.shape != (4, 4) or not np.all(np.isfinite(pose))
            or not np.allclose(pose[3], [0., 0., 0., 1.])
            or not np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), atol=1e-5)
            or np.linalg.det(pose[:3, :3]) < .99):
        raise ApproachRouteRejected('接近路径收到无效的刚体矩阵')
    return pose.copy()


def pose_error(actual, target):
    position = float(np.linalg.norm(actual[:3, 3]-target[:3, 3]))
    angle = math.acos(float(np.clip((np.trace(actual[:3, :3].T @ target[:3, :3])-1.)/2., -1., 1.)))
    return position, angle


def pitch_limit_degrees(config):
    value = config.get('pregrasp_max_pitch_deg', 0.)
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value) or not 0. <= value <= 10.:
        raise ValueError('pregrasp_max_pitch_deg必须为0至10度的有限数值')
    return float(value)


def horizontal_approach_direction(tcp, config):
    """Separate the horizontal translation direction from bounded wrist pitch."""
    direction = np.asarray(tcp[:3, 2], dtype=float).copy()
    allowed_vertical = max(.02, math.sin(math.radians(pitch_limit_degrees(config))))
    if abs(float(direction[2])) > allowed_vertical+1e-10:
        raise ApproachRouteRejected('水平侧向接近的末端俯仰超出配置范围')
    direction[2] = 0.
    return direction/np.linalg.norm(direction)


def route_approach_direction(tcp, center, config):
    mode = config.get('pregrasp_route_mode', 'horizontal')
    if mode == 'horizontal':
        return horizontal_approach_direction(tcp, config)
    if mode != 'lying_upper' or config.get('pregrasp_lying_upper_enabled', False) is not True:
        raise ApproachRouteRejected('未启用或无效的横躺上方接近模式')
    axis = center[:3, 2]
    direction = tcp[:3, 2]
    slope = math.degrees(math.asin(float(np.clip(-direction[2], -1., 1.))))
    if abs(float(axis[2])) > math.sin(math.radians(20.))+1e-8:
        raise ApproachRouteRejected('上方接近只用于接近水平的杯轴')
    if not 5.-1e-8 <= slope <= 75.+1e-8:
        raise ApproachRouteRejected('横躺接近方向超出5至75度向下倾角')
    if abs(float(direction @ axis)) > 1e-6:
        raise ApproachRouteRejected('横躺夹爪接近轴必须垂直杯轴')
    if abs(float(tcp[:3, 1] @ axis)) > 1e-6:
        raise ApproachRouteRejected('横躺夹爪闭合轴必须垂直杯轴')
    offset = center[:3, 3]-tcp[:3, 3]
    distance = float(offset @ direction)
    if abs(distance-float(config['pregrasp_distance_m'])) > 1e-6 or np.linalg.norm(offset-distance*direction) > 1e-6:
        raise ApproachRouteRejected('横躺预抓取必须沿工具接近轴退出配置距离')
    radial = np.linalg.norm(offset-axis*float(offset @ axis))
    if radial <= float(config.get('pregrasp_collision_body_diameter_m', config['pregrasp_body_diameter_m']))/2.+float(config.get('pregrasp_cup_collision_margin_m', .003)):
        raise ApproachRouteRejected('横躺预抓取点位于杯身碰撞包络内')
    return direction.copy()


class CupCollisionProxy:
    """Inflated body cylinder and handle box checked against every URDF collision mesh."""
    def __init__(self, solver, center, config):
        import hppfcl
        self.fcl = hppfcl
        self.solver = solver
        margin = float(config.get('pregrasp_cup_collision_margin_m', .003))
        radius = float(config.get('pregrasp_collision_body_diameter_m', config['pregrasp_body_diameter_m']))/2.
        height = float(config.get('pregrasp_body_height_m', .096375))
        if not (0 <= margin <= .02 and 0 < radius < .2 and 0 < height < .5):
            raise ApproachRouteRejected('杯子碰撞代理尺寸无效')
        self.objects = [(hppfcl.Cylinder(radius+margin, height+2.*margin),
                         hppfcl.Transform3f(center[:3, :3], center[:3, 3]))]
        handle = np.asarray(config['pregrasp_handle_axis_mesh'], dtype=float)
        handle /= np.linalg.norm(handle)
        axis = np.array([0., 0., 1.])
        handle_rotation = np.column_stack((handle, np.cross(axis, handle), axis))
        bounds = np.asarray(config.get('pregrasp_handle_bounds_m', [[.042, -.015, -.04], [.080, .015, .04]]))
        if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)) or np.any(bounds[1] <= bounds[0]):
            raise ApproachRouteRejected('杯把碰撞代理尺寸无效')
        handle_center = center[:3, 3] + center[:3, :3] @ handle_rotation @ bounds.mean(axis=0)
        self.objects.append((hppfcl.Box(*(bounds[1]-bounds[0]+2.*margin)),
                             hppfcl.Transform3f(center[:3, :3] @ handle_rotation, handle_center)))
        self.request = hppfcl.CollisionRequest()
        self.opening = float(config['pregrasp_measured_opening_m'])

    def check(self, q):
        # The gripper is held open. Its geometric width comes from the user's95mm measurement.
        # This value is used only in FK/collision checks and is never a driver command.
        import pinocchio as pin
        full_q = np.r_[q, self.opening/2., -self.opening/2.]
        pin.forwardKinematics(self.solver.robot.model, self.solver.robot.data, full_q)
        pin.updateGeometryPlacements(self.solver.robot.model, self.solver.robot.data,
                                     self.solver.geom_model, self.solver.geometry_data)
        for mesh, placement in zip(self.solver.geom_model.geometryObjects, self.solver.geometry_data.oMg):
            transform = self.fcl.Transform3f(placement.rotation, placement.translation)
            for shape, pose in self.objects:
                result = self.fcl.CollisionResult()
                if self.fcl.collide(mesh.geometry, transform, shape, pose, self.request, result):
                    raise ApproachRouteRejected('路径会接触杯子碰撞代理，部件' + mesh.name)


def plan_horizontal_pregrasp(solver, start, target, center, config):
    """Return the entire checked trajectory before any movement occurs."""
    if config.get('pregrasp_route_mode') == 'perpendicular':
        from cup_route_search import plan_search_pregrasp
        from cup_ik_search import SearchDeadlineExceeded
        try:
            return plan_search_pregrasp(solver, start, target, center, config)
        except SearchDeadlineExceeded as error:
            rejected = ApproachRouteRejected(str(error))
            rejected.search_statistics = getattr(error, 'search_statistics', None)
            raise rejected from error
    target, center = rigid(target), rigid(center)
    tool = rigid(config['T_ee_tcp'])
    tcp = target @ tool
    preferred = float(config.get('pregrasp_staging_distance_m', .10))
    timeout = float(config.get('pregrasp_route_planning_timeout_s', 30.))
    if not np.isfinite(preferred) or not .10 <= preferred <= .35 or not np.isfinite(timeout) or timeout <= 0:
        raise ApproachRouteRejected('杯外准备距离或路径规划时限无效')
    direction = route_approach_direction(tcp, center, config)
    final_distance = float((center[:3, 3]-tcp[:3, 3]) @ direction)
    distances = [preferred]
    if final_distance > 0:
        # Some low horizontal goals are reachable while a farther, equally low
        # staging point exceeds the wrist limit. Check closer staging points
        # with the same full trajectory/collision checks before returning a plan.
        for extra in (.020, .002):
            distance = final_distance+extra
            if .03 <= distance < distances[-1]-1e-6:
                distances.append(distance)
    began = time.monotonic()
    deadline = began+timeout
    attempts = []
    for distance in distances:
        trial = dict(config, pregrasp_staging_distance_m=distance)
        try:
            times, positions, summary = _plan_at_staging_distance(solver, start, target, center, trial, deadline)
        except ApproachRouteRejected as error:
            reason = str(error)
            attempts.append(dict(staging_distance_m=distance, passed=False, reason=reason))
            if not reason.startswith(('align_outside_cup逆解残差超限', 'descend_outside_cup逆解残差超限')):
                raise
        else:
            attempts.append(dict(staging_distance_m=distance, passed=True))
            summary.update(staging_distance_m=distance, preferred_staging_distance_m=preferred,
                           final_standoff_m=final_distance, staging_attempts=attempts,
                           planning_elapsed_s=time.monotonic()-began)
            return times, positions, summary
    reasons = ['准备距离{:.1f}mm {}'.format(item['staging_distance_m']*1000., item['reason']) for item in attempts]
    raise ApproachRouteRejected('杯外准备点均未通过逆解检查。'+'；'.join(reasons))


def _plan_at_staging_distance(solver, start, target, center, config, deadline):
    """Check one complete route against the shared planning deadline."""
    target, center = rigid(target), rigid(center)
    start = np.asarray(start, dtype=float)
    lower, upper = solver.reduced_robot.model.lowerPositionLimit, solver.reduced_robot.model.upperPositionLimit
    if start.shape != (6,) or not np.all(np.isfinite(start)) or np.any(start < lower) or np.any(start > upper):
        raise ApproachRouteRejected('接近路径起点关节无效')
    tool = rigid(config['T_ee_tcp'])
    target_tcp = target @ tool
    direction = route_approach_direction(target_tcp, center, config)
    rate = float(config.get('rate_hz', 50.))
    output_rate = float(config.get('pregrasp_output_rate_hz', rate))
    speed = float(config.get('joint_velocity_rad_s', .25))
    acceleration = float(config.get('joint_acceleration_rad_s2', .5))
    cart_speed = float(config.get('pregrasp_side_speed_m_s', .02))
    retreat = float(config.get('pregrasp_staging_distance_m', .10))
    position_tolerance = float(config.get('solution_position_tolerance_m', .002))
    rotation_tolerance = float(config.get('solution_rotation_tolerance_rad', .02))
    if not (10 <= rate <= 100 and 10 <= output_rate <= 100 and speed > 0 and acceleration > 0 and .005 <= cart_speed <= .05 and .03 <= retreat <= .35):
        raise ApproachRouteRejected('水平接近路径速度或外侧准备距离无效')
    began = time.monotonic()
    workspace_min = np.asarray(config['workspace_min_m'])
    workspace_max = np.asarray(config['workspace_max_m'])
    collision = CupCollisionProxy(solver, center, config)
    opening = config['pregrasp_measured_opening_m']
    maxima = [0., 0.]
    phase_name = 'align_outside_cup'

    def check(q, desired=None):
        if time.monotonic() > deadline:
            raise ApproachRouteRejected('完整分段接近路径规划超时')
        if np.any(q < lower-1e-6) or np.any(q > upper+1e-6):
            raise ApproachRouteRejected('分段接近路径关节越限')
        actual = solver.forward_pose(q)
        if desired is not None:
            pe, re = pose_error(actual, desired)
            maxima[0], maxima[1] = max(maxima[0], pe), max(maxima[1], re)
            if pe > position_tolerance or re > rotation_tolerance:
                reason = '{}逆解残差超限{:.1f}mm/{:.4f}rad'.format(phase_name, pe*1000., re)
                margins = np.minimum(q-lower, upper-q)
                joint = int(np.argmin(margins))
                if margins[joint] < .01:
                    bound = '下限' if q[joint]-lower[joint] <= upper[joint]-q[joint] else '上限'
                    reason += '，关节{}接近{}，余量{:.4f}rad'.format(joint+1, bound, margins[joint])
                raise ApproachRouteRejected(reason)
        if np.any(actual[:3, 3] < workspace_min) or np.any(actual[:3, 3] > workspace_max):
            raise ApproachRouteRejected('分段接近路径超出末端工作空间')
        if solver.check_self_collision(q, np.array([opening/2., -opening/2.])):
            raise ApproachRouteRejected('分段接近路径自碰撞')
        collision.check(q)
        return actual

    def solve(desired, seed):
        solver.history_data = seed.copy()
        q, _, accepted = solver.ik_fun(desired, gripper=opening, motorstate=seed,
                                       reference_configuration=seed)
        if not accepted or q is None:
            raise ApproachRouteRejected(phase_name+'逆解失败或自碰撞')
        q = np.asarray(q, dtype=float)
        check(q, desired)
        return q

    start_pose = check(start)
    start_tcp = start_pose @ tool
    final_height = float(target_tcp[2, 3])
    staging_low_tcp = target_tcp.copy()
    staging_low_tcp[:3, 3] = center[:3, 3]-retreat*direction
    upper_route = config.get('pregrasp_route_mode', 'horizontal') == 'lying_upper'
    if not upper_route:
        staging_low_tcp[2, 3] = final_height
    staging_high_tcp = staging_low_tcp.copy()
    # Keep alignment outside the cup while avoiding a high horizontal wrist pose
    # that this arm cannot reach from the folded observation configuration.
    if not upper_route:
        staging_high_tcp[2, 3] = max(final_height, min(float(start_tcp[2, 3]), final_height+.04))
    high, low = staging_high_tcp @ np.linalg.inv(tool), staging_low_tcp @ np.linalg.inv(tool)

    high_q = solve(high, start)
    times, positions, _ = quintic_samples(start, high_q, speed, rate, acceleration)
    times, positions, timing = resample_limited_samples(times, positions, speed, acceleration, output_rate)
    for q in positions:
        check(q)
    phases = [dict(name='align_outside_cup', first=0, last=len(positions)-1,
                   target_tcp=staging_high_tcp.tolist(), timing=timing)]
    all_times, all_positions = times.tolist(), list(positions)
    previous = high_q.copy()
    phase_start = high.copy()
    approach_phase = 'upper_oblique_approach' if upper_route else 'horizontal_side_approach'
    for name, desired_end in [('descend_outside_cup', low), (approach_phase, target)]:
        phase_name = name
        distance = float(np.linalg.norm(desired_end[:3, 3]-phase_start[:3, 3]))
        duration = max(1.875*distance/cart_speed, .1)
        steps = max(1, int(np.ceil(duration*rate)))
        first = len(all_positions)-1
        offset = all_times[-1]
        phase_positions = [previous.copy()]
        for index in range(1, steps+1):
            fraction = index/steps
            alpha = fraction**3*(10.+fraction*(-15.+6.*fraction))
            desired = desired_end.copy()
            desired[:3, 3] = phase_start[:3, 3]+alpha*(desired_end[:3, 3]-phase_start[:3, 3])
            q = solve(desired, previous)
            if np.max(np.abs(q-previous)) > float(config.get('max_joint_step_rad', .35)):
                raise ApproachRouteRejected('分段接近路径相邻关节跳变')
            if name == 'horizontal_side_approach':
                tcp = solver.forward_pose(q) @ tool
                if abs(float(tcp[2, 3])-final_height) > position_tolerance:
                    raise ApproachRouteRejected('最后侧向接近段未保持同高')
            phase_positions.append(q.copy())
            previous = q
        phase_times, phase_positions, timing = resample_limited_samples(
            np.linspace(0., duration, steps+1), phase_positions, speed, acceleration, output_rate)
        for stamp, q in zip(phase_times[1:], phase_positions[1:]):
            fraction = float(stamp/phase_times[-1])
            alpha = fraction**3*(10.+fraction*(-15.+6.*fraction))
            desired = desired_end.copy()
            desired[:3, 3] = phase_start[:3, 3]+alpha*(desired_end[:3, 3]-phase_start[:3, 3])
            check(q, desired)
            if name == 'horizontal_side_approach' and abs(float((solver.forward_pose(q) @ tool)[2, 3])-final_height) > position_tolerance:
                raise ApproachRouteRejected('最后侧向接近段重采样后未保持同高')
        all_positions.extend(phase_positions[1:])
        all_times.extend(offset+phase_times[1:])
        phases.append(dict(name=name, first=first, last=len(all_positions)-1,
                           target_tcp=(desired_end @ tool).tolist(), timing=timing))
        phase_start = desired_end
    _, limits = retime_samples(all_times, all_positions, speed, acceleration)
    if limits['time_scale'] > 1.+1e-8:
        raise ApproachRouteRejected('分段轨迹衔接后速度或加速度超限')
    if np.max(np.abs(np.diff(all_positions, axis=0))) > float(config.get('max_joint_step_rad', .35)):
        raise ApproachRouteRejected('均匀发送轨迹相邻关节跳变')
    if np.max(np.diff(all_times)) >= .2:
        raise ApproachRouteRejected('分段接近路径限速后周期过长')
    joint_margin = np.min(np.minimum(np.asarray(all_positions)-lower, upper-np.asarray(all_positions)), axis=0)
    summary = dict(phases=phases, samples=len(all_positions), duration_s=float(all_times[-1]),
                   planning_elapsed_s=time.monotonic()-began,
                   max_position_error_m=maxima[0], max_rotation_error_rad=maxima[1],
                   final_side_height_m=final_height,
                   collision_model='all URDF collision meshes vs inflated cup cylinder and handle box',
                   gripper_geometry_width_m=opening, scene_table_obstacles_checked=False,
                   wrist_pitch_deg=math.degrees(math.asin(float(np.clip(-target_tcp[2, 2], -1., 1.)))),
                   translation_approach_axis_base=direction.tolist(),
                   joint_limit_margin_min_deg=np.degrees(joint_margin).tolist(),
                   route_mode=config.get('pregrasp_route_mode', 'horizontal'),
                   output_rate_hz=output_rate, planning_rate_hz=rate,
                   time_parameterization='independent phase limits and uniform output grid', **limits)
    return all_times, np.asarray(all_positions), summary
