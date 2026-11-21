#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯数学、ArUco 和配置函数。导入本文件不会连接 ROS、相机或机械臂。"""

import math
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import yaml


def vector(values, size, name):
    a = np.asarray(values, dtype=float)
    if a.shape != (size,) or not np.all(np.isfinite(a)):
        raise ValueError("{} 必须包含 {} 个有限数值".format(name, size))
    return a


def transform(xyz, rpy_deg=(0, 0, 0)):
    """生成 T_parent_child：p_parent = T_parent_child @ p_child。"""
    r, p, y = np.deg2rad(vector(rpy_deg, 3, "RPY"))
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    T = np.eye(4)
    T[:3, :3] = [[cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr],
                 [sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr], [-sp, cp*sr, cp*cr]]
    T[:3, 3] = vector(xyz, 3, "XYZ")
    return T


def pose_matrix(xyz, xyzw):
    q = vector(xyzw, 4, "四元数")
    norm = np.linalg.norm(q)
    if norm < 1e-9:
        raise ValueError("反馈四元数为零")
    x, y, z, w = q / norm
    T = np.eye(4)
    T[:3, :3] = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                 [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                 [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    T[:3, 3] = vector(xyz, 3, "反馈位置")
    return T


def euler_radians(R):
    """返回 ROS PosCmd 使用的固定轴 XYZ 欧拉角，单位 rad。"""
    sy = math.hypot(R[0, 0], R[1, 0])
    if sy > 1e-8:
        return math.atan2(R[2, 1], R[2, 2]), math.atan2(-R[2, 0], sy), math.atan2(R[1, 0], R[0, 0])
    return math.atan2(-R[1, 2], R[1, 1]), math.atan2(-R[2, 0], sy), 0.0


def rotation_distance(A, B):
    return float(np.linalg.norm(cv2.Rodrigues(A.T @ B)[0]))


def interpolate_pose(start, target, alpha):
    """平移走直线，旋转沿 SO(3) 最短弧；纯旋转也能插值。"""
    T = np.eye(4)
    axis_angle = cv2.Rodrigues(start[:3, :3].T @ target[:3, :3])[0]
    T[:3, :3] = start[:3, :3] @ cv2.Rodrigues(alpha * axis_angle)[0]
    T[:3, 3] = start[:3, 3] + alpha * (target[:3, 3] - start[:3, 3])
    return T


def smooth_progress(progress):
    """五次时间曲线：两端的速度和加速度均为零，最大斜率为1.875。"""
    t = float(np.clip(progress, 0.0, 1.0))
    return t*t*t * (10.0 + t * (-15.0 + 6.0*t))


def level_rotation(reference):
    """沿用 _4 的夹持方向：局部 X 向下，局部 Z 取观测姿态 Z 轴的水平投影。"""
    x = np.array([0.0, 0.0, -1.0])
    for ref in [reference[:, 2], reference[:, 1], reference[:, 0], np.array([1., 0., 0.])]:
        z = ref - np.dot(ref, x) * x
        if np.linalg.norm(z) > 1e-8:
            z /= np.linalg.norm(z)
            return np.column_stack((x, np.cross(z, x), z))
    raise ValueError("无法构造抓取朝向")


def dictionary_and_detector(config):
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("OpenCV 缺少 aruco；请使用项目 .venv-piper 环境")
    name = config["marker_dictionary"]
    if not isinstance(name, str) or not name.startswith("DICT_") or not hasattr(cv2.aruco, name):
        raise ValueError("未知 ArUco 字典: {}".format(name))
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))
    if not isinstance(config["marker_id"], int) or not 0 <= config["marker_id"] < len(dictionary.bytesList):
        raise ValueError("marker_id 超出所选字典范围")
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return dictionary, cv2.aruco.ArucoDetector(dictionary, params)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        c = yaml.safe_load(f)
    if not isinstance(c, dict):
        raise ValueError("配置必须为 YAML 字典")
    # 以随程序提供的配置为字段表，遗漏字段立即报错，不带着不完整参数移动。
    with open(Path(__file__).with_name("aruco_grab.yaml"), encoding="utf-8") as f:
        required = yaml.safe_load(f)
    missing = set(required) - set(c)
    if missing:
        raise ValueError("配置缺少字段: " + ", ".join(sorted(missing)))
    positive = ["marker_length_m", "observation_speed_percent", "joint_tolerance_rad",
                "observation_timeout_s", "travel_speed_m_s", "approach_speed_m_s",
                "angular_speed_rad_s", "command_rate_hz", "position_tolerance_m",
                "rotation_tolerance_rad", "arrival_timeout_s", "feedback_timeout_s",
                "startup_timeout_s", "gripper_wait_s", "pregrasp_distance_m",
                "detection_timeout_s", "max_position_spread_m", "max_rotation_spread_rad",
                "min_marker_area_px", "max_reprojection_error_px", "min_depth_m",
                "max_depth_m", "max_depth_difference_m", "max_segment_distance_m"]
    for key in positive:
        if not isinstance(c[key], (float, int)) or not np.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(key + " 必须为正的有限数值")
    for key in ["settle_time_s", "lift_distance_m"]:
        if not np.isfinite(c[key]) or c[key] < 0:
            raise ValueError(key + " 不能为负")
    for key in ["camera_width", "camera_height", "camera_fps", "camera_warmup_frames", "stable_frames"]:
        if not isinstance(c[key], int) or c[key] < (2 if key == "stable_frames" else 1):
            raise ValueError(key + " 必须为合法正整数")
    for key in ["ee_to_tcp_xyz_m", "ee_to_tcp_rpy_deg", "marker_to_grasp_xyz_m",
                "marker_to_grasp_rpy_deg", "workspace_min_m", "workspace_max_m"]:
        vector(c[key], 3, key)
    joints = vector(c["observation_joints_rad"], 6, "observation_joints_rad")
    urdf = Path(__file__).resolve().parent.parent / "piper_description/urdf/piper_description.urdf"
    limits = {j.attrib["name"]: j.find("limit") for j in ET.parse(urdf).getroot().findall("joint")}
    for i, value in enumerate(joints, 1):
        limit = limits["joint{}".format(i)]
        if not float(limit.attrib["lower"]) <= value <= float(limit.attrib["upper"]):
            raise ValueError("观测位 joint{} 超出本机 URDF 关节范围".format(i))
    if c["orientation_mode"] not in ("level", "marker"):
        raise ValueError("orientation_mode 只能为 level 或 marker")
    if np.any(np.asarray(c["workspace_min_m"]) >= np.asarray(c["workspace_max_m"])):
        raise ValueError("工作空间下限必须小于上限")
    if c["min_depth_m"] >= c["max_depth_m"] or c["observation_speed_percent"] > 100:
        raise ValueError("深度范围或关节速度百分比无效")
    if not 0 <= c["gripper_closed_m"] < c["gripper_open_m"] <= 0.07:
        raise ValueError("夹爪需要满足 0 <= 闭合开度 < 张开开度 <= 0.07 米")
    if not 0.5 <= c["gripper_effort"] <= 2.0:
        raise ValueError("gripper_effort 超出当前驱动服务范围 0.5～2")
    for key in ["enable_arm", "show_window", "require_depth"]:
        if not isinstance(c[key], bool):
            raise ValueError(key + " 必须为 true/false")
    T = np.asarray(c["ee_to_camera"], dtype=float)
    if T.shape != (4, 4) or not np.all(np.isfinite(T)) or not np.allclose(T[3], [0, 0, 0, 1]):
        raise ValueError("ee_to_camera 必须为有限的 4×4 齐次矩阵")
    if not np.allclose(T[:3, :3].T @ T[:3, :3], np.eye(3), atol=0.01) or np.linalg.det(T[:3, :3]) <= 0:
        raise ValueError("手眼矩阵旋转部分无效")
    dictionary_and_detector(c)
    return c


