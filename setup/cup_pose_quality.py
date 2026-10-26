#!/usr/bin/env python3
"""Fast original-mesh GPU silhouette/depth; consistency checks are never pose GT."""
import numpy as np


class MeshProjection:
    def __init__(self, mesh, context):
        from Utils import make_mesh_tensors
        self.tensors = make_mesh_tensors(mesh.copy())
        self.context = context

    def render_depth(self, pose, K, shape):
        import torch
        from Utils import nvdiffrast_render
        with torch.inference_mode():
            _, depth, _ = nvdiffrast_render(K=K, H=shape[0], W=shape[1],
                ob_in_cams=torch.as_tensor(pose, device='cuda', dtype=torch.float32)[None],
                glctx=self.context, mesh_tensors=self.tensors, extra={})
            return depth[0].detach().cpu().numpy()


def depth_consistency(predicted, measured_mm):
    silhouette = predicted > 0
    common = silhouette & (measured_mm > 0)
    count = int(silhouette.sum())
    valid = int(common.sum())
    residual = np.abs(predicted[common] - measured_mm[common].astype(np.float32) * 0.001)
    median = float(np.median(residual)) if valid else None
    within = float(np.mean(residual < 0.030)) if valid else 0.0
    # Heuristics in meters, deliberately named consistency rather than confidence.
    consistent = count >= 200 and valid >= 100 and valid / max(1, count) >= .20 and median <= .040 and within >= .40
    return dict(rendered_pixels=count, valid_measured_pixels=valid,
                valid_measured_fraction=valid / max(1, count), median_abs_depth_residual_m=median,
                p90_abs_depth_residual_m=float(np.percentile(residual, 90)) if valid else None,
                depth_agreement_fraction_30mm=within, heuristic_consistent=bool(consistent),
                thresholds=dict(min_pixels=200, min_valid_pixels=100, min_valid_fraction=.20,
                                max_median_residual_m=.040, min_fraction_under_30mm=.40),
                is_calibrated_probability=False, pose_accuracy_validated=False)


def image_change(old_rgb, latest_rgb, target_mask):
    selected = target_mask > 0
    if int(selected.sum()) < 100:
        return dict(consistent=False, median_absolute_rgb_difference=None)
    differences = np.mean(np.abs(old_rgb.astype(np.float32) - latest_rgb.astype(np.float32)), axis=2)
    median = float(np.median(differences[selected]))
    return dict(consistent=median <= 25.0, median_absolute_rgb_difference=median,
                threshold=25.0, scope='same-pixel masked appearance heuristic; not pose accuracy')
