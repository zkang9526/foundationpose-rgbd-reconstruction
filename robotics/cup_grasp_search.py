"""Full radial pregrasp candidates with tool approach perpendicular to cup axis."""
import math

import numpy as np

from aruco_geometry import rotation_distance, transform, validate_plan
from cup_side_grasp import SideGraspPlanningError, axes_rotation, unit, validate_side_config
from pose_stability import matrix


def search_angle_step(config):
    """Use an integer angular grid that covers the complete circle uniformly."""
    enabled = config.get('pregrasp_search_enabled', False)
    if not isinstance(enabled, bool):
        raise ValueError('pregrasp_search_enabled必须为布尔值')
    for name in ('pregrasp_closing_axis_fallback_enabled', 'search_ik_tolerance_refinement_enabled'):
        if not isinstance(config.get(name, False), bool):
            raise ValueError(name+'必须为布尔值')
    step = config.get('pregrasp_search_angle_step_deg', 5)
    if isinstance(step, bool) or not isinstance(step, int) or not 1 <= step <= 30 or 360 % step:
        raise ValueError('pregrasp_search_angle_step_deg必须为1至30中整除360的整数')
    return step


def expanded_side_pregrasp(center_base, observation_base, config):
    """Generate geometry-only candidates; every candidate still needs full planning.

    Tool X follows the cup axis with either sign. Tool Z approaches radially and
    tool Y closes across the body. All three frames retain their native units.
    """
    center = matrix(center_base)
    observation = matrix(observation_base)
    step = search_angle_step(config)
    closing_fallback = config.get('pregrasp_closing_axis_fallback_enabled', False)
    if not isinstance(closing_fallback, bool):
        raise ValueError('pregrasp_closing_axis_fallback_enabled必须为布尔值')
    if validate_side_config(config) != 'object_axis_handle':
        raise ValueError('完整径向搜索要求object_axis_handle模式')
    distance = config['pregrasp_distance_m']
    if isinstance(distance, bool) or not isinstance(distance, (float, int)) or not np.isfinite(distance) or distance <= 0:
        raise ValueError('pregrasp_distance_m必须为正有限米值')

    axis = unit(center[:3, :3] @ unit(config['pregrasp_cup_axis_mesh'], 'cup axis'), 'base cup axis')
    handle = center[:3, :3] @ unit(config['pregrasp_handle_axis_mesh'], 'handle axis')
    handle = unit(handle-axis*float(handle @ axis), 'radial handle')
    tangent = unit(np.cross(axis, handle), 'radial tangent')
    vertical = abs(float(axis[2])) >= math.cos(math.radians(20.))
    height = float(config.get('pregrasp_height_correction_m', 0.))
    if not vertical and config.get('pregrasp_height_correction_scope', 'vertical_only') == 'vertical_only':
        height = 0.
    trim = np.array([0., 0., height])
    tool = transform(config['ee_to_tcp_xyz_m'], config['ee_to_tcp_rpy_deg'])
    inverse_tool = np.linalg.inv(tool)
    observation_tcp = observation @ tool
    towards_center = center[:3, 3]-observation_tcp[:3, 3]
    towards_center -= axis*float(towards_center @ axis)
    if np.linalg.norm(towards_center) < 1e-8:
        towards_center = handle.copy()
    preferred = unit(towards_center, 'preferred radial approach')
    records = []
    accepted = []
    meta = dict(mode='object_axis_handle', search_policy='full_radial_perpendicular',
                posture='vertical_horizontal_side' if vertical else 'lying_or_tilted_radial_side',
                translation_unit='m', cup_axis_base=axis.tolist(), handle_axis_base=handle.tolist(),
                configured_height_correction_m=config.get('pregrasp_height_correction_m', 0.),
                applied_height_correction_m=height,
                height_correction_scope=config.get('pregrasp_height_correction_scope', 'vertical_only'),
                body_diameter_m=config['pregrasp_body_diameter_m'],
                measured_physical_opening_m=config['pregrasp_measured_opening_m'],
                body_fits_measured_opening=bool(config['pregrasp_body_diameter_m'] <= config['pregrasp_measured_opening_m']),
                table_collision_validated=False, contact_grasp_validated=False,
                ik_and_joint_path_check='required_by_existing_motion_backend',
                search_angle_step_deg=step, closing_axis_fallback_enabled=closing_fallback,
                candidates=records)
    for angle in range(0, 360, step):
        radians = math.radians(angle)
        direction = math.cos(radians)*handle+math.sin(radians)*tangent
        for sign in (1., -1.):
            rotation = axes_rotation(sign*axis, direction)
            closing = rotation[:, 1]
            reason = None
            handle_warning = None
            if float(direction[2]) > .15:
                reason = 'approach_from_below_rejected'
            elif float((-direction) @ handle) > math.cos(math.radians(45.))+1e-8:
                reason = 'approach_origin_too_close_to_handle_direction'
            elif abs(float(closing @ handle)) > math.cos(math.radians(20.))+1e-8:
                if closing_fallback:
                    handle_warning = 'finger_closing_axis_too_close_to_handle'
                else:
                    reason = 'finger_closing_axis_too_close_to_handle'
            tcp = center.copy()
            tcp[:3, :3] = rotation
            pre_tcp = tcp.copy()
            pre_tcp[:3, 3] += trim-distance*direction
            target = pre_tcp @ inverse_tool
            nominal_tcp = pre_tcp.copy()
            nominal_tcp[:3, 3] -= trim
            offset_angle = math.degrees(math.acos(float(np.clip(direction @ preferred, -1., 1.))))
            rotation_change = rotation_distance(observation[:3, :3], target[:3, :3])
            travel = float(np.linalg.norm(target[:3, 3]-observation[:3, 3]))
            score = float(offset_angle/180.+.15*rotation_change+travel)
            if handle_warning is not None:
                score += 1000.
            record = dict(label='radial_search_angle_%03d_axis_%+g' % (angle, sign),
                          route_mode='perpendicular', search_angle_deg=angle,
                          search_axis_sign=sign, score=score, search_rank=score,
                          approach_axis_base=direction.tolist(),
                          translation_approach_axis_base=direction.tolist(),
                          deviation_from_handle_opposite_deg=float(min(angle, 360-angle)),
                          wrist_pitch_deg=0., rejected_reason=reason,
                          handle_heuristic_warning=handle_warning,
                          applied_height_correction_m=height, ik_checked=False,
                          T_base_pregrasp_ee=target.tolist(),
                          T_base_center_target_ee=(tcp @ inverse_tool).tolist(),
                          T_base_pregrasp_ee_nominal=(nominal_tcp @ inverse_tool).tolist(),
                          approach_cup_axis_dot=float(direction @ axis),
                          closing_cup_axis_dot=float(closing @ axis))
            if reason is None:
                try:
                    validate_plan([('预抓取', target)], observation, config)
                except ValueError as error:
                    record['rejected_reason'] = 'workspace_or_segment: '+str(error)
                else:
                    accepted.append(record)
            records.append(record)
    meta['accepted_geometric_candidates'] = len(accepted)
    meta['generated_candidates'] = len(records)
    if not accepted:
        reasons = sorted(set(record['rejected_reason'] for record in records))
        raise SideGraspPlanningError('完整径向搜索没有通过几何约束的预抓取候选：'+'；'.join(reasons), meta)
    selected = min(accepted, key=lambda record:(record['score'], record['label']))
    pre = np.asarray(selected['T_base_pregrasp_ee'])
    goal = np.asarray(selected['T_base_center_target_ee'])
    tcp_goal = goal @ tool
    meta.update(selected=selected['label'],
                selected_approach_axis_base=tcp_goal[:3, 2].tolist(),
                selected_closing_axis_base=tcp_goal[:3, 1].tolist(),
                R_cup_center_tcp=(center[:3, :3].T @ tcp_goal[:3, :3]).tolist(),
                T_cup_center_tcp=(np.linalg.inv(center) @ tcp_goal).tolist(),
                T_base_pregrasp_ee_nominal=selected['T_base_pregrasp_ee_nominal'])
    return [('预抓取', pre), ('靠近', goal)], meta
