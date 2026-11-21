"""Object-axis/handle-guided pregrasp geometry; importing never connects hardware.

The handle rules are geometric heuristics, not a complete collision checker.
Workspace/segment checks run here; existing live IK/path checks remain mandatory.
"""
import math
import numpy as np
from aruco_geometry import grasp_plan, level_rotation, rotation_distance, transform, validate_plan, vector
from pose_stability import matrix
from cup_approach_route import pitch_limit_degrees


class SideGraspPlanningError(ValueError):
    def __init__(self, message, details):
        super().__init__(message)
        self.details = details


def unit(value, name):
    v = vector(value, 3, name)
    length = np.linalg.norm(v)
    if length < 1e-8:
        raise ValueError(name + ' must be nonzero')
    return v / length


def pregrasp_height_corrected(T_base_pregrasp_ee, config):
    """Temporary user-observed trim in base +Z, independent of grasp orientation."""
    height = config.get('pregrasp_height_correction_m', 0.)
    if isinstance(height, bool) or not isinstance(height, (float, int)) or not np.isfinite(height):
        raise ValueError('pregrasp_height_correction_m 必须是有限米值')
    if abs(height) > .05:
        raise ValueError('临时预抓取高度补偿不得超过±50mm；请检查手眼/TCP')
    target = matrix(T_base_pregrasp_ee).copy()
    target[2, 3] += height
    return target


def validate_side_config(config):
    mode = config.get('pregrasp_orientation_mode', 'fixed_level')
    if mode not in ('fixed_level', 'object_axis_handle'):
        raise ValueError('Unknown pregrasp_orientation_mode: ' + str(mode))
    pregrasp_height_corrected(np.eye(4), config)
    pitch_limit_degrees(config)
    if not isinstance(config.get('pregrasp_lying_upper_enabled', False), bool):
        raise ValueError('pregrasp_lying_upper_enabled必须为布尔值')
    if config.get('pregrasp_height_correction_scope', 'vertical_only') not in ('vertical_only', 'all_postures'):
        raise ValueError('Invalid pregrasp_height_correction_scope')
    if config.get('pregrasp_lying_upper_enabled', False) and config.get('pregrasp_height_correction_scope', 'vertical_only') != 'vertical_only':
        raise ValueError('横躺上方接近要求高度补偿仅用于竖直杯')
    if mode == 'object_axis_handle':
        axis = unit(config['pregrasp_cup_axis_mesh'], 'cup axis')
        handle = unit(config['pregrasp_handle_axis_mesh'], 'handle axis')
        if abs(float(axis @ handle)) > .05:
            raise ValueError('杯把方向必须近似垂直杯身轴线')
        for key in ('pregrasp_body_diameter_m', 'pregrasp_measured_opening_m'):
            value = config[key]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value) or value <= 0:
                raise ValueError('Invalid '+key)
    return mode


def rotation_about(axis, angle):
    # Rodrigues in scalar/vector form; no Euler singularity for a horizontal cup.
    a = unit(axis, 'rotation axis')
    skew = np.array([[0., -a[2], a[1]], [a[2], 0., -a[0]], [-a[1], a[0], 0.]])
    return np.eye(3)*math.cos(angle) + (1-math.cos(angle))*np.outer(a, a) + math.sin(angle)*skew


def axes_rotation(x_axis, approach):
    x = unit(x_axis, 'TCP X')
    z = unit(approach, 'TCP approach')
    x = unit(x - z*float(x @ z), 'TCP X perpendicular to approach')
    y = unit(np.cross(z, x), 'TCP closing Y')
    return np.column_stack((x, y, z))


