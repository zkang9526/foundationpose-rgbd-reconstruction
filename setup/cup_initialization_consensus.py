"""Conservative, same-frame consensus of nearby registration candidates."""
import time

import cv2
import numpy as np


def rotation_difference_degrees(first, second):
    cosine = (np.trace(first @ second.T) - 1.) / 2.
    return float(np.degrees(np.arccos(np.clip(cosine, -1., 1.))))


def registration_consensus(candidates, selected, raw_mm, mask, K, projection, center_offset):
    """Average only one tight candidate mode and validate it on the same RGB-D.

    Translations refer to the physical body center. The returned transform keeps
    the original Mesh origin. No earlier session or pose is used as a prior.
    """
    started = time.monotonic()
    original = np.asarray(selected['pose'], dtype=float)
    limits = dict(pair_translation_m=.002, pair_rotation_deg=3.,
                  max_iou_loss=.001, max_median_depth_increase_m=.0001,
                  max_mean_depth_increase_m=.00005, min_coverage=.99)
    metadata = dict(method='same-frame close-mode registration consensus', accepted=False,
                    physical_accuracy_validated=False, source_rank=selected['rank'], limits=limits)

    def finish(reason, pose=original):
        metadata.update(reason=reason, seconds=time.monotonic()-started)
        return pose.copy(), metadata

    eligible = [candidate for candidate in candidates
                if candidate['overlap']['consistent']
                and candidate['depth_quality']['heuristic_consistent']
                and candidate['selection_metric'] >= selected['selection_metric']-.015]
    metadata['candidate_ranks'] = sorted(candidate['rank'] for candidate in eligible)
    if len(eligible) < 3 or selected not in eligible:
        return finish('fewer than three admissible candidates including the source')
    poses = np.asarray([candidate['pose'] for candidate in eligible], dtype=float)
    offset = np.asarray(center_offset, dtype=float)
    if poses.shape != (len(eligible), 4, 4) or offset.shape != (3,) or not np.isfinite(poses).all() or not np.isfinite(offset).all():
        return finish('invalid candidate or body-center data')
    rotations = poses[:, :3, :3]
    if (not np.allclose(poses[:, 3], [0., 0., 0., 1.], atol=1e-6)
            or not np.allclose(rotations @ rotations.transpose(0, 2, 1), np.eye(3), atol=1e-4)
            or np.any(np.abs(np.linalg.det(rotations)-1.) > 1e-4)):
        return finish('candidate is not a rigid transform')
    centers = rotations @ offset + poses[:, :3, 3]
    pair_translation = max(float(np.linalg.norm(first-second)) for first in centers for second in centers)
    pair_rotation = max(rotation_difference_degrees(first, second) for first in rotations for second in rotations)
    metadata.update(pair_translation_m=pair_translation, pair_rotation_deg=pair_rotation)
    if pair_translation > limits['pair_translation_m'] or pair_rotation > limits['pair_rotation_deg']:
        return finish('candidates contain separated pose modes')
    # Polar mean on SO(3). Averaging Euler angles can wrap at +/-180 degrees.
    left, _, right = np.linalg.svd(np.sum(rotations, axis=0))
    correction = np.diag([1., 1., np.linalg.det(left @ right)])
    rotation = left @ correction @ right
    center = np.median(centers, axis=0)
    consensus = np.eye(4)
    consensus[:3, :3] = rotation
    consensus[:3, 3] = center-rotation @ offset
    metadata['proposed_pose'] = consensus.tolist()
    metadata['center_correction_m'] = float(np.linalg.norm(center-(original[:3, :3] @ offset+original[:3, 3])))
    metadata['rotation_correction_deg'] = rotation_difference_degrees(rotation, original[:3, :3])

    raw = np.asarray(raw_mm)
    binary = np.asarray(mask, dtype=bool)
    target = raw.astype(float)*.001
    baseline = projection.render_depth(original, K, raw.shape)
    proposed = projection.render_depth(consensus, K, raw.shape)
    interior = cv2.erode(binary.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    local_min = cv2.erode(target.astype(np.float32), np.ones((3, 3), np.uint8))
    local_max = cv2.dilate(target.astype(np.float32), np.ones((3, 3), np.uint8))
    support = interior & (local_min > 0.) & (local_max-local_min < .008) & (baseline > 0.)
    support_count = int(np.count_nonzero(support))
    metadata['depth_support_pixels'] = support_count
    if support_count < 300:
        return finish('insufficient reliable interior depth')

    def quality(render):
        silhouette = render > 0.
        visible = silhouette[support]
        residual = np.full(support_count, .02)
        residual[visible] = np.minimum(np.abs(render[support][visible]-target[support][visible]), .02)
        return dict(iou=float(np.count_nonzero(silhouette & binary)/max(1, np.count_nonzero(silhouette | binary))),
                    coverage=float(np.mean(visible)),
                    median_abs_depth_m=float(np.median(residual)), mean_abs_depth_m=float(np.mean(residual)))

    before, after = quality(baseline), quality(proposed)
    metadata.update(before=before, after=after)
    if (after['iou'] < before['iou']-limits['max_iou_loss'] or after['coverage'] < limits['min_coverage']
            or after['median_abs_depth_m'] > before['median_abs_depth_m']+limits['max_median_depth_increase_m']
            or after['mean_abs_depth_m'] > before['mean_abs_depth_m']+limits['max_mean_depth_increase_m']):
        return finish('consensus failed silhouette/depth validation')
    metadata['accepted'] = True
    return finish('one tight candidate mode passed same-frame validation', consensus)
