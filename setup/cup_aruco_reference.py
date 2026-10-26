#!/usr/bin/env python3
"""Same-RGB ArUco reference and fixed-scene relative motion evaluation, in meters."""
import cv2
import numpy as np

ARUCO_DICTIONARIES = ('DICT_4X4_50', 'DICT_5X5_50', 'DICT_6X6_50', 'DICT_7X7_50', 'DICT_ARUCO_ORIGINAL')


def rigid_error(estimated, reference):
    # Neural float32 rotations may have tiny orthogonality residuals. Project
    # each to SO(3) before the geodesic angle, avoiding a nonzero self-error.
    def rotation(value):
        U, _, V = np.linalg.svd(value[:3, :3])
        correction = np.diag([1., 1., np.linalg.det(U @ V)])
        return U @ correction @ V
    difference = rotation(estimated) @ rotation(reference).T
    return dict(translation_error_mm=float(np.linalg.norm(estimated[:3, 3] - reference[:3, 3]) * 1000),
                rotation_error_deg=float(np.degrees(np.arccos(np.clip((np.trace(difference) - 1) / 2, -1, 1)))))


class ArucoReference:
    def __init__(self, length_m, marker_id=0, dictionary='DICT_4X4_50', fixed_scene=False, marker_from_mesh=None):
        if not np.isfinite(length_m) or length_m <= 0:
            raise ValueError('Measured black outer-border side length must be positive, in meters')
        self.length = length_m
        self.id = marker_id
        self.dictionary = dictionary
        self.fixed_scene = fixed_scene
        self.marker_from_mesh = marker_from_mesh
        if marker_from_mesh is not None:
            T = np.asarray(marker_from_mesh, np.float64)
            if (T.shape != (4, 4) or not np.isfinite(T).all()
                    or not np.allclose(T[3], [0, 0, 0, 1], atol=1e-7)
                    or not np.allclose(T[:3, :3].T @ T[:3, :3], np.eye(3), atol=1e-5)
                    or not np.isclose(np.linalg.det(T[:3, :3]), 1, atol=1e-5)):
                raise ValueError('Independent T_marker_from_original_mesh must be a rigid 4x4 matrix in meters')
            self.marker_from_mesh = T
        half = length_m / 2
        # IPPE_SQUARE prescribed order: TL, TR, BR, BL; marker x right/y up.
        self.object_points = np.array([[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]], np.float64)
        dictionary_obj = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
        if not 0 <= marker_id < len(dictionary_obj.bytesList):
            raise ValueError('Marker ID outside configured dictionary')
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector = cv2.aruco.ArucoDetector(dictionary_obj, parameters)
        self.anchor_estimate = self.anchor_marker = None
        self.anchor_frame = None

    def detect(self, rgb, K):
        corners, ids, _ = self.detector.detectMarkers(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
        value = dict(found=False, reference_accepted=False, dictionary=self.dictionary, marker_id=self.id,
                     measured_marker_length_m=self.length, corner_refinement='SUBPIX',
                     reference_is_error_free=False, detected_ids=[] if ids is None else ids.flatten().tolist())
        if ids is None or np.count_nonzero(ids == self.id) != 1:
            value['reason'] = 'target marker absent or duplicate target IDs'
            return value
        image_points = np.asarray(corners[int(np.flatnonzero(ids.flatten() == self.id)[0])]).reshape(4, 2).astype(np.float64)
        sides = np.linalg.norm(image_points - np.roll(image_points, 1, axis=0), axis=1)
        value.update(found=True, corners_px=image_points.tolist(), min_edge_pixels=float(sides.min()))
        if sides.min() < 25:
            value['reason'] = 'marker too small in image for configured reference gate'
            return value
        result = cv2.solvePnPGeneric(self.object_points, image_points, K, np.zeros(5), flags=cv2.SOLVEPNP_IPPE_SQUARE)
        candidates = []
        if result[0]:
            for rotation, translation in zip(result[1], result[2]):
                R, _ = cv2.Rodrigues(rotation)
                t = translation.reshape(3)
                if np.min(self.object_points @ R[2, :] + t[2]) <= 0:
                    continue
                projected, _ = cv2.projectPoints(self.object_points, rotation, translation, K, np.zeros(5))
                rms = float(np.sqrt(np.mean(np.sum((projected.reshape(4, 2) - image_points) ** 2, axis=1))))
                T = np.eye(4);T[:3, :3] = R;T[:3, 3] = t
                candidates.append((rms, T))
        candidates.sort(key=lambda item: item[0])
        if not candidates:
            value['reason'] = 'no positive-depth IPPE solution'
            return value
        rms, T = candidates[0]
        value.update(reprojection_rms_px=rms, pose_camera_from_marker=T.tolist(),
                     alternative_reprojection_rms_px=candidates[1][0] if len(candidates) > 1 else None)
        ambiguous = False
        if len(candidates) > 1:
            angle = rigid_error(T, candidates[1][1])['rotation_error_deg']
            ambiguous = angle > 5 and candidates[1][0] <= max(rms * 1.2, rms + .15)
            value['alternative_rotation_difference_deg'] = angle
        value.update(reference_accepted=rms <= 1.5 and not ambiguous,
                     reason='accepted independent marker reference' if rms <= 1.5 and not ambiguous else 'reprojection or planar ambiguity gate failed')
        return value

    def evaluate(self, pose, reference, frame, tracking_consistent):
        value = dict(relative_errors=None, anchored_object_errors=None, absolute_errors=None, anchor_frame=self.anchor_frame,
                     reference_is_error_free=False, absolute_object_pose_validated=False,
                     fixed_cup_and_marker_protocol=self.fixed_scene)
        if not reference.get('reference_accepted') or not tracking_consistent:
            value['reason'] = 'no accepted same-frame reference or tracking consistency failed'
            return value
        marker = np.array(reference['pose_camera_from_marker'])
        if self.fixed_scene:
            if self.anchor_estimate is None:
                self.anchor_estimate, self.anchor_marker, self.anchor_frame = pose.copy(), marker.copy(), frame
            estimate_delta = pose @ np.linalg.inv(self.anchor_estimate)
            reference_delta = marker @ np.linalg.inv(self.anchor_marker)
            value.update(relative_errors=rigid_error(estimate_delta, reference_delta), anchor_frame=self.anchor_frame,
                         relative_metric_definition='T_Ct_from_C0 = T_Ct_from_O @ inverse(T_C0_from_O), compared to marker equivalent',
                         estimate_relative_transform=estimate_delta.tolist(), reference_relative_transform=reference_delta.tolist())
            anchored_reference = reference_delta @ self.anchor_estimate
            value.update(anchored_object_errors=rigid_error(pose, anchored_reference),
                         anchored_reference_pose_camera_from_mesh=anchored_reference.tolist(),
                         anchored_scope='Object-origin drift relative to first estimated pose, with marker camera motion; removes initial object-pose bias, not absolute GT')
        if self.marker_from_mesh is not None:
            absolute_reference = marker @ self.marker_from_mesh
            value.update(absolute_errors=rigid_error(pose, absolute_reference),
                         pose_camera_from_mesh_reference=absolute_reference.tolist(),
                         absolute_requires_independent_marker_from_mesh_calibration=True)
        return value