def pitch_fallback_candidates(candidates, observation_base, config):
    """Pitch level side-grasp candidates about closing Y, retaining TCP points."""
    maximum = pitch_limit_degrees(config)
    if maximum == 0.:
        return []
    tool = transform(config['ee_to_tcp_xyz_m'], config['ee_to_tcp_rpy_deg'])
    inverse_tool = np.linalg.inv(tool)
    generated = []
    target_keys = ('T_base_pregrasp_ee', 'T_base_center_target_ee', 'T_base_pregrasp_ee_nominal')
    transient = ('ik_checked', 'ik_accepted', 'ik_status', 'ik_request_id', 'checked_target_joints_rad')
    for angle in sorted({min(5., maximum), maximum}):
        pitch = rotation_about([0., 1., 0.], math.radians(angle))
        for candidate in candidates:
            original_tcp = matrix(candidate['T_base_pregrasp_ee']) @ tool
            # Closing-Y pitch is vertical for a level, TCP-X-down grasp. Other
            # cup orientations retain their existing object-axis candidates.
            if not np.allclose(original_tcp[:3, 0], [0., 0., -1.], atol=1e-6):
                continue
            record = {key:value for key,value in candidate.items() if key not in transient}
            record.update(label=candidate['label']+'_pitch_%+g' % angle,
                          original_candidate=candidate['label'], wrist_pitch_deg=angle,
                          ik_checked=False, rejected_reason=None)
            for key in target_keys:
                tcp = matrix(candidate[key]) @ tool
                tcp[:3, :3] = tcp[:3, :3] @ pitch
                record[key] = (tcp @ inverse_tool).tolist()
            pitched_tcp = np.asarray(record['T_base_pregrasp_ee']) @ tool
            record['approach_axis_base'] = pitched_tcp[:3, 2].tolist()
            record['translation_approach_axis_base'] = original_tcp[:3, 2].tolist()
            record['tcp_point_preserved'] = True
            try:
                validate_plan([('预抓取', np.asarray(record['T_base_pregrasp_ee']))], observation_base, config)
            except ValueError as error:
                record['rejected_reason'] = 'workspace_or_segment: '+str(error)
            generated.append(record)
    return generated


