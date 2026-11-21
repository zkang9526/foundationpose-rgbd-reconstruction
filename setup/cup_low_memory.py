"""Inference batching for a 4 GiB GPU, preserving global candidate scoring."""
import functools


def install_bounded_diameter(block_size=128):
    import numpy as np
    import Utils
    original = Utils.compute_mesh_diameter

    @functools.wraps(original)
    def diameter(model_pts=None, mesh=None, n_sample=1000):
        if mesh is not None:
            return original(model_pts=model_pts, mesh=mesh, n_sample=n_sample)
        points = model_pts
        if n_sample is not None:
            ids = np.random.choice(len(points), size=min(n_sample, len(points)), replace=False)
            points = points[ids]
        maximum = None
        for start in range(0, len(points), block_size):
            distances = np.linalg.norm(points[None] - points[start:start+block_size, None], axis=-1)
            maximum = distances.max() if maximum is None else np.maximum(maximum, distances.max())
        return maximum

    Utils.compute_mesh_diameter = diameter
    return dict(diameter_block_size=block_size, diameter_sample_count_unchanged=True)


def install_render_batches(batch_size=8):
    import inspect
    import torch
    import Utils
    original = Utils.nvdiffrast_render
    signature = inspect.signature(original)

    @functools.wraps(original)
    def render(*args, **kwargs):
        values = dict(signature.bind_partial(*args, **kwargs).arguments)
        poses = values.get('ob_in_cams')
        if torch.is_grad_enabled() or poses is None or len(poses) <= batch_size:
            return original(*args, **kwargs)
        rendered, extra_parts = [], []
        for start in range(0, len(poses), batch_size):
            part = dict(values, ob_in_cams=poses[start:start+batch_size], extra={})
            if values.get('bbox2d') is not None:
                part['bbox2d'] = values['bbox2d'][start:start+batch_size]
            rendered.append(original(**part))
            extra_parts.append(part['extra']['xyz_map'])
        if 'extra' in values:
            values['extra']['xyz_map'] = torch.cat(extra_parts, dim=0)
        return tuple(torch.cat([part[index] for part in rendered], dim=0)
                     if rendered[0][index] is not None else None for index in range(3))

    Utils.nvdiffrast_render = render
    return dict(render_batch_size=batch_size, render_candidate_order_unchanged=True)


def install_feature_batches(scorer, refiner, batch_size=8):
    import torch
    if scorer.model.training or refiner.model.training:
        raise ValueError('Low-memory batching requires evaluation-mode networks')
    refine_forward = refiner.model.forward
    score_features = scorer.model.extract_feat

    @functools.wraps(refine_forward)
    def refine(A, B):
        if torch.is_grad_enabled() or len(A) <= batch_size:
            return refine_forward(A, B)
        parts = [refine_forward(A[start:start+batch_size], B[start:start+batch_size])
                 for start in range(0, len(A), batch_size)]
        return {key: torch.cat([part[key] for part in parts], dim=0) for key in parts[0]}

    @functools.wraps(score_features)
    def features(A, B):
        if torch.is_grad_enabled() or len(A) <= batch_size:
            return score_features(A, B)
        return torch.cat([score_features(A[start:start+batch_size], B[start:start+batch_size])
                          for start in range(0, len(A), batch_size)], dim=0)

    refiner.model.forward = refine
    scorer.model.extract_feat = features
    return dict(feature_batch_size=batch_size, candidate_count_unchanged=True,
                score_cross_candidate_attention_unchanged=True,
                refinement_iterations_unchanged=True)
