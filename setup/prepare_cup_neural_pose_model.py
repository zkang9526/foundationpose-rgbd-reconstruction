#!/usr/bin/env python3
"""Bake a verified neural SDF surface and learned colors for FoundationPose.

The online renderer remains the official triangle renderer, as in the public
model-free entry. No previous TSDF mesh or new pose-network training is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--field',type=Path,required=True,help='fit directory with config, report, checkpoint and SDF surfaces')
    parser.add_argument('--field-repo',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--memory-fraction', type=float, default=.20)
    args=parser.parse_args()
    if not 0 < args.memory_fraction <= 1:
        parser.error('Memory fraction must be in (0,1]')
    args.output.mkdir(parents=True,exist_ok=False)
    report=dict(passed=False,status='validating',geometry_quality_accepted=False,
                backend='neural_field_surface_foundationpose',direct_neural_renderer=False,
                pose_is_ground_truth=False,pose_definition='T_camera_from_field_object_meters',
                source_field=str(args.field),online_unit='m',recentered=False,rescaled=False,
                existing_tsdf_mesh_used=False)
    started=time.monotonic()
    try:
        import numpy as np
        import torch
        import trimesh
        import yaml
        sys.path[:0]=[str(args.field_repo/'bundlesdf'),str(args.field_repo)]
        from cup_neural_runtime import install_neural_cuda_aliases
        report['cuda_module_binding'] = install_neural_cuda_aliases()
        from nerf_helpers import get_embedder,NeRFSmall
        torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(args.memory_fraction)
        training=json.loads((args.field/'report.json').read_text())
        cfg=yaml.safe_load((args.field/'config.yml').read_text())
        if cfg['frame_features']!=0 or cfg['optimize_poses']!=0 or cfg['i_embed']!=1:
            raise ValueError('Adapter requires this fixed-pose Hash field without per-frame appearance codes')
        checkpoint=args.field/'model_latest.pth'
        digest=sha(checkpoint)
        if digest!=training['field_checkpoint']['sha256']:raise ValueError('Field checkpoint SHA differs')
        if not training.get('training_inputs_unchanged'):raise ValueError('Training input provenance not verified')
        metric=args.field/'surface_metric.obj';normalized=args.field/'surface_normalized.obj'
        mesh=trimesh.load(str(metric),force='mesh',process=False)
        norm=trimesh.load(str(normalized),force='mesh',process=False)
        scale=float(cfg['sc_factor']);translation=np.asarray(cfg['translation'],dtype=float)
        if not scale>0 or translation.shape!=(3,) or not np.isfinite(translation).all():raise ValueError('Invalid normalization')
        if mesh.vertices.shape!=norm.vertices.shape or not np.allclose(norm.vertices/scale-translation,mesh.vertices,atol=2e-8,rtol=0):
            raise ValueError('Metric surface does not match saved neural normalization')
        if not np.array_equal(mesh.faces,norm.faces):raise ValueError('Surface topology differs')
        if not np.isfinite(mesh.vertices).all() or np.any(mesh.extents<.001) or np.any(mesh.extents>.5):
            raise ValueError('Surface coordinates are not plausible meter-scale cup geometry')
        # Only remove isolated tiny components, preserving the field object frame.
        components=mesh.split(only_watertight=False)
        minimum=max(30,int(max(len(m.faces) for m in components)*.003))
        kept=[m for m in components if len(m.faces)>=minimum]
        report['component_cleanup']=dict(input_components=len(components),kept_components=len(kept),
                                         minimum_faces=minimum,input_faces=len(mesh.faces))
        mesh=trimesh.util.concatenate(kept)
        mesh.remove_unreferenced_vertices()
        sources=json.loads((args.field/'inputs.json').read_text())
        pose_sources={int(Path(s['path']).stem):s for s in sources
                      if Path(s['path']).suffix=='.txt' and 'estimated_camera_to_model' in s['path']}
        cameras=[]
        for i in training['train_ids']:
            info=pose_sources[i];path=Path(info['path'])
            if sha(path)!=info['sha256']:raise ValueError('Reference estimated pose changed')
            cameras.append(np.loadtxt(path)[:3,3])
        # Four most front-facing training camera directions per vertex. This is
        # static learned-color baking, not a new texture atlas or a live neural renderer.
        vertices=np.asarray(mesh.vertices);normals=np.asarray(mesh.vertex_normals)
        towards=np.asarray(cameras)[None,:,:]-vertices[:,None,:]
        towards/=np.maximum(np.linalg.norm(towards,axis=-1,keepdims=True),1e-12)
        cosine=(towards*normals[:,None,:]).sum(axis=-1)
        best=np.argsort(cosine,axis=1)[:,-4:]
        weights=np.maximum(np.take_along_axis(cosine,best,axis=1),0)**2
        weights[weights.sum(axis=1)==0]=1
        weights/=weights.sum(axis=1,keepdims=True)
        directions=-np.take_along_axis(towards,best[:,:,None],axis=1)
        embed,channels=get_embedder(cfg['multires'],cfg,i=cfg['i_embed']);embed=embed.cuda()
        view_embed,view_channels=get_embedder(cfg['multires_views'],cfg,i=cfg['i_embed_views']);view_embed=view_embed.cuda()
        model=NeRFSmall(num_layers=2,hidden_dim=64,geo_feat_dim=15,num_layers_color=3,
                        hidden_dim_color=64,input_ch=channels,input_ch_views=view_channels).cuda()
        state=torch.load(str(checkpoint),map_location='cpu')
        embed.load_state_dict(state['embed_fn'],strict=True);model.load_state_dict(state['model'],strict=True)
        view_embed.load_state_dict(state['embeddirs_fn'],strict=True)
        report['field_step']=int(state['global_step']);del state
        embed.eval();view_embed.eval();model.eval()
        colors=np.zeros((len(vertices),3),np.float32);sdf=[]
        with torch.no_grad():
            for lo in range(0,len(vertices),4096):
                hi=min(lo+4096,len(vertices))
                xyz=torch.as_tensor((vertices[lo:hi]+translation)*scale,device='cuda',dtype=torch.float32)
                features=embed(xyz)
                for k in range(4):
                    d=torch.as_tensor(directions[lo:hi,k],device='cuda',dtype=torch.float32)
                    raw=model(torch.cat([features,view_embed(d)],dim=-1))
                    colors[lo:hi]+=torch.sigmoid(raw[:,:3]).cpu().numpy()*weights[lo:hi,k,None]
                sdf.extend(raw[:,3].abs().cpu().numpy().tolist())
        mesh.visual.vertex_colors=np.column_stack([(np.clip(colors,0,1)*255).round().astype(np.uint8),np.full(len(colors),255,np.uint8)])
        model_file=args.output/'model.obj';mesh.export(str(model_file));mesh.export(str(args.output/'model.ply'))
        # Test the serialized file that FoundationPose will actually load.
        reloaded=trimesh.load(str(model_file),force='mesh',process=False)
        if not np.allclose(reloaded.bounds,mesh.bounds,atol=2e-8,rtol=0):raise ValueError('Export changed metric coordinates')
        if reloaded.visual.kind!='vertex' or np.ptp(np.asarray(reloaded.visual.vertex_colors)[:,:3])<10:
            raise ValueError('Learned vertex colors absent after OBJ reload')
        report.update(passed=True,status='prepared_candidate_not_accuracy_acceptance',
            model_file='model.obj',model_sha256=sha(model_file),vertices=len(mesh.vertices),faces=len(mesh.faces),
            extents_m=mesh.extents.tolist(),visual_kind=reloaded.visual.kind,
            surface_from_field_object=np.eye(4).tolist(),
            learned_color_baking='Four front-facing training camera directions; angular weighted learned RGB at SDF surface vertices',
            median_abs_raw_sdf_at_vertices=float(np.median(sdf)),raw_sdf_is_metric_distance=False,
            source_checkpoint_sha256=digest,source_metric_surface_sha256=sha(metric),
            source_normalized_surface_sha256=sha(normalized),source_config_sha256=sha(args.field/'config.yml'),
            training_report_sha256=sha(args.field/'report.json'),
            source_manifest_sha256=sha(args.field.parent/'source_manifest.json'),
            source_training_ids=training['train_ids'],reserved_view_ids=training['validation_ids'],
            scripts={Path(__file__).name:sha(Path(__file__))},elapsed_seconds=time.monotonic()-started)
    except Exception as error:
        report.update(status='failed',error=str(error),traceback=traceback.format_exc());traceback.print_exc()
    finally:
        (args.output/'manifest.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
