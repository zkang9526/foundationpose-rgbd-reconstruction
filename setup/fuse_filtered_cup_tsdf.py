#!/usr/bin/env python3
"""Reassociate filtered voxel representatives to measured rays, then compare two RGB-D TSDFs."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree
from cup_reconstruction_depth import selected_depth_mask

DTYPE = [('x','<f4'),('y','<f4'),('z','<f4'),('rgb','<u4')]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def xyz(data):
    return np.column_stack([data[k] for k in ('x','y','z')]).astype(float)


def export_mesh(mesh, out, key, label, smooth_normals=False):
    """Export geometry with optional vertex normals for smooth viewer lighting."""
    if not len(mesh.triangles):
        raise ValueError('Empty TSDF mesh')
    o3d.io.write_triangle_mesh(str(out/(key+'_raw.ply')),mesh)
    labels, counts, _ = mesh.cluster_connected_triangles()
    labels, counts = np.asarray(labels), np.asarray(counts)
    remove = counts[labels] < max(30, int(counts.max())*.003)
    clean = copy.deepcopy(mesh)
    clean.remove_triangles_by_mask(remove)
    clean.remove_unreferenced_vertices()
    clean.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(out/(key+'.ply')), clean)
    v, f, color = np.asarray(clean.vertices), np.asarray(clean.triangles), np.asarray(clean.vertex_colors)
    with (out/(key+'.obj')).open('x') as stream:
        stream.write('# meters; TSDF candidate with estimated poses; not GT\n')
        for pos, rgb in zip(v, color):
            stream.write('v '+' '.join('%.9g'%x for x in np.r_[pos,rgb])+'\n')
        for face in f:
            stream.write('f %d %d %d\n'%tuple(face+1))
    if smooth_normals:
        normals = np.asarray(clean.vertex_normals)[f.reshape(-1)]
    else:
        normals = np.repeat(np.asarray(clean.triangle_normals), 3, axis=0)
    triangles = v[f.reshape(-1)]
    rgb = np.rint(np.clip(color[f.reshape(-1)],0,1)*255).astype(np.uint32)
    packed = np.empty(len(triangles),dtype=DTYPE+[('nx','<f4'),('ny','<f4'),('nz','<f4')])
    for j, field in enumerate(('x','y','z')):
        packed[field]=triangles[:,j]
    packed['rgb']=(rgb[:,0]<<16)|(rgb[:,1]<<8)|rgb[:,2]
    for j, field in enumerate(('nx','ny','nz')):
        packed[field]=normals[:,j]
    raw=packed.tobytes()
    (out/(key+'.bin')).write_bytes(raw)
    edges=np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]])
    _, edge_counts=np.unique(np.sort(edges,axis=1),axis=0,return_counts=True)
    return dict(kind='mesh',stride=28,points=len(packed),triangles=len(f),vertices=len(v),
                label=label,sha256=hashlib.sha256(raw).hexdigest(),
                raw_triangles=len(mesh.triangles),removed_fragment_triangles=int(remove.sum()),
                boundary_edges=int((edge_counts==1).sum()),nonmanifold_edges=int((edge_counts>2).sum()),
                bounds_m=[v.min(axis=0).tolist(),v.max(axis=0).tolist()],
                extents_mm=(np.ptp(v,axis=0)*1000).tolist(), obj_sha256=sha(out/(key+'.obj')))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('clouds','filtered','scene','masks','result','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    cm=json.loads((a.clouds/'manifest.json').read_text())
    fm=json.loads((a.filtered/'manifest.json').read_text())
    report=json.loads((a.result/'report.json').read_text())
    raw=np.fromfile(a.clouds/'after_rgb.bin',dtype=DTYPE)
    raw_sha=sha(a.clouds/'after_rgb.bin')
    if raw_sha!=cm['artifacts']['after_rgb']['sha256'] or raw_sha!=fm['source_after_rgb_sha256']:
        raise ValueError('Original point cloud differs')
    for key in ('denoised_rgb','filtered_rgb'):
        if sha(a.filtered/(key+'.bin'))!=fm['artifacts'][key]['sha256']:
            raise ValueError('Filtered cloud differs')
    original=xyz(raw)
    denoised=xyz(np.fromfile(a.filtered/'denoised_rgb.bin',dtype=DTYPE))
    smoothed=xyz(np.fromfile(a.filtered/'filtered_rgb.bin',dtype=DTYPE))
    cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(original))
    voxel=np.asarray(cloud.voxel_down_sample(.001).points)
    distance,index=cKDTree(voxel).query(denoised,k=1)
    if distance.max()>1e-6 or len(np.unique(index))!=len(index):
        raise ValueError('Cannot recover filtered voxel membership')
    origin=original.min(axis=0)-.0005
    voxel_keys=np.floor((voxel-origin)/.001).astype(np.int64)
    lookup={tuple(voxel_keys[i]):j for j,i in enumerate(index)}
    keys,inverse=np.unique(np.floor((original-origin)/.001).astype(np.int64),axis=0,return_inverse=True)
    membership=np.array([lookup.get(tuple(k),-1) for k in keys],dtype=np.int64)[inverse]
    if (membership>=0).sum()==0:
        raise ValueError('No retained measured rays')
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'derived_depth').mkdir()
    K=np.loadtxt(a.scene/'K.txt')
    intrinsic=o3d.camera.PinholeCameraIntrinsic(640,480,K[0,0],K[1,1],K[0,2],K[1,2])
    volumes=[o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=.0015,sdf_trunc=.0075,
             color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8) for _ in range(2)]
    rows=[]
    cursor=0
    for row, saved in zip(report['frames'],cm['frames']):
        name=row['frame']
        paths=[a.scene/'rgb'/name,a.scene/'depth'/name,a.masks/'masks'/name]
        expected=[row[k] for k in ('raw_rgb_sha256','raw_depth_sha256','mask_sha256')]
        if [sha(x) for x in paths]!=expected:
            raise ValueError('Frame source hash differs: '+name)
        rgb=cv2.cvtColor(cv2.imread(str(paths[0])),cv2.COLOR_BGR2RGB)
        depth=cv2.imread(str(paths[1]),-1)
        valid=selected_depth_mask(depth,cv2.imread(str(paths[2]),0)>0,report,row)
        yy,xx=np.nonzero(valid)
        count=int(valid.sum())
        if count!=saved['points'] or name!=saved['frame']:
            raise ValueError('Frame point order differs')
        T_path=a.result/'estimated_camera_to_model'/(Path(name).stem+'.txt')
        if sha(T_path)!=saved['pose_sha256']:
            raise ValueError('Saved pose differs')
        T=np.loadtxt(T_path)
        z=depth[valid].astype(float)/1000.
        camera=np.column_stack(((xx-K[0,2])*z/K[0,0],(yy-K[1,2])*z/K[1,1],z))
        world=camera@T[:3,:3].T+T[:3,3]
        if np.max(np.abs(world-original[cursor:cursor+count]))>1e-6:
            raise ValueError('Original point provenance/order check failed')
        ids=membership[cursor:cursor+count]
        retained=ids>=0
        adjustment=np.zeros(count)
        adjustment[retained]=np.einsum('ij,j->i',smoothed[ids[retained]]-world[retained],T[:3,2])
        adjustment=np.clip(adjustment,-.0015,.0015)
        derived=np.zeros(depth.shape,dtype=np.float32)
        derived[yy[retained],xx[retained]]=(z[retained]+adjustment[retained]).astype(np.float32)
        np.save(a.output/'derived_depth'/(Path(name).stem+'.npy'),derived)
        original_depth=np.where(valid,depth,0).astype(np.uint16)
        for volume,image,scale in zip(volumes,(original_depth,derived),(1000.,1.)):
            rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(o3d.geometry.Image(rgb),o3d.geometry.Image(image),
                   depth_scale=scale,depth_trunc=.8,convert_rgb_to_intensity=False)
            volume.integrate(rgbd,intrinsic,np.linalg.inv(T))
        rows.append(dict(frame=name,original_rays=count,retained_rays=int(retained.sum()),
                         max_depth_update_mm=float(np.abs(adjustment[retained]).max()*1000),
                         source_sha256=expected,pose_sha256=saved['pose_sha256']))
        cursor+=count
    if cursor!=len(original):
        raise ValueError('Frame count does not consume original cloud')
    artifacts={}
    for volume,key,label in zip(volumes,('tsdf_original','tsdf_filtered'),('原始深度 → TSDF表面','滤波派生深度 → TSDF表面')):
        mesh=volume.extract_triangle_mesh()
        mesh.remove_degenerate_triangles()
        mesh.remove_duplicated_triangles()
        mesh.remove_unreferenced_vertices()
        artifacts[key]=export_mesh(mesh,a.output,key,label)
    result=dict(scope='Independent RGB-D TSDF comparison with fixed saved ICP poses; not a precision acceptance.',
                source_after_rgb_sha256=raw_sha,source_filtered_rgb_sha256=fm['artifacts']['filtered_rgb']['sha256'],
                method='Associate original measured points to retained 1mm voxel representatives. Keep original pixel rays and RGB; update depth toward smoothed representative camera Z, bounded 1.5mm. No new valid pixels. Then RGB-D TSDF.',
                caveat='Not literal integration of merged cloud. Ray-preserving derived depths approximate the 3D filter; frame correlations remain. Invalid depth and occluded surfaces are not filled.',
                tsdf_voxel_mm=1.5,tsdf_truncation_mm=7.5,original_modified=False,poses_modified=False,
                cleanup='Both meshes: remove components smaller than max(30 triangles, 0.3% largest component); no mesh smoothing or scale change.',
                frames=rows,artifacts=artifacts,geometry_accuracy_validated=False)
    (a.output/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='frames'}))


if __name__=='__main__':
    main()
