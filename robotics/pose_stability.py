"""Pure numerical gate shared by live acquisition and recorded-session replay."""
from collections import Counter
import numpy as np


def matrix(value):
    T = np.asarray(value, dtype=float)
    if T.shape != (4, 4) or not np.isfinite(T).all():
        raise ValueError('Invalid pose shape/values')
    R = T[:3, :3]
    if (not np.allclose(T[3], [0, 0, 0, 1], atol=1e-6, rtol=0)
            or not np.allclose(R.T @ R, np.eye(3), atol=1e-3, rtol=0)
            or abs(np.linalg.det(R) - 1) > 1e-3):
        raise ValueError('Invalid rigid transform')
    return T


def rotation_distance(A, B):
    # Project small float32 nonorthogonality before measuring geodesic distance.
    u, _, vt = np.linalg.svd(A.T @ B)
    R = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
    return float(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))


class PoseStabilityGate:
    def __init__(self, config):
        self.c = config
        self.samples, self.times, self.frames = [], [], []
        self.last = None
        self.resets = Counter()
        self.rejections = Counter()
        self.max_position = self.max_rotation = 0.0
        self.last_reason = None

    def reset(self, reason):
        if self.samples:
            self.resets[reason] += 1
        self.samples.clear()
        self.times.clear()
        self.frames.clear()
        self.max_position = self.max_rotation = 0.0
        self.last_reason = reason

    def add(self, frame, result, capture, now):
        self.last_reason = None
        try:
            captured = float(capture['received_monotonic'])
            if not np.isfinite([captured, now]).all():
                raise ValueError('nonfinite timestamp')
            epoch = result['tracking_epoch']
            if type(epoch) is not int or type(frame) is not int:
                raise ValueError('invalid frame/epoch')
        except (KeyError, TypeError, ValueError, OverflowError):
            self.last = None
            return self.reject('invalid_metadata')
        if self.last is not None:
            old_frame, old_time, old_epoch = self.last
            if epoch != old_epoch:
                self.reset('tracking_epoch_changed')
            elif frame != old_frame + 1:
                self.reset('frame_gap')
            elif captured <= old_time or captured - old_time > self.c['max_pose_age_s']:
                self.reset('capture_time_gap')
        self.last = (frame, captured, epoch)
        if not 0 <= now - captured <= self.c['max_pose_age_s']:
            return self.reject('stale_or_future_capture')
        if not all(result.get(key) is True for key in (
                'pose_confirmed', 'accepted_for_tracking', 'state_revision_current')):
            return self.reject('unconfirmed_or_rejected')
        try:
            T = matrix(result['pose'])
        except (KeyError, TypeError, ValueError):
            return self.reject('invalid_pose')
        if not self.c['min_depth_m'] < T[2, 3] < self.c['max_depth_m']:
            return self.reject('depth_out_of_range')
        distances = [float(np.linalg.norm(T[:3, 3] - s[:3, 3])) for s in self.samples]
        angles = [rotation_distance(T[:3, :3], s[:3, :3]) for s in self.samples]
        dp, dr = max(distances, default=0.0), max(angles, default=0.0)
        if dp > self.c['max_position_spread_m'] or dr > self.c['max_rotation_spread_rad']:
            self.reset('pose_spread')
            dp = dr = 0.0
        self.max_position = max(self.max_position, dp)
        self.max_rotation = max(self.max_rotation, dr)
        self.samples.append(T.copy())
        self.times.append(captured)
        self.frames.append(frame)
        return self.ready

    def reject(self, reason):
        self.rejections[reason] += 1
        self.reset(reason)
        return False

    @property
    def ready(self):
        return (len(self.samples) >= self.c['stable_frames']
                and self.times[-1] - self.times[0] >= self.c['stable_observation_s'])

    def summary(self):
        data = dict(ready=self.ready, stable_samples=len(self.samples),
                    stable_duration_s=self.times[-1] - self.times[0] if self.times else 0.0,
                    reset_counts=dict(self.resets), rejection_counts=dict(self.rejections),
                    absolute_accuracy_validated=False)
        if not self.samples:
            return data
        answer = np.eye(4)
        answer[:3, 3] = np.median([s[:3, 3] for s in self.samples], axis=0)
        u, _, vt = np.linalg.svd(sum(s[:3, :3] for s in self.samples))
        answer[:3, :3] = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
        dp = np.array([np.linalg.norm(s[:3, 3] - answer[:3, 3]) for s in self.samples])
        dr = np.array([rotation_distance(answer[:3, :3], s[:3, :3]) for s in self.samples])
        data.update(T_camera_mesh=answer.tolist(), first_frame=self.frames[0], last_frame=self.frames[-1],
                    position_pairwise_max_mm=self.max_position * 1000,
                    rotation_pairwise_max_deg=float(np.degrees(self.max_rotation)),
                    position_to_final_p95_mm=float(np.percentile(dp, 95) * 1000),
                    position_to_final_max_mm=float(dp.max() * 1000),
                    rotation_to_final_p95_deg=float(np.degrees(np.percentile(dr, 95))),
                    rotation_to_final_max_deg=float(np.degrees(dr.max())),
                    position_axis_std_mm=(np.std([s[:3, 3] for s in self.samples], axis=0) * 1000).tolist())
        return data
