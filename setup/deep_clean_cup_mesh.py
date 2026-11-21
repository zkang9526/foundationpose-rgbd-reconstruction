#!/usr/bin/env python3
"""Depth-supported trimming and stronger mesh denoising, never fit scale to dimensions."""
import argparse,copy,hashlib,json,sys,time
from pathlib import Path
import cv2
import numpy as np
import open3d as o3d
from clean_and_measure_cup_mesh import topology,profile,write_mesh,distance_summary
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def render(mesh,K,T):
    scene=o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    rays=o3d.t.geometry.RaycastingScene.create_rays_pinhole(
       intrinsic_matrix=o3d.core.Tensor(K),extrinsic_matrix=o3d.core.Tensor(np.linalg.inv(T)),
       width_px=640,height_px=480)
    return scene.cast_rays(rays,nthreads=2)['t_hit'].numpy()

def observations(scene_dir,pose_dir):
    rows=[]
    for frame in range(72):
        stem='%06d'%frame
        rows.append((np.loadtxt(pose_dir/(stem+'.txt')),
          cv2.imread(str(scene_dir/'masks'/(stem+'.png')),-1)>0,
          cv2.imread(str(scene_dir/'depth'/(stem+'.png')),-1).astype(np.float32)/1000))
    return rows

def vertex_support(mesh,K,obs):
    points=np.asarray(mesh.vertices)
    visible=np.zeros(len(points),np.int32);support=visible.copy();contradiction=visible.copy();outside=visible.copy()
    for frame,(T,mask,depth) in enumerate(obs):
        inv=np.linalg.inv(T);pc=points@inv[:3,:3].T+inv[:3,3]
        uv=np.rint((pc@K.T)[:,:2]/pc[:,2,None]).astype(int)
        inside=(pc[:,2]>0)&(uv[:,0]>=1)&(uv[:,0]<639)&(uv[:,1]>=1)&(uv[:,1]<479)
        ids=np.flatnonzero(inside);u=uv[ids,0];v=uv[ids,1];z=pc[ids,2]
        rendered=render(mesh,K,T)
        seen=(~np.isfinite(rendered[v,u]))|(z<=rendered[v,u]+.003)
        ids=ids[seen];u=u[seen];v=v[seen];z=z[seen]
        visible[ids]+=1
        near_mask=cv2.dilate(mask.astype(np.uint8),np.ones((5,5),np.uint8))>0
        outside[ids]+=~near_mask[v,u]
        best=np.full(len(ids),np.inf);anydepth=np.zeros(len(ids),bool);front_bad=np.ones(len(ids),bool)
        for dy in [-1,0,1]:
            for dx in [-1,0,1]:
                d=depth[v+dy,u+dx];valid=d>0
                best=np.minimum(best,np.where(valid,np.abs(d-z),np.inf))
                anydepth|=valid
                front_bad&=(~valid)|(z<d-.008)
        support[ids]+=(best<=.004)&near_mask[v,u]
        contradiction[ids]+=(~near_mask[v,u])|(anydepth&front_bad)
    return visible,support,contradiction,outside

