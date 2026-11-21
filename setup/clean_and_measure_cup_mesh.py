#!/usr/bin/env python3
"""Bounded mesh cleanup and dimensional screening; no scale fitting or GT claim."""
import argparse, copy, hashlib, json, time
from pathlib import Path
import numpy as np
import open3d as o3d
from scipy.optimize import least_squares
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def topology(mesh):
    faces=np.asarray(mesh.triangles)
    edges=np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
    edges,counts=np.unique(edges,axis=0,return_counts=True)
    ids,sizes,areas=mesh.cluster_connected_triangles()
    return dict(vertices=len(mesh.vertices),faces=len(faces),components=len(sizes),
                component_faces=[int(x) for x in sizes],boundary_edges=int((counts==1).sum()),
                nonmanifold_edges=int((counts>2).sum())),np.unique(edges[counts==1])

def profile(mesh):
    """RANSAC circle fits on nine fixed Z sections, with angular coverage checks."""
    v=np.asarray(mesh.vertices);f=np.asarray(mesh.triangles);tri=v[f]
    rng=np.random.default_rng(20261104);rows=[]
    for h in range(10,91,10):
        z=(h+.137)/1000
        parts=[]
        for a,b in [(0,1),(1,2),(2,0)]:
            A=tri[:,a];B=tri[:,b];valid=(A[:,2]-z)*(B[:,2]-z)<0
            s=(z-A[valid,2])/(B[valid,2]-A[valid,2])
            parts.append(A[valid,:2]+s[:,None]*(B[valid,:2]-A[valid,:2]))
        pts=np.unique(np.round(np.concatenate(parts),8),axis=0)
        if len(pts)<30:continue
        best=None;score=-1
        for _ in range(500):
            a,b,c=pts[rng.choice(len(pts),3,replace=False)]
            M=2*np.stack([b-a,c-a])
            if abs(np.linalg.det(M))<1e-8:continue
            center=np.linalg.solve(M,np.array([b@b-a@a,c@c-a@a]))
            r=np.linalg.norm(a-center)
            if not(.02<r<.055) or np.linalg.norm(center)>.012:continue
            mask=np.abs(np.linalg.norm(pts-center,axis=1)-r)<.0015
            if mask.sum()>score:best=(center,r,mask);score=mask.sum()
        if best is None:continue
        center,r,mask=best
        for _ in range(3):
            fit=least_squares(lambda x: np.linalg.norm(pts[mask]-x[:2],axis=1)-x[2],
                              np.r_[center,r],loss='soft_l1',f_scale=.001)
            center=fit.x[:2];r=fit.x[2]
            mask=np.abs(np.linalg.norm(pts-center,axis=1)-r)<.0015
        angles=np.arctan2(*(pts[mask]-center)[:,[1,0]].T)
        coverage=len(np.unique(np.floor((angles+np.pi)/(2*np.pi)*24).astype(int)))
        rows.append(dict(z_mm=z*1000,diameter_mm=float(2*r*1000),center_xy_mm=(center*1000).tolist(),
                         section_points=len(pts),inliers=int(mask.sum()),angular_bins_of_24=coverage,
                         radial_residual_median_mm=float(np.median(np.abs(np.linalg.norm(pts[mask]-center,axis=1)-r))*1000)))
    return rows

def distance_summary(points,target):
    scene=o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(target))
    ds=scene.compute_distance(o3d.core.Tensor(np.asarray(points,dtype=np.float32))).numpy()*1000
    return dict(samples=len(ds),mean_mm=float(ds.mean()),median_mm=float(np.median(ds)),
                rms_mm=float(np.sqrt(np.mean(ds**2))),p95_mm=float(np.percentile(ds,95)),max_sampled_mm=float(ds.max()))

def write_mesh(mesh, folder, stem):
    o3d.io.write_triangle_mesh(str(folder/(stem+'.ply')),mesh,write_ascii=False)
    v=np.asarray(mesh.vertices);f=np.asarray(mesh.triangles);c=np.asarray(mesh.vertex_colors)
    with (folder/(stem+'.obj')).open('x') as out:
        out.write('# meters; independent bounded cleanup candidate; not CAD ground truth\n')
        for i,p in enumerate(v):
            values=np.r_[p,c[i]] if len(c)==len(v) else p
            out.write('v '+' '.join('%.12g'%x for x in values)+'\n')
        for face in f:out.write('f '+' '.join(str(int(x)+1) for x in face)+'\n')

