"""Compare point-filtered TSDF and bounded smoothing using fixed reference poses.

These are same-view consistency checks, not independent geometry/pose accuracy.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
import open3d as o3d


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def save(mesh,path,provenance=None):
    o3d.io.write_triangle_mesh(str(path.with_suffix('.ply')),mesh)
    v,f,c=np.asarray(mesh.vertices),np.asarray(mesh.triangles),np.asarray(mesh.vertex_colors)
    with path.with_suffix('.obj').open('x') as s:
        header='meters; derived observed RGB-D mesh; no scaling or hole filling; not GT' if provenance is None else str(provenance).replace('\n',' ').replace('\r',' ')
        s.write('# '+header+'\n')
        for i,point in enumerate(v):s.write('v '+' '.join('%.12g'%x for x in np.r_[point,c[i]])+'\n')
        for face in f:s.write('f '+' '.join(str(int(x)+1) for x in face)+'\n')


def topology(mesh):
    f=np.asarray(mesh.triangles)
    e=np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1)
    e,n=np.unique(e,axis=0,return_counts=True)
    labels,counts,_=mesh.cluster_connected_triangles()
    return dict(vertices=len(mesh.vertices),faces=len(f),boundary_edges=int((n==1).sum()),
        nonmanifold_edges=int((n>2).sum()),components=len(counts),
        extents_mm=(np.ptp(np.asarray(mesh.vertices),axis=0)*1000).tolist()),np.unique(e[n==1])


def smooth(base,iterations,limit,handle_angle=None):
    info,boundary=topology(base);v=np.asarray(base.vertices).copy()
    m=base.filter_smooth_taubin(number_of_iterations=iterations,lambda_filter=.5,mu=-.53,
        filter_scope=o3d.geometry.FilterScope.Vertex)
    delta=np.asarray(m.vertices)-v
    limits=np.full(len(v),limit/1000)
    limits[np.linalg.norm(v[:,:2],axis=1)>.05]=min(limit,.75)/1000
    delta*=np.minimum(1,limits/np.maximum(np.linalg.norm(delta,axis=1),1e-20))[:,None]
    delta[boundary]=0
    if handle_angle is not None:
        radial=np.linalg.norm(v[:,:2],axis=1)
        direction=np.array([np.cos(handle_angle),np.sin(handle_angle)])
        cosine=(v[:,:2]@direction)/np.maximum(radial,1e-12)
        protection=np.clip((radial-.036)/.008,0,1)*np.clip((cosine-.5)/(.70710678-.5),0,1)
        delta*=1-protection[:,None]
    m.vertices=o3d.utility.Vector3dVector(v+delta);m.vertex_colors=copy.deepcopy(base.vertex_colors)
    m.compute_vertex_normals()
    assert np.array_equal(np.asarray(m.triangles),np.asarray(base.triangles))
    assert np.array_equal(np.asarray(m.vertices)[boundary],v[boundary])
    assert np.isfinite(np.asarray(m.vertices)).all()
    movement=np.linalg.norm(delta,axis=1)*1000
    return m,dict(iterations=iterations,boundary_vertices_pinned=len(boundary),
        displacement_mm_percentiles=np.percentile(movement,[0,50,95,100]).tolist(),
        interior_limit_mm=limit,handle_region_limit_mm=min(limit,.75),faces_unchanged=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('baseline','filtered','reproduced','scene','masks','poses','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--candidate-poses',type=Path)
    p.add_argument('--geometry-report',type=Path,help='Observed initial handle direction for additional protection')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    base=o3d.io.read_triangle_mesh(str(a.baseline));filtered=o3d.io.read_triangle_mesh(str(a.filtered))
    reproduced=o3d.io.read_triangle_mesh(str(a.reproduced))
    # The old tools must reproduce the latest input selection before any filtering comparison.
    assert len(base.vertices)==len(reproduced.vertices) and len(base.triangles)==len(reproduced.triangles)
    repro_max=float(np.max(np.abs(np.asarray(base.vertices)-np.asarray(reproduced.vertices))))
    assert repro_max<1e-7 and np.array_equal(np.asarray(base.triangles),np.asarray(reproduced.triangles))
    meshes=dict(baseline=base,point_filtered=filtered);processing={}
    handle_angle=None
    if a.geometry_report:
        geom=json.loads(a.geometry_report.read_text())
        if not geom['frames'][0]['handle_angle_observed']:raise ValueError('First handle not directly observed')
        handle_angle=geom['frames'][0]['handle_yaw_radians']
    for name,iterations,limit in [('light',3,.5),('smooth',30,2.)]:
        meshes[name],processing[name]=smooth(filtered,iterations,limit,handle_angle)
    models={}
    scenes={}
    for name,m in meshes.items():
        m.compute_vertex_normals();save(m,a.output/name)
        info,_=topology(m);models[name]=dict(topology=info,frames=[])
        scenes[name]=o3d.t.geometry.RaycastingScene()
        scenes[name].add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(m))
    K=np.loadtxt(a.scene/'K.txt');sources={str(x):sha(x) for x in (a.baseline,a.filtered,a.reproduced,a.scene/'K.txt')}
    yy,xx=np.indices((480,640));pixel=np.stack([(xx+.5-K[0,2])/K[0,0],(yy+.5-K[1,2])/K[1,1],np.ones_like(xx)],axis=-1)
    for i in range(72):
        name='%06d.png'%i;paths=[a.scene/'rgb'/name,a.scene/'depth'/name,a.masks/'masks'/name,a.poses/('%06d.txt'%i)]
        for path in paths:sources[str(path)]=sha(path)
        rgb=cv2.imread(str(paths[0]));depth=cv2.imread(str(paths[1]),-1)/1000.;target=cv2.imread(str(paths[2]),0)>0
        hsv=cv2.cvtColor(rgb,cv2.COLOR_BGR2HSV);cyan=(hsv[:,:,0]>=70)&(hsv[:,:,0]<=105)&(hsv[:,:,1]>=90)
        T=np.loadtxt(paths[3]);rays=o3d.t.geometry.RaycastingScene.create_rays_pinhole(
            intrinsic_matrix=o3d.core.Tensor(K),extrinsic_matrix=o3d.core.Tensor(np.linalg.inv(T)),width_px=640,height_px=480)
        candidate_rays=rays
        if a.candidate_poses:
            pose_path=a.candidate_poses/('%06d.txt'%i);sources[str(pose_path)]=sha(pose_path)
            candidate_rays=o3d.t.geometry.RaycastingScene.create_rays_pinhole(intrinsic_matrix=o3d.core.Tensor(K),
                extrinsic_matrix=o3d.core.Tensor(np.linalg.inv(np.loadtxt(pose_path))),width_px=640,height_px=480)
        rendered={n:scene.cast_rays(rays if n=='baseline' else candidate_rays,nthreads=2)['t_hit'].numpy() for n,scene in scenes.items()}
        z=rendered['baseline'];camera=pixel*np.where(np.isfinite(z),z,0)[...,None]
        world=camera@T[:3,:3].T+T[:3,3]
        handle_reference=target&cyan&np.isfinite(z)&(np.linalg.norm(world[...,:2],axis=-1)>.05)
        for key,z in rendered.items():
            predicted=np.isfinite(z)&(z>0);overlap=predicted&target&(depth>0)
            residual=np.abs(z[overlap]-depth[overlap])*1000
            row=dict(frame=name,mask_iou=float((predicted&target).sum()/max(1,(predicted|target).sum())),
                target_coverage=float((predicted&target).sum()/max(1,target.sum())),
                depth_residual_median_mm=float(np.median(residual)),depth_residual_p95_mm=float(np.percentile(residual,95)),
                baseline_derived_handle_pixels=int(handle_reference.sum()),
                baseline_derived_handle_coverage=float((predicted&handle_reference).sum()/max(1,handle_reference.sum())))
            models[key]['frames'].append(row)
            if i in (0,12,24,36,48,60,71):
                image=rgb.copy();image[predicted&~target]=(0,0,255);image[target&~predicted]=(0,255,0)
                cv2.imwrite(str(a.output/(key+'_projection_%06d.png'%i)),image)
        if i%12==0:print('Evaluated frames %d/72'%i,flush=True)
    for name,info in models.items():
        rows=info['frames'];h=[r for r in rows if r['baseline_derived_handle_pixels']>=20]
        info['summary']=dict(mean_mask_iou=float(np.mean([r['mask_iou'] for r in rows])),
            mean_target_coverage=float(np.mean([r['target_coverage'] for r in rows])),
            median_frame_depth_residual_mm=float(np.median([r['depth_residual_median_mm'] for r in rows])),
            median_frame_depth_p95_mm=float(np.median([r['depth_residual_p95_mm'] for r in rows])),
            mean_baseline_derived_handle_coverage=float(np.mean([r['baseline_derived_handle_coverage'] for r in h])),handle_views=len(h))
    ref=models['baseline']['summary'];acceptance={}
    for name in ('point_filtered','light','smooth'):
        s=models[name]['summary']
        acceptance[name]=dict(passed=s['mean_mask_iou']>=ref['mean_mask_iou']-.005 and
            s['median_frame_depth_residual_mm']<=ref['median_frame_depth_residual_mm']+.3 and
            s['mean_baseline_derived_handle_coverage']>=ref['mean_baseline_derived_handle_coverage']-.015 and
            s['mean_target_coverage']>=ref['mean_target_coverage']-.015)
    selected=next((n for n in ('smooth','light','point_filtered') if acceptance[n]['passed']),'baseline')
    save(meshes[selected],a.output/'cup_selected')
    report=dict(scope='Same72 reference views and estimated poses; not independent physical accuracy',
        meshes=models,processing=processing,acceptance=acceptance,numerically_selected=selected,
        requires_visual_review=True,physical_accuracy_validated=False,production_model_replaced=False,
        input_reproduction_max_vertex_difference_m=repro_max,scale_changed=False,hole_filling=False,
        handle_protection_angle_radians=handle_angle,candidate_poses_separate=a.candidate_poses is not None,
        source_files_sha256=sources,elapsed_seconds=time.monotonic()-started)
    assert all(sha(Path(path))==value for path,value in sources.items())
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(selected=selected,metrics={n:m['summary'] for n,m in models.items()},
        acceptance=acceptance,elapsed_seconds=report['elapsed_seconds'])),flush=True)


if __name__=='__main__':main()
