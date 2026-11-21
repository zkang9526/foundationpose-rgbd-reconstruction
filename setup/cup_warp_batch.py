"""Optional inference-only batching for Kornia's independent image warps.

This bounds temporary full-resolution grids. It does not split FoundationPose
scoring, change candidate order/count, or modify the upstream source files.
"""
import functools


def install_warp_batch_limit(limit):
    if type(limit) is not int or not 1 <= limit <= 128:
        raise ValueError('Warp batch limit must be an integer from 1 to 128')
    import torch
    import kornia.geometry.transform as transform
    original = transform.warp_perspective
    if hasattr(original, '_cup_warp_batch_limit'):
        raise RuntimeError('Warp batch limit already installed')
    counters = dict(limit=limit, calls_split=0, largest_input_batch=0)

    @functools.wraps(original)
    def bounded(src, M, *args, **kwargs):
        source, matrix = src, M
        # Preserve upstream validation and autograd for all other callers.
        if (torch.is_grad_enabled() or source.ndim != 4 or matrix.ndim != 3
                or source.shape[0] <= limit or source.shape[0] != matrix.shape[0]):
            return original(source, matrix, *args, **kwargs)
        count = source.shape[0]
        counters['calls_split'] += 1
        counters['largest_input_batch'] = max(counters['largest_input_batch'], count)
        output = None
        for start in range(0, count, limit):
            end = min(start + limit, count)
            part = original(source[start:end], matrix[start:end], *args, **kwargs)
            if output is None:
                output = part.new_empty((count,) + tuple(part.shape[1:]))
            output[start:end].copy_(part)
            del part
        return output

    bounded._cup_warp_batch_limit = limit
    transform.warp_perspective = bounded
    return counters
