#!/usr/bin/env python3
"""CPU OBJ triangle rasterizer using NumPy and Pillow, no Matplotlib/trimesh."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def obj_index(value, count):
    value = int(value)
    result = value - 1 if value > 0 else count + value
    if value == 0 or not 0 <= result < count:
        raise ValueError("OBJ index outside defined data")
    return result


def read_obj(path):
    vertices, uv, faces, face_uv, materials = [], [], [], [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "v":
            vertices.append([float(v) for v in fields[1:4]])
        elif fields[0] == "vt":
            uv.append([float(v) for v in fields[1:3]])
        elif fields[0] == "mtllib":
            materials.extend(fields[1:])
        elif fields[0] == "f":
            vi, ti = [], []
            for corner in fields[1:]:
                parts = corner.split("/")
                vi.append(obj_index(parts[0], len(vertices)))
                ti.append(obj_index(parts[1], len(uv)) if len(parts) > 1 and parts[1] else -1)
            if len(vi) < 3:
                raise ValueError("Face requires at least three vertices")
            for j in range(1, len(vi) - 1):
                faces.append([vi[0], vi[j], vi[j + 1]])
                face_uv.append([ti[0], ti[j], ti[j + 1]])
    v, f, t, ft = (np.asarray(vertices, np.float64), np.asarray(faces, np.int64),
                    np.asarray(uv, np.float64), np.asarray(face_uv, np.int64))
    if v.ndim != 2 or v.shape[1] != 3 or not len(f) or not np.all(np.isfinite(v)):
        raise ValueError("Mesh requires nonempty finite 3D vertices and triangle faces")
    if t.size and not np.all(np.isfinite(t)):
        raise ValueError("Mesh has nonfinite UVs")
    return v, f, t, ft, materials


def material_path(mesh, name):
    path = (mesh.parent / name).resolve()
    path.relative_to(mesh.parent.resolve())
    if not path.is_file():
        raise ValueError("Local material is missing")
    return path


def camera_basis(elev, azim):
    elevation, azimuth = np.deg2rad([elev, azim])
    direction = np.asarray([np.cos(elevation)*np.cos(azimuth),
                            np.cos(elevation)*np.sin(azimuth), np.sin(elevation)])
    right = np.asarray([-np.sin(azimuth), np.cos(azimuth), 0.0])
    up = np.cross(direction, right)
    return right, up, direction


def render(vertices, faces, colors, center, span, elev, azim, shading=True, size=540):
    right, up, camera = camera_basis(elev, azim)
    local = vertices - center
    projected = np.column_stack((local @ right, local @ up, local @ camera))
    projected[:, 0] = (projected[:, 0] / span + 0.5) * (size - 1)
    projected[:, 1] = (0.5 - projected[:, 1] / span) * (size - 1)
    raster = np.full((size,size,3),245,np.uint8)
    zbuffer = np.full((size,size),-np.inf,np.float64)
    for j, face in enumerate(faces):
        triangle = projected[face]
        xmin, xmax = max(0,int(np.floor(triangle[:,0].min()))), min(size-1,int(np.ceil(triangle[:,0].max())))
        ymin, ymax = max(0,int(np.floor(triangle[:,1].min()))), min(size-1,int(np.ceil(triangle[:,1].max())))
        if xmin>xmax or ymin>ymax:
            continue
        x0,y0,z0 = triangle[0]; x1,y1,z1=triangle[1]; x2,y2,z2=triangle[2]
        denominator = (y1-y2)*(x0-x2)+(x2-x1)*(y0-y2)
        if abs(denominator)<1e-10:
            continue
        yy,xx=np.mgrid[ymin:ymax+1,xmin:xmax+1]
        xx=xx+0.5; yy=yy+0.5
        a=((y1-y2)*(xx-x2)+(x2-x1)*(yy-y2))/denominator
        b=((y2-y0)*(xx-x2)+(x0-x2)*(yy-y2))/denominator
        c=1-a-b
        depth=a*z0+b*z1+c*z2
        current=zbuffer[ymin:ymax+1,xmin:xmax+1]
        inside=(a>=-1e-7)&(b>=-1e-7)&(c>=-1e-7)&(depth>current)
        if np.any(inside):
            current[inside]=depth[inside]
            color=colors[j]
            if shading:
                world=vertices[face]
                normal=np.cross(world[1]-world[0],world[2]-world[0]); length=np.linalg.norm(normal)
                brightness=0.55+0.45*abs(float(normal@camera))/max(length,1e-20)
                color=color*brightness
            raster[ymin:ymax+1,xmin:xmax+1][inside]=np.clip(color*255,0,255).astype(np.uint8)
    image=Image.fromarray(raster)
    draw=ImageDraw.Draw(image)
    draw.text((9,9),"elev %d / azim %d, orthographic" % (elev,azim),fill=(0,0,0))
    draw.text((9,24),"shared span %.4f model m" % span,fill=(0,0,0))
    bar=int(0.05/span*(size-1));draw.line((20,size-25,20+bar,size-25),fill=(0,0,0),width=3)
    draw.text((20,size-44),"0.050 model m (not measured)",fill=(0,0,0))
    ox,oy=size-67,size-67
    for direction,label,color in zip(np.eye(3),"XYZ",[(210,25,25),(20,150,20),(30,60,210)]):
        dx,dy=float(direction@right)*38,-float(direction@up)*38
        draw.line((ox,oy,ox+dx,oy+dy),fill=color,width=2);draw.text((ox+dx,oy+dy),label,fill=color)
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args();mesh=args.mesh.resolve();output=args.output.resolve()
    if output.exists():raise FileExistsError("Preserve prior preview; choose a new output directory")
    output.mkdir(parents=True)
    v,f,uv,ft,materials=read_obj(mesh)
    triangles=v[f];areas=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)/2
    good=areas>1e-14;degenerate=int(np.count_nonzero(~good));f=f[good];ft=ft[good]
    colors=np.tile([0.05,0.62,0.64],(len(f),1));sources=[{"path":str(mesh),"sha256":sha(mesh)}]
    texture=None
    for name in materials:
        m=material_path(mesh,name);sources.append({"path":str(m),"sha256":sha(m)})
        for line in m.read_text(encoding="utf-8").splitlines():
            fields=line.split()
            if fields and fields[0]=="map_Kd":
                texture=material_path(mesh," ".join(fields[1:]));break
        if texture:break
    if texture is not None and uv.size:
        pixels=np.asarray(Image.open(texture).convert("RGB"))/255.0
        good_uv=np.all(ft>=0,axis=1);means=uv[ft[good_uv]].mean(axis=1)
        xs=np.clip(np.rint(means[:,0]*(pixels.shape[1]-1)),0,pixels.shape[1]-1).astype(int)
        ys=np.clip(np.rint((1-means[:,1])*(pixels.shape[0]-1)),0,pixels.shape[0]-1).astype(int)
        colors[good_uv]=pixels[ys,xs];sources.append({"path":str(texture),"sha256":sha(texture)})
    lo,hi=v.min(axis=0),v.max(axis=0);center=(hi+lo)/2;extents=hi-lo
    span=max(float(np.linalg.norm(extents))*1.08,1e-6)
    views=[(20,angle) for angle in range(0,360,60)]+[(85,0),(-70,0)]
    outputs=[]
    for mode in ("textured","geometry"):
        panels=[];facecolors=colors if mode=="textured" else np.tile([0.18,0.58,0.65],(len(f),1))
        for elevation,azimuth in views:
            view=render(v,f,facecolors,center,span,elevation,azimuth)
            path=output/('%s_elev%d_azim%d.png' % (mode,elevation,azimuth));view.save(path)
            outputs.append({"path":str(path),"sha256":sha(path)})
            panels.append(view)
            print(json.dumps({"stage":"rendered","mode":mode,"elevation":elevation,"azimuth":azimuth}),flush=True)
        montage=Image.new("RGB",(540*4,540*2+42),(255,255,255))
        for i,panel in enumerate(panels):montage.paste(panel,((i%4)*540,(i//4)*540+42))
        ImageDraw.Draw(montage).text((12,12),"Reconstructed cup %s: 8 CPU views, one shared scale; visual geometry QA only, no GT or physical-size accuracy" % mode,fill=(0,0,0))
        path=output/(mode+"_views_8.png");montage.save(path);outputs.append({"path":str(path),"sha256":sha(path)})
    report={"schema_version":1,"passed":True,"created_at_utc":datetime.now(timezone.utc).isoformat(),"source_files":sources,"method":"OBJ fan triangulation, NumPy CPU orthographic triangle z-buffer; triangle-centroid texture and normal lighting; no trimesh or Matplotlib","vertices":len(v),"triangulated_faces_total":len(good),"nondegenerate_faces_rendered":len(f),"degenerate_faces_skipped":degenerate,"all_vertices_finite":True,"bounding_box_min_xyz":lo.tolist(),"bounding_box_max_xyz":hi.tolist(),"extents_xyz":extents.tolist(),"orthographic_span_shared_all_views":span,"world_axis_bounds_xyz":[[float(a),float(b)] for a,b in zip(lo,hi)],"axis_unit":"reconstruction model meters inherited from RGB-D; physical accuracy unverified","views_elevation_azimuth_degrees":views,"outputs":outputs,"gpu_used":False,"ssh_or_camera_access":False,"source_mesh_unchanged":sha(mesh)==sources[0]['sha256'],"is_ground_truth":False,"manual_visual_review_completed":False,"limitations":["Eight preview viewpoints do not certify topology or dimensional accuracy","Texture sampled once per triangle, approximate","No cup physical measurements or GT pose labels","Source model axes are recovered coordinates and may differ from physical upright axes"]}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'output':str(output),'vertices':len(v),'triangles':len(good),'extents_xyz':extents.tolist()}),flush=True)


if __name__=='__main__':main()