def filter_mesh(base,bad,iterations,cap_mm,boundary_cap_mm,stem,out,handle_axis=None):
    trimmed=copy.deepcopy(base)
    trimmed.remove_vertices_by_mask(bad)
    trimmed.remove_degenerate_triangles();trimmed.remove_duplicated_triangles();trimmed.remove_unreferenced_vertices()
    labels,sizes,_=trimmed.cluster_connected_triangles();labels=np.asarray(labels);sizes=np.asarray(sizes)
    # Only tiny remnants. A detached handle-sized component is retained.
    fragment_mask=sizes[labels]<60
    fragments=int(fragment_mask.sum())
    if fragments:
        trimmed.remove_triangles_by_mask(fragment_mask);trimmed.remove_unreferenced_vertices()
    before,boundary=topology(trimmed)
    v0=np.asarray(trimmed.vertices).copy()
    smooth=trimmed.filter_smooth_taubin(number_of_iterations=iterations,lambda_filter=.5,mu=-.53,
                                      filter_scope=o3d.geometry.FilterScope.Vertex)
    delta=np.asarray(smooth.vertices)-v0
    limits=np.full(len(v0),cap_mm/1000)
    limits[boundary]=boundary_cap_mm/1000
    # Extra protection for the narrow handle.
    limits[np.linalg.norm(v0[:,:2],axis=1)>.05]=np.minimum(limits[np.linalg.norm(v0[:,:2],axis=1)>.05],.001)
    norms=np.linalg.norm(delta,axis=1)
    delta*=np.minimum(1,limits/np.maximum(norms,1e-20))[:,None]
    protected_vertices=0
    if handle_axis is not None:
        radial=np.linalg.norm(v0[:,:2],axis=1)
        cosine=(v0[:,:2]@handle_axis)/np.maximum(radial,1e-12)
        strength=np.clip((radial-.035)/.008,0,1)*np.clip((cosine-.5)/(.70710678-.5),0,1)
        delta*=(1-strength[:,None])
        protected_vertices=int((strength>.999).sum())
        # Use the observed model envelope only; never the manual dimensions.
        vertices=v0+delta
        vertices=np.clip(vertices,np.asarray(base.vertices).min(axis=0),np.asarray(base.vertices).max(axis=0))
        delta=vertices-v0
    smooth.vertices=o3d.utility.Vector3dVector(v0+delta)
    smooth.vertex_colors=copy.deepcopy(trimmed.vertex_colors);smooth.compute_vertex_normals()
    after,_=topology(smooth)
    assert np.isfinite(np.asarray(smooth.vertices)).all()
    assert np.array_equal(np.asarray(smooth.triangles),np.asarray(trimmed.triangles))
    assert np.linalg.norm(delta,axis=1).max()<=cap_mm/1000+1e-10
    assert after['nonmanifold_edges']==0
    write_mesh(smooth,out,stem)
    motion=np.linalg.norm(delta,axis=1)*1000
    return smooth,dict(unsupported_vertices_removed=int(bad.sum()),tiny_fragment_faces_removed=fragments,
      vertices_before=len(base.vertices),faces_before=len(base.triangles),trimmed=before,final=after,
      smoothing=dict(iterations=iterations,fully_protected_handle_vertices=protected_vertices,original_envelope_guard=handle_axis is not None,max_interior_mm=cap_mm,max_boundary_mm=boundary_cap_mm,
                     max_handle_mm=1.,median_displacement_mm=float(np.median(motion)),
                     p95_displacement_mm=float(np.percentile(motion,95)),max_displacement_mm=float(motion.max())))

def measure(mesh,axis,manual):
    v=np.asarray(mesh.vertices)*1000
    sections=profile(mesh);valid=[s for s in sections if s['angular_bins_of_24']>=18]
    d=dict(height=float(np.ptp(v[:,2])),body_diameter=max(s['diameter_mm'] for s in valid),
           width_including_handle=float(np.ptp(v[:,:2]@axis)))
    return dict(dimensions_mm=d,signed_difference_from_approximate_manual_mm={k:d[k]-manual[k] for k in d},
                body_sections=sections)

def evaluate(candidates,K,obs,base_depths):
    yy,xx=np.indices((480,640));pixel=np.stack([(xx+.5-K[0,2])/K[0,0],(yy+.5-K[1,2])/K[1,1],np.ones_like(xx)],axis=-1)
    results={}
    for name,mesh in candidates.items():
        rows=[]
        for i,(T,target,measured) in enumerate(obs):
            depth=base_depths[i] if name=='light_baseline' else render(mesh,K,T)
            pred=np.isfinite(depth)&(depth>0)
            overlap=pred&target&(measured>0)
            residual=np.abs(depth[overlap]-measured[overlap])*1000
            basez=base_depths[i]
            cam_points=pixel*np.where(np.isfinite(basez),basez,0)[...,None]
            model=cam_points@T[:3,:3].T+T[:3,3]
            handle=target&np.isfinite(basez)&(np.linalg.norm(model[...,:2],axis=-1)>.05)
            rows.append(dict(frame=i,mask_iou=float((pred&target).sum()/max(1,(pred|target).sum())),
                             depth_median_mm=float(np.median(residual)),handle_reference_pixels=int(handle.sum()),
                             handle_reference_recall=float((pred&handle).sum()/max(1,handle.sum()))))
        valid=[r for r in rows if r['handle_reference_pixels']>=20]
        results[name]=dict(mean_mask_iou=float(np.mean([r['mask_iou'] for r in rows])),
            median_frame_depth_residual_mm=float(np.median([r['depth_median_mm'] for r in rows])),
            mean_handle_reference_recall=float(np.mean([r['handle_reference_recall'] for r in valid])),
            handle_views=len(valid),frames=rows)
    return results

