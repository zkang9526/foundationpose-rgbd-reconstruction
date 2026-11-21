#!/usr/bin/env python3
"""Reload a saved field and render held-out views by SDF zero crossings.

Upstream raw2outputs uses observed depth for its color weights. To avoid leaking
validation depth, query the learned SDF/color directly along ordered rays and
interpolate color and depth at the first zero crossing instead.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['repo','fit','scene','poses','output']:
        p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--memory-fraction', type=float, default=.23)
    a=p.parse_args()
    if not 0 < a.memory_fraction <= 1:
        p.error('Memory fraction must be in (0,1]')
    a.output.mkdir(exist_ok=False)
    sys.path[:0]=[str(a.repo/'bundlesdf'),str(a.repo)]
    import numpy as np
    import cv2
    import torch
    import yaml
    from cup_neural_runtime import install_neural_cuda_aliases
    cuda_module_binding = install_neural_cuda_aliases()
    import run_nerf as api
    start=time.monotonic()
    torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(a.memory_fraction)
    previous=json.loads((a.fit/'report.json').read_text())
    cfg=yaml.safe_load((a.fit/'config.yml').read_text())
    cfg['save_dir']=str(a.output)
    cfg['save_octree_clouds']=False
    K=np.loadtxt(a.scene/'K.txt')
    rgbs=[];depths=[];masks=[];poses=[]
    for i in range(72):
        stem='%06d'%i
        rgbs.append(cv2.cvtColor(cv2.imread(str(a.scene/'rgb'/(stem+'.png'))),cv2.COLOR_BGR2RGB))
        depths.append(cv2.imread(str(a.scene/'depth'/(stem+'.png')),-1).astype(np.float32)/1000)
        masks.append(cv2.imread(str(a.scene/'masks'/(stem+'.png')),-1))
        poses.append(np.loadtxt(a.poses/(stem+'.txt')))
    rgbs=np.asarray(rgbs);depths=np.asarray(depths);masks=np.asarray(masks);poses=np.asarray(poses)
    ids=previous['train_ids'];sc=cfg['sc_factor'];translation=np.asarray(cfg['translation'])
    arrays=api.preprocess_data(rgbs[ids].copy(),depths[ids].copy(),masks[ids].copy(),None,
                              poses[ids]@api.glcam_in_cvcam,sc,translation)
    cloud=api.o3d.io.read_point_cloud(str(a.fit/'pcd_normalized.ply'))
    nerf=api.NerfRunner(cfg,*arrays[:3],normal_maps=None,poses=arrays[4],K=K,build_octree_pcd=cloud)
    checkpoint=a.fit/'model_latest.pth'
    expected=previous['field_checkpoint']['sha256']
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==expected
    weights=torch.load(str(checkpoint),map_location='cpu')
    for name in ['model','embed_fn','embeddirs_fn']:
        if nerf.models[name] is not None:nerf.models[name].load_state_dict(weights[name],strict=True)
    nerf.global_step=weights['global_step'];del weights
    H,W=240,320;smallK=K.copy();smallK[:2]*=.5
    dirs=torch.tensor(api.get_camera_rays_np(H,W,smallK).reshape(-1,3),device='cuda',dtype=torch.float32)
    panels=[];stats=[]
    for frame in previous['validation_ids']:
        Tgl=poses[frame]@api.glcam_in_cvcam
        Tgl[:3,3]=(Tgl[:3,3]+translation)*sc
        transform=torch.tensor(Tgl,device='cuda',dtype=torch.float32)
        origins=transform[:3,3].expand(len(dirs),3).contiguous()
        viewdirs=dirs/dirs.norm(dim=-1,keepdim=True)
        world_dirs=(transform[:3,:3]@viewdirs.T).T.contiguous()
        level=int(np.floor(np.log2(2/(cfg['octree_raytracing_voxel_size']*sc))))
        near,far,_,intervals=nerf.octree_m.ray_trace(origins,world_dirs,level=level)
        picks=torch.nonzero((near>0).reshape(-1)).reshape(-1)
        rgb=np.zeros((H*W,3),np.float32);depth=np.zeros(H*W,np.float32)
        for lo in range(0,len(picks),256):
            pix=picks[lo:lo+256]
            directions=dirs[pix];vd=viewdirs[pix]
            with torch.no_grad():
                z,_=nerf.sample_rays_uniform_occupied_voxels(vd,intervals[pix],perturb=False,depths=None,N_samples=256)
                points=directions[:,None,:]*z[:,:,None]
                raw,_,valid=nerf.run_network(points,vd,torch.zeros(len(pix),device='cuda',dtype=torch.long),
                                            tf=transform.expand(len(pix),4,4))
                sdf=raw[...,-1]
                crosses=(sdf[:,:-1]*sdf[:,1:]<0)&valid[:,:-1]&valid[:,1:]
                first=crosses.float().argmax(dim=1)
                row=torch.arange(len(pix),device='cuda')
                s0=sdf[row,first];s1=sdf[row,first+1]
                alpha=(s0/(s0-s1+1e-12)).clamp(0,1)
                z0=z[row,first];z1=z[row,first+1]
                distance=(z0+(z1-z0)*alpha)/sc
                c0=torch.sigmoid(raw[row,first,:3]);c1=torch.sigmoid(raw[row,first+1,:3])
                colors=c0+(c1-c0)*alpha[:,None]
                good=crosses.any(dim=1)
            outpix=pix[good].cpu().numpy()
            rgb[outpix]=colors[good].cpu().numpy();depth[outpix]=distance[good].cpu().numpy()
        rgb=rgb.reshape(H,W,3);depth=depth.reshape(H,W)
        truth=cv2.resize(rgbs[frame],(W,H),interpolation=cv2.INTER_AREA)
        observed=cv2.resize(depths[frame],(W,H),interpolation=cv2.INTER_NEAREST)
        target=cv2.resize(masks[frame],(W,H),interpolation=cv2.INTER_NEAREST)>0
        predicted=depth>0;both=predicted&target&(observed>0)
        residual=np.abs(depth[both]-observed[both])*1000
        stats.append(dict(frame=frame,mask_iou=float((predicted&target).sum()/max(1,(predicted|target).sum())),
                          depth_pixels=int(both.sum()),depth_abs_median_mm=float(np.median(residual)),
                          depth_abs_p95_mm=float(np.percentile(residual,95)),render_nonzero_rgb_pixels=int((rgb.max(axis=2)>0).sum())))
        assert stats[-1]['render_nonzero_rgb_pixels']>1000
        rendered=(np.clip(rgb,0,1)*255).astype(np.uint8)
        cv2.imwrite(str(a.output/('neural_rgb_%06d.png'%frame)),cv2.cvtColor(rendered,cv2.COLOR_RGB2BGR))
        np.save(str(a.output/('neural_depth_%06d.npy'%frame)),depth)
        if frame in [3,21,39,57]:
            truth[~target]=35
            yy,xx=np.where(target|predicted)
            x0=max(0,xx.min()-15);x1=min(W,xx.max()+16)
            y0=max(0,yy.min()-15);y1=min(H,yy.max()+16)
            row=np.concatenate([cv2.resize(im[y0:y1,x0:x1],(240,240)) for im in [truth,rendered]],axis=1)
            cv2.putText(row,'View %06d: observed | neural SDF/color'%frame,(5,16),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
            panels.append(row)
    cv2.imwrite(str(a.output/'novel_views.png'),cv2.cvtColor(np.concatenate(panels),cv2.COLOR_RGB2BGR))
    report=dict(status='checkpoint_reloaded_and_12_held_out_views_rendered',checkpoint_sha256=expected,
                cuda_module_binding=cuda_module_binding,
                no_validation_rgb_depth_mask_used_in_render=True,estimated_camera_poses_used=True,
                color_render_method='Learned RGB interpolated at first learned SDF zero crossing; no observed-depth weights.',
                previous_black_rgb_preview_superseded=True,validation=stats,
                mean_mask_iou=float(np.mean([s['mask_iou'] for s in stats])),
                median_of_view_depth_medians_mm=float(np.median([s['depth_abs_median_mm'] for s in stats])),
                elapsed_seconds=time.monotonic()-start)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