def object_side_pregrasp(center_base, observation_base, config):
    """Return a checked pregrasp and nominal center target, plus every decision.

    Vertical cups keep TCP X down and approach horizontal. Lying/tilted cups
    align TCP X with the cup axis and approach along the horizontal normal to
    that axis. Every candidate shares the route planner's horizontal constraint.
    """
    center = matrix(center_base)
    observation = matrix(observation_base)
    mode = validate_side_config(config)
    up = np.array([0., 0., 1.])
    candidates = []
    raw = []
    meta = dict(mode=mode, translation_unit='m', table_collision_validated=False,
                contact_grasp_validated=False, ik_and_joint_path_check='required_by_existing_motion_backend')
    applied_height = config.get('pregrasp_height_correction_m', 0.)
    if mode == 'fixed_level':
        raw.append((level_rotation(observation[:3, :3]), 0., 'fixed_level'))
    else:
        axis = unit(center[:3, :3] @ unit(config['pregrasp_cup_axis_mesh'], 'cup axis'), 'base cup axis')
        handle = center[:3, :3] @ unit(config['pregrasp_handle_axis_mesh'], 'handle axis')
        handle = unit(handle - axis*float(handle @ axis), 'radial handle')
        vertical = abs(float(axis @ up)) >= math.cos(math.radians(20.))
        posture = 'vertical_horizontal_side' if vertical else 'lying_or_tilted_radial_side'
        if not vertical and config.get('pregrasp_height_correction_scope', 'vertical_only') == 'vertical_only':
            # The earlier20mm observation was made with an inverted upright cup.
            # It is not a calibrated tool-frame offset that can be reused after tilting.
            applied_height = 0.
        meta.update(posture=posture, cup_axis_base=axis.tolist(), handle_axis_base=handle.tolist(),
                    body_diameter_m=config['pregrasp_body_diameter_m'],
                    measured_physical_opening_m=config['pregrasp_measured_opening_m'],
                    configured_gripper_command_m=config['gripper_open_m'],
                    body_fits_measured_opening=bool(config['pregrasp_body_diameter_m'] <= config['pregrasp_measured_opening_m']),
                    nominal_each_side_clearance_m=(config['pregrasp_measured_opening_m']-config['pregrasp_body_diameter_m'])/2.,
                    handle_avoidance='heuristic approach cone45deg and finger cone20deg; no mesh collision guarantee')
        if vertical:
            horizontal = unit(handle - up*float(handle @ up), 'horizontal handle')
            angles = [0.] + [sign*angle for angle in range(15, 121, 15) for sign in (-1., 1.)]
            for degrees in angles:
                d = rotation_about(up, math.radians(degrees)) @ horizontal
                raw.append((axes_rotation(-up, d), abs(degrees), 'horizontal_handle_%+g' % degrees))
        else:
            horizontal_radial = unit(np.cross(up, axis), 'horizontal radial cup approach')
            for side in (1., -1.):
                d = side*horizontal_radial
                angle = math.degrees(math.atan2(float(d @ np.cross(axis, handle)),
                                               float(d @ handle)))
                for sign in (1., -1.):
                    raw.append((axes_rotation(sign*axis, d), abs(angle),
                                'horizontal_radial_side_%+g_axis_%+g' % (side, sign)))

    if (mode == 'object_axis_handle' and not vertical
            and config.get('pregrasp_lying_upper_enabled', False)
            and abs(float(axis @ up)) <= math.sin(math.radians(20.))):
        radial = unit(np.cross(up, axis), 'lying horizontal radial')
        for side in (1., -1.):
            for elevation in (15., 30., 45., 60., 75., 90.):
                base_direction = rotation_about(axis, math.radians(side*elevation)) @ (side*radial)
                if base_direction[2] > 0.:
                    base_direction = rotation_about(axis, -math.radians(side*elevation)) @ (side*radial)
                for axis_sign in (1., -1.):
                    original = axes_rotation(axis_sign*axis, base_direction)
                    slope = math.degrees(math.asin(float(np.clip(-original[2, 2], -1., 1.))))
                    if not 5. <= slope <= 75.:
                        continue
                    label = 'lying_upper_side_%+g_elev_%g_axis_%+g_radial' % (side, elevation, axis_sign)
                    raw.append((original, 0., label))

    meta.update(configured_height_correction_m=config.get('pregrasp_height_correction_m', 0.),
                applied_height_correction_m=applied_height,
                height_correction_scope=config.get('pregrasp_height_correction_scope', 'vertical_only'))
    for rotation, deviation, label in raw:
        reason = None
        d, closing = rotation[:, 2], rotation[:, 1]
        if mode == 'object_axis_handle':
            if float((-d) @ handle) > math.cos(math.radians(45.)) + 1e-8:
                reason = 'approach_origin_too_close_to_handle_direction'
            elif abs(float(closing @ handle)) > math.cos(math.radians(20.)) + 1e-8:
                reason = 'finger_closing_axis_too_close_to_handle'
            elif not vertical and float(d @ up) > .15:
                reason = 'approach_from_below_rejected'
        record = dict(label=label, deviation_from_handle_opposite_deg=float(deviation),
                      approach_axis_base=d.tolist(), rejected_reason=reason)
        upper = label.startswith('lying_upper_')
        if upper:
            record['route_mode'] = 'lying_upper'
            record['approach_inclination_deg'] = math.degrees(math.asin(float(np.clip(-d[2], -1., 1.))))

        if reason is None:
            reference = center.copy()
            reference[:3, :3] = rotation
            plan_config = dict(config, orientation_mode='marker', marker_to_grasp_xyz_m=[0., 0., 0.],
                               marker_to_grasp_rpy_deg=[0., 0., 0.])
            plan = grasp_plan(reference, observation, plan_config)
            nominal = plan[0][1].copy()
            plan[0] = (plan[0][0], pregrasp_height_corrected(nominal, dict(config, pregrasp_height_correction_m=applied_height)))
            try:
                validate_plan(plan[:1], observation, config)
            except ValueError as exc:
                record['rejected_reason'] = 'workspace_or_segment: ' + str(exc)
            else:
                distance = float(np.linalg.norm(plan[0][1][:3, 3]-observation[:3, 3]))
                rotation_change = rotation_distance(observation[:3, :3], plan[0][1][:3, :3])
                # Prioritize opposite-handle for vertical cups, upper-side for lying cups.
                preference = deviation/15. if mode == 'object_axis_handle' and vertical else 0.
                if mode == 'object_axis_handle' and not vertical:
                    preference = deviation/180.
                score = float(preference + distance + .1*rotation_change)
                if upper:
                    score += 1000. + record['approach_inclination_deg']/15.

                record.update(score=score, segment_distance_m=distance, ik_checked=False,
                              T_base_pregrasp_ee=plan[0][1].tolist(),
                              T_base_center_target_ee=plan[1][1].tolist(),
                              T_base_pregrasp_ee_nominal=nominal.tolist())
                candidates.append((score, label, plan, nominal, rotation, record))
        meta.setdefault('candidates', []).append(record)

    if not candidates:
        reasons = sorted(set(item['rejected_reason'] for item in meta['candidates']))
        raise SideGraspPlanningError('没有通过方向/工作空间/单段距离约束的预抓取候选：' + '; '.join(reasons), meta)
    _, label, plan, nominal, rotation, record = min(candidates, key=lambda c:(c[0], c[1]))
    ee_tcp = transform(config['ee_to_tcp_xyz_m'], config['ee_to_tcp_rpy_deg'])
    target_tcp = plan[1][1] @ ee_tcp
    meta.update(selected=label, selected_approach_axis_base=rotation[:, 2].tolist(),
                selected_closing_axis_base=rotation[:, 1].tolist(),
                R_cup_center_tcp=(center[:3, :3].T @ rotation).tolist(),
                T_cup_center_tcp=(np.linalg.inv(center) @ target_tcp).tolist(),
                T_base_pregrasp_ee_nominal=nominal.tolist(),
                accepted_geometric_candidates=len(candidates))
    return plan, meta