def preview(meshes, labels, path):
    points=np.concatenate([np.asarray(m.vertices)*1000 for m in meshes])
    center=(points.min(axis=0)+points.max(axis=0))/2
    half=np.ptp(points,axis=0).max()*.54
    fig=plt.figure(figsize=(15,12))
    light=np.array([-.4,-.6,1.]);light/=np.linalg.norm(light)
    for row,(mesh,label) in enumerate(zip(meshes,labels)):
        mesh.compute_triangle_normals()
        v=np.asarray(mesh.vertices)*1000;f=np.asarray(mesh.triangles)
        shade=.25+.7*np.abs(np.asarray(mesh.triangle_normals)@light)
        color=np.clip(shade[:,None]*np.array([.7,.79,.85]),0,1)
        for col,azim in enumerate([-130,-30,70]):
            ax=fig.add_subplot(len(meshes),3,row*3+col+1,projection='3d')
            ax.add_collection3d(Poly3DCollection(v[f],facecolors=color,edgecolors='none',linewidths=0))
            for fn,k in [(ax.set_xlim,0),(ax.set_ylim,1),(ax.set_zlim,2)]:fn(center[k]-half,center[k]+half)
            ax.set_box_aspect([1,1,1]);ax.set_proj_type('ortho');ax.view_init(elev=22,azim=azim)
            ax.set_axis_off();ax.set_title(label+' | '+str(azim)+' deg',fontsize=11)
    fig.suptitle('Cup cleanup comparison | matched scale / cameras / shading',fontsize=15)
    fig.text(.5,.02,'Top: original | middle: prior point-filtered TSDF | bottom: bounded Taubin, pinned boundaries | no scale correction',ha='center',fontsize=10)
    fig.subplots_adjust(left=0,right=1,bottom=.06,top=.94,wspace=0,hspace=.02)
    fig.savefig(path,dpi=130);plt.close(fig)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--denoised',type=Path,required=True)
    p.add_argument('--measurements',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    sources={str(x):sha(x) for x in [a.original,a.denoised,a.measurements]}
    original=o3d.io.read_triangle_mesh(str(a.original))
    base=o3d.io.read_triangle_mesh(str(a.denoised))
    assert len(base.vertices)>10000 and len(base.triangles)>20000
    before,boundary=topology(base)
    smooth=base.filter_smooth_taubin(number_of_iterations=3,lambda_filter=.5,mu=-.53,
                                   filter_scope=o3d.geometry.FilterScope.Vertex)
    v0=np.asarray(base.vertices).copy();v1=np.asarray(smooth.vertices).copy()
    delta=v1-v0;length=np.linalg.norm(delta,axis=1)
    delta*=np.minimum(1,.0005/np.maximum(length,1e-20))[:,None]
    delta[boundary]=0
    smooth.vertices=o3d.utility.Vector3dVector(v0+delta)
    smooth.vertex_colors=copy.deepcopy(base.vertex_colors)
    smooth.compute_vertex_normals()
    after,_=topology(smooth)
    movement=np.linalg.norm(delta,axis=1)*1000
    assert movement.max()<=.5000001 and np.allclose(np.asarray(smooth.vertices)[boundary],v0[boundary])
    assert after['faces']==before['faces'] and after['boundary_edges']==before['boundary_edges']
    assert np.array_equal(np.asarray(smooth.triangles),np.asarray(base.triangles))
    assert np.isfinite(np.asarray(smooth.vertices)).all()
    write_mesh(smooth,a.output,'cup_light_clean')
    manual=json.loads(a.measurements.read_text())
    mesh_info={}
    for name,m in [('original',original),('prior_denoised_tsdf',base),('light_clean',smooth)]:
        verts=np.asarray(m.vertices)
        info,_=topology(m);info['aabb_xyz_mm']=(np.ptp(verts,axis=0)*1000).tolist()
        comparisons=[]
        for label,k,index in [('height','height_mm',2),('body_outer_diameter','body_outer_diameter_mm',1),
                              ('overall_width_including_handle','overall_width_including_handle_mm',0)]:
            span=info['aabb_xyz_mm'][index];truth=float(manual[k])
            comparisons.append(dict(dimension=label,manual_approximate_mm=truth,aabb_span_mm=span,
                                    signed_difference_mm=span-truth,absolute_difference_mm=abs(span-truth),
                                    relative_absolute_percent=abs(span-truth)/truth*100))
        info['approximate_envelope_comparisons']=comparisons
        info['body_cross_sections']=profile(m)
        valid=[q for q in info['body_cross_sections'] if q['angular_bins_of_24']>=18]
        info['largest_fitted_section_diameter_mm']=max(q['diameter_mm'] for q in valid) if valid else None
        if valid:info['section_diameter_difference_from_manual_mm']=info['largest_fitted_section_diameter_mm']-manual['body_outer_diameter_mm']
        mesh_info[name]=info
    o3d.utility.random.seed(20261104)
    original_points=np.asarray(original.sample_points_uniformly(number_of_points=50000).points)
    clean_points=np.asarray(smooth.sample_points_uniformly(number_of_points=50000).points)
    change={'original_to_clean':distance_summary(original_points,smooth),
            'clean_to_original':distance_summary(clean_points,original)}
    preview([original,base,smooth],['Original TSDF','Prior point-filtered TSDF','Light mesh cleanup'],a.output/'comparison.png')
    report=dict(status='complete_derived_mesh_and_dimension_screen',source_files_sha256=sources,
                settings=dict(taubin_iterations=3,lambda_filter=.5,mu=-.53,pinned_boundary_vertices=len(boundary),
                              max_vertex_displacement_mm=.5,scale_changed=False,hole_filling=False),
                displacement_relative_to_prior_denoised_tsdf_mm=dict(median=float(np.median(movement)),
                 p95=float(np.percentile(movement,95)),max=float(movement.max()),moved_vertices=int((movement>1e-6).sum())),
                mesh_measurements=mesh_info,sampled_surface_change_not_ground_truth=change,
                manual_measurements=manual,mesh_precision_gt_available=False,original_inputs_unchanged=all(sha(Path(q))==v for q,v in sources.items()),
                limitations=['AABB spans are coarse dimensional screens, not calibrated semantic dimensions.',
                 'Body circle sections exclude most handle points but use the inherited estimated Z axis; manual measurement height is unspecified.',
                 'Manual dimensions are approximate; no uncertainty or independent reference surface is supplied.',
                 'Surface changes measure processing magnitude and do not prove accuracy improvement.',
                 'Prior denoised TSDF is reused, not rerun in this task. Original raw RGB-D and ICP poses are retained.'],
                elapsed_seconds=time.monotonic()-started)
    assert report['original_inputs_unchanged']
    artifacts=[]
    for file in a.output.iterdir():
        if file.is_file():artifacts.append(dict(name=file.name,bytes=file.stat().st_size,sha256=sha(file)))
    report['artifacts']=artifacts
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
