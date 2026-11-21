"""Opt-in verified mask-hole ray sampling using existing SDF free-space targets."""
import numpy as np


def verified_hole_ray_ids(nerf, raw_depths, fraction):
    import cv2
    import torch
    from cup_handle_local_selection import handle_region
    if not 0 < fraction <= .5:
        raise ValueError('Hole ray fraction must be in (0,.5]')
    rays = nerf.rays.detach().cpu().numpy()
    frame_ids = np.rint(rays[:, nerf.ray_frame_id_slice]).astype(int)
    directions = rays[:, nerf.ray_dir_slice]
    z = -directions[:, 2]
    us = np.rint(nerf.K[0, 2]+nerf.K[0, 0]*directions[:, 0]/z).astype(int)
    vs = np.rint(nerf.K[1, 2]-nerf.K[1, 1]*directions[:, 1]/z).astype(int)
    if (np.any(us < 0) or np.any(us >= nerf.W) or np.any(vs < 0) or np.any(vs >= nerf.H)):
        raise ValueError('Training ray-to-pixel mapping is outside the input frame')
    selected = np.zeros(len(rays), bool)
    rows = []
    scale = float(nerf.cfg['sc_factor'])
    for frame_id, depth in enumerate(raw_depths):
        mask = nerf.masks[frame_id, ..., 0] > 0
        reference = handle_region(mask)
        if reference is None:
            rows.append(dict(frame=frame_id, hole_core_pixels=0, protected_rays=0))
            continue
        core = cv2.erode(reference['hole'].astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        stride = int(nerf.cfg.get('down_scale_ratio', 1))
        raw = depth[::stride, ::stride]
        if raw.shape != (nerf.H, nerf.W):
            raise ValueError('Raw background depth does not match the training pixel stride')
        ids = np.flatnonzero(frame_ids == frame_id)
        observed = raw[vs[ids], us[ids]].astype(np.float32)*.001
        # The upstream far column is the object-box exit in normalized camera Z.
        exit_depth = rays[ids, nerf.ray_far_slice]/scale
        safe = (core[vs[ids], us[ids]] & (observed > 0) & (observed > exit_depth+.005)
                & (rays[ids, nerf.ray_mask_slice] == 0)
                & (rays[ids, nerf.ray_type_slice] == 0)
                & (rays[ids, nerf.ray_depth_slice] > nerf.cfg['far']*scale))
        selected[ids[safe]] = True
        rows.append(dict(frame=frame_id, hole_core_pixels=int(core.sum()), protected_rays=int(safe.sum())))
    ids = np.flatnonzero(selected)
    report = dict(enabled=bool(len(ids)), pool_rays=len(ids), total_rays=len(rays),
        requested_fraction=fraction, frames=rows, erode_pixels=2, background_margin_m=.005,
        supervision='Original BAD_DEPTH free-space targets retained; raw background depth used only for screening')
    return torch.as_tensor(ids, dtype=torch.long, device=nerf.rays.device), report


class HoleRayLoader:
    def __init__(self, nerf, raw_depths, fraction):
        import torch
        if nerf.cfg['N_rand'] < 2:
            raise ValueError('Hole sampling requires at least2 rays per batch')
        self.hole_ids, self.report = verified_hole_ray_ids(nerf, raw_depths, fraction)
        if len(self.hole_ids) < 8:
            raise ValueError('Fewer than8 protected hole rays; inspect raw depth and mask before training')
        self.hole_batch = min(nerf.cfg['N_rand']//2, max(1, int(round(nerf.cfg['N_rand']*fraction))))
        self.ordinary_batch = nerf.cfg['N_rand']-self.hole_batch
        self.ordinary = type(nerf.data_loader)(nerf.rays, self.ordinary_batch)
        self.rays = nerf.rays
        self.generator = torch.Generator(device='cpu').manual_seed(137)
        self.report.update(hole_rays_per_batch=self.hole_batch, ordinary_rays_per_batch=self.ordinary_batch,
                           batches=0, sampled_hole_rays=0, sampled_ordinary_rays=0)

    def __next__(self):
        import torch
        normal = next(self.ordinary)
        choices = torch.randint(len(self.hole_ids), (self.hole_batch,), generator=self.generator)
        extra = self.rays[self.hole_ids[choices.to(self.hole_ids.device)]]
        self.report['batches'] += 1
        self.report['sampled_hole_rays'] += self.hole_batch
        self.report['sampled_ordinary_rays'] += self.ordinary_batch
        return torch.cat([normal, extra], dim=0)