def hand_eye(config):
    T = np.array(config["ee_to_camera"], dtype=float)
    u, _, vt = np.linalg.svd(T[:3, :3])
    T[:3, :3] = u @ vt
    return T


def marker_object_points(length):
    """IPPE_SQUARE 要求的顺序：左上、右上、右下、左下；原点在码中心。"""
    h = length / 2.0
    return np.array([[-h, h, 0], [h, h, 0], [h, -h, 0], [-h, -h, 0]], dtype=np.float64)


def estimate_marker_pose(normalized_corners, length, focal_xy):
    """输入去畸变的相机射线 x/z,y/z，避免把 RealSense 逆畸变参数当成 OpenCV 参数。"""
    points = marker_object_points(length)
    corners = np.asarray(normalized_corners, dtype=np.float64).reshape(4, 2)
    result = cv2.solvePnPGeneric(points, corners, np.eye(3), None, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    candidates = []
    if not result[0]:
        raise ValueError("ArUco PnP 无解")
    for rvec, tvec in zip(result[1], result[2]):
        R = cv2.Rodrigues(rvec)[0]
        xyz = (R @ points.T).T + tvec.reshape(3)
        if not np.all(np.isfinite(xyz)) or np.any(xyz[:, 2] <= 0):
            continue
        predicted = xyz[:, :2] / xyz[:, 2:3]
        error = float(np.sqrt(np.mean(np.sum(((predicted - corners) * focal_xy) ** 2, axis=1))))
        T = np.eye(4)
        T[:3, :3], T[:3, 3] = R, tvec.reshape(3)
        candidates.append((error, T))
    if not candidates:
        raise ValueError("PnP 候选位于相机后方或数值无效")
    return min(candidates, key=lambda item: item[0])


def marker_depth(depth_image_m, corners, config):
    """在码内缩后的多边形取深度中位数，减少边缘背景污染。"""
    corners = np.asarray(corners).reshape(4, 2)
    inner = corners.mean(axis=0) + 0.6 * (corners - corners.mean(axis=0))
    mask = np.zeros(depth_image_m.shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.rint(inner).astype(np.int32), 1)
    values = depth_image_m[(mask > 0) & np.isfinite(depth_image_m)
                           & (depth_image_m > config["min_depth_m"])
                           & (depth_image_m < config["max_depth_m"])]
    return float(np.median(values)) if len(values) >= 20 else None


class StablePoseWindow:
    """只接受连续稳定帧；位置跳变、姿态翻转或漏检后重新积累。"""
    def __init__(self, config):
        self.config, self.samples = config, []

    def clear(self):
        self.samples.clear()

    def add(self, T):
        if any(np.linalg.norm(T[:3, 3] - s[:3, 3]) > self.config["max_position_spread_m"]
               or rotation_distance(T[:3, :3], s[:3, :3]) > self.config["max_rotation_spread_rad"]
               for s in self.samples):
            self.clear()
        self.samples.append(T.copy())
        self.samples = self.samples[-self.config["stable_frames"]:]
        if len(self.samples) < self.config["stable_frames"]:
            return None
        result = np.eye(4)
        result[:3, 3] = np.median([s[:3, 3] for s in self.samples], axis=0)
        u, _, vt = np.linalg.svd(sum(s[:3, :3] for s in self.samples))
        result[:3, :3] = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
        return result


def grasp_plan(T_base_marker, T_base_observation, config):
    """先算 TCP 目标，再以工具变换的逆矩阵反求驱动末端目标。"""
    T_tcp = T_base_marker @ transform(config["marker_to_grasp_xyz_m"], config["marker_to_grasp_rpy_deg"])
    if config["orientation_mode"] == "level":
        T_tcp[:3, :3] = level_rotation(T_base_observation[:3, :3])
    T_ee_tcp = transform(config["ee_to_tcp_xyz_m"], config["ee_to_tcp_rpy_deg"])
    grasp = T_tcp @ np.linalg.inv(T_ee_tcp)
    pre = T_tcp @ transform([0, 0, -config["pregrasp_distance_m"]]) @ np.linalg.inv(T_ee_tcp)
    lift = grasp.copy()
    lift[2, 3] += config["lift_distance_m"]
    return [("预抓取", pre), ("靠近", grasp), ("提起", lift)]


def validate_plan(plan, start, config):
    lo, hi = np.array(config["workspace_min_m"]), np.array(config["workspace_max_m"])
    previous = start
    for name, T in plan:
        if not np.all(np.isfinite(T)) or np.any(T[:3, 3] < lo) or np.any(T[:3, 3] > hi):
            raise ValueError("{}末端目标超出配置工作空间: {}".format(name, T[:3, 3]))
        if np.linalg.norm(T[:3, 3] - previous[:3, 3]) > config["max_segment_distance_m"]:
            raise ValueError(name + "单段移动距离超过配置上限")
        previous = T