def plot(meshes,names,path):
    points=np.concatenate([np.asarray(m.vertices)*1000 for m in meshes])
    center=(points.min(axis=0)+points.max(axis=0))/2;half=np.ptp(points,axis=0).max()*.54
    light=np.array([-.4,-.6,1.]);light/=np.linalg.norm(light)
    fig=plt.figure(figsize=(15,12))
    for row,(m,name) in enumerate(zip(meshes,names)):
        m.compute_triangle_normals();v=np.asarray(m.vertices)*1000;f=np.asarray(m.triangles)
        shade=.25+.7*np.abs(np.asarray(m.triangle_normals)@light);colors=shade[:,None]*np.array([.7,.79,.85])
        for col,azim in enumerate([-130,-30,70]):
            ax=fig.add_subplot(len(meshes),3,row*3+col+1,projection='3d')
            ax.add_collection3d(Poly3DCollection(v[f],facecolors=colors,edgecolors='none',linewidths=0))
            ax.set_xlim(center[0]-half,center[0]+half);ax.set_ylim(center[1]-half,center[1]+half);ax.set_zlim(center[2]-half,center[2]+half)
            ax.set_box_aspect([1,1,1]);ax.set_proj_type('ortho');ax.view_init(elev=22,azim=azim);ax.set_axis_off()
            ax.set_title(name+' | '+str(azim)+' deg',fontsize=11)
    fig.suptitle('Stronger cup cleanup | same scale, cameras and shading',fontsize=15)
    fig.text(.5,.02,'No rescaling or clipping to manual dimensions | all candidates retained | observation consistency is not ground truth',ha='center',fontsize=10)
    fig.subplots_adjust(left=0,right=1,bottom=.06,top=.94,wspace=0,hspace=.02)
    fig.savefig(path,dpi=130);plt.close(fig)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['mesh','scene','poses','semantic','output']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    baseline=o3d.io.read_triangle_mesh(str(a.mesh))
    K=np.loadtxt(a.scene/'K.txt');obs=observations(a.scene,a.poses)
    source_files=[a.mesh,a.semantic,a.scene/'K.txt']
    for folder,suffix in [('rgb','.png'),('depth','.png'),('masks','.png')]:
        source_files += [a.scene/folder/('%06d'%i+suffix) for i in range(72)]
    source_files += [a.poses/('%06d.txt'%i) for i in range(72)]
    evidence={str(q):sha(q) for q in source_files}
    semantic=json.loads(a.semantic.read_text())
    axis=np.asarray(semantic['handle_axis_xy']);manual=semantic['manual_mm']
    visible,support,bad,outside=vertex_support(baseline,K,obs)
    np.savez_compressed(a.output/'vertex_evidence.npz',visible=visible,support=support,contradiction=bad,outside_mask=outside)
    ratio=bad/np.maximum(visible,1)
    settings={'supported_filter':((visible>=6)&(support<2)&(ratio>.65),12,1.,.5),
              'deep_filter':((visible>=6)&(support<3)&(ratio>.50),30,2.,1.)}
    xy=np.asarray(baseline.vertices)[:,:2]
    radial=np.linalg.norm(xy,axis=1)
    cosine=(xy@axis)/np.maximum(radial,1e-12)
    handle_region=(radial>.036)&(cosine>.5)
    settings['protected_deep']=(((visible>=6)&(support<3)&(ratio>.50)&~handle_region),30,2.,1.)
    candidates={'light_baseline':baseline};processing={}
    for name,(remove,iterations,cap,bcap) in settings.items():
        m,info=filter_mesh(baseline,remove,iterations,cap,bcap,name,a.output,
                          handle_axis=axis if name=='protected_deep' else None)
        assert len(m.triangles)>.85*len(baseline.triangles), 'Unexpectedly large removal'
        candidates[name]=m;processing[name]=info
    base_depths=[render(baseline,K,T) for T,_,_ in obs]
    evaluation=evaluate(candidates,K,obs,base_depths)
    gate={}
    ref=evaluation['light_baseline']
    for name in settings:
        x=evaluation[name]
        gate[name]=dict(iou_drop=x['mean_mask_iou']-ref['mean_mask_iou'],
          depth_change_mm=x['median_frame_depth_residual_mm']-ref['median_frame_depth_residual_mm'],
          handle_recall=x['mean_handle_reference_recall'],
          passed=x['mean_mask_iou']>=ref['mean_mask_iou']-.005 and
                 x['median_frame_depth_residual_mm']<=ref['median_frame_depth_residual_mm']+.5 and
                 x['mean_handle_reference_recall']>=.98)
    selected=next((name for name in ['protected_deep','deep_filter','supported_filter'] if gate[name]['passed']),'light_baseline')
    measures={name:measure(mesh,axis,manual) for name,mesh in candidates.items()}
    plot([baseline,candidates['deep_filter'],candidates['protected_deep']],
         ['Previous light cleanup','Strong trim without handle guard','Strong filter with handle guard'],a.output/'comparison.png')
    selected_mesh=candidates[selected]
    write_mesh(selected_mesh,a.output,'cup_deep_clean_selected')
    o3d.utility.random.seed(20261105)
    sample=np.asarray(selected_mesh.sample_points_uniformly(number_of_points=50000).points)
    change=distance_summary(sample,baseline)
    report=dict(status='complete_stronger_cleanup_candidates',selected=selected,manual_dimensions_used_to_filter=False,
     source_files_sha256=evidence,source_mesh_sha256=sha(a.mesh),settings=dict(depth_support_tolerance_mm=4,front_contradiction_mm=8,
      visibility_tolerance_mm=3,mask_dilation_pixels=5,depth_neighborhood_pixels=3,
      supported_filter=dict(min_visible_views=6,max_support_views_exclusive=2,min_contradiction_ratio_exclusive=.65),
      deep_filter=dict(min_visible_views=6,max_support_views_exclusive=3,min_contradiction_ratio_exclusive=.5)),
     vertex_support_summary=dict(visible_median=float(np.median(visible)),support_median=float(np.median(support)),
                                candidates_without_support=int((support==0).sum())),
     processing=processing,measurements=measures,evaluation=evaluation,acceptance=gate,
     selected_surface_change_to_light_baseline_mm=change,scale_changed=False,hole_filling=False,
     original_sources_unchanged=all(sha(Path(path))==digest for path,digest in evidence.items()),
     production_model_replaced=False,elapsed_seconds=time.monotonic()-start,
     limitations=['Support tests use the same estimated ICP poses and reference views, not independent GT.',
       'Trimming can remove plausible but poorly observed surfaces; both candidates and evidence are retained.',
       'Depth-supported geometry deletion may open boundaries; smoothing alone preserves retained connectivity.',
       'Manual sizes are approximate; height is an axial envelope, diameter is sampled-section fit, width uses fixed handle direction.'])
    assert report['original_sources_unchanged']
    report['artifacts']=[dict(name=q.name,bytes=q.stat().st_size,sha256=sha(q)) for q in a.output.iterdir() if q.is_file()]
    with (a.output/'report.json').open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(dict(selected=selected,processing=processing,
      dimensions={n:x['dimensions_mm'] for n,x in measures.items()},
      metrics={n:{k:v for k,v in x.items() if k!='frames'} for n,x in evaluation.items()},
      acceptance=gate,elapsed_seconds=report['elapsed_seconds'])),flush=True)

if __name__=='__main__':main()
