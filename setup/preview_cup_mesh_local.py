#!/usr/bin/env python3
"""Read an OBJ and render CPU-only multi-angle previews without trimesh."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
from PIL import Image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index(value, count):
    number = int(value)
    result = number - 1 if number > 0 else count + number
    if number == 0 or not 0 <= result < count:
        raise ValueError("OBJ index outside defined vertices/UVs")
    return result


def parse_obj(path):
    vertices, uv, faces, face_uv, materials = [], [], [], [], []
    for raw in path.read_text(encoding="utf-8").splitlines():
        tokens = raw.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        if tokens[0] == "v":
            vertices.append([float(x) for x in tokens[1:4]])
        elif tokens[0] == "vt":
            uv.append([float(x) for x in tokens[1:3]])
        elif tokens[0] == "mtllib":
            materials.extend(tokens[1:])
        elif tokens[0] == "f":
            corners, tex = [], []
            for token in tokens[1:]:
                pieces = token.split("/")
                corners.append(index(pieces[0], len(vertices)))
                tex.append(index(pieces[1], len(uv)) if len(pieces) > 1 and pieces[1] else -1)
            if len(corners) < 3:
                raise ValueError("OBJ face has fewer than three vertices")
            for j in range(1, len(corners) - 1):
                faces.append([corners[0], corners[j], corners[j + 1]])
                face_uv.append([tex[0], tex[j], tex[j + 1]])
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    uv = np.asarray(uv, dtype=np.float64)
    face_uv = np.asarray(face_uv, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(faces):
        raise ValueError("OBJ lacks nonempty 3D vertices or faces")
    if not np.all(np.isfinite(vertices)) or (uv.size and not np.all(np.isfinite(uv))):
        raise ValueError("OBJ vertices/UVs contain nonfinite values")
    return vertices, faces, uv, face_uv, materials


def local_material(path, name):
    candidate = (path.parent / name).resolve()
    candidate.relative_to(path.parent.resolve())
    if not candidate.is_file():
        raise ValueError("Missing local material: " + name)
    return candidate


def parse_vertex_rgb(path, vertex_count):
    """Read the common OBJ v x y z r g b extension without inventing colors."""
    colors = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and fields[0] == "v":
            if len(fields) != 7:
                return None
            colors.append([float(value) for value in fields[4:7]])
    colors = np.asarray(colors, dtype=np.float64)
    if colors.shape != (vertex_count, 3):
        return None
    if not np.all(np.isfinite(colors)) or np.any(colors < 0) or np.any(colors > 1):
        raise ValueError("OBJ vertex RGB must be finite and in [0, 1]")
    return colors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    mesh = args.mesh.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Preserve prior previews; use a new output directory")
    output.mkdir(parents=True)
    vertices, faces, uv, face_uv, material_names = parse_obj(mesh)
    triangles = vertices[faces]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    nondegenerate = area > 1e-14
    triangles = triangles[nondegenerate]
    selected_face_uv = face_uv[nondegenerate]
    colors = np.tile([0.08, 0.66, 0.70], (len(triangles), 1))
    vertex_rgb = parse_vertex_rgb(mesh, len(vertices))
    appearance_source = "uniform fallback; no stored appearance found"
    if vertex_rgb is not None:
        colors = vertex_rgb[faces[nondegenerate]].mean(axis=1)
        appearance_source = "OBJ vertex RGB averaged per triangle"
    provenance = [{"path": str(mesh), "sha256": sha(mesh)}]
    texture_path = None
    for name in material_names:
        material = local_material(mesh, name)
        provenance.append({"path": str(material), "sha256": sha(material)})
        for line in material.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if fields and fields[0] == "map_Kd":
                texture_path = local_material(mesh, " ".join(fields[1:]))
                break
        if texture_path:
            break
    if texture_path is not None and uv.size:
        texture = np.asarray(Image.open(texture_path).convert("RGB")) / 255.0
        valid_uv = np.all(selected_face_uv >= 0, axis=1)
        centroids = uv[selected_face_uv[valid_uv]].mean(axis=1)
        x = np.clip(np.rint(centroids[:, 0] * (texture.shape[1] - 1)), 0, texture.shape[1] - 1).astype(int)
        y = np.clip(np.rint((1 - centroids[:, 1]) * (texture.shape[0] - 1)), 0, texture.shape[0] - 1).astype(int)
        colors[valid_uv] = texture[y, x]
        if np.any(valid_uv):
            appearance_source = "UV texture sampled at triangle centroid"
        provenance.append({"path": str(texture_path), "sha256": sha(texture_path)})
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    extent, center = hi - lo, (hi + lo) / 2
    half_span = max(float(extent.max()) * 0.58, 1e-6)
    limits = [(float(value - half_span), float(value + half_span)) for value in center]
    views = [(20, angle) for angle in range(0, 360, 60)] + [(85, 0), (-70, 0)]

    def draw(ax, elevation, azimuth, textured):
        if textured:
            face_colors = colors
        else:
            normal = cross[nondegenerate] / np.maximum(np.linalg.norm(cross[nondegenerate], axis=1)[:, None], 1e-20)
            light = np.asarray([0.3, -0.4, 0.86]); light /= np.linalg.norm(light)
            brightness = 0.55 + 0.40 * np.abs(normal @ light)
            face_colors = np.asarray([0.13, 0.62, 0.68])[None, :] * brightness[:, None]
        collection = Poly3DCollection(triangles, facecolors=face_colors, edgecolors="none", linewidths=0)
        ax.add_collection3d(collection)
        ax.set_xlim(*limits[0]); ax.set_ylim(*limits[1]); ax.set_zlim(*limits[2])
        ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=elevation, azim=azimuth)
        ax.set_xlabel("X (model m)", fontsize=7); ax.set_ylabel("Y (model m)", fontsize=7); ax.set_zlabel("Z (model m)", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.set_title("elev %d / azim %d" % (elevation, azimuth), fontsize=10)

    outputs = []
    for textured, filename in ((True, "color_views_8.png"), (False, "geometry_views_8.png")):
        figure = plt.figure(figsize=(18, 9))
        for i, (elevation, azimuth) in enumerate(views, 1):
            draw(figure.add_subplot(2, 4, i, projection="3d"), elevation, azimuth, textured)
        display = appearance_source if textured else "uniform normal shading for shape inspection"
        figure.suptitle("Reconstructed cup: " + display + "; shared metric axis span\nAppearance/geometry preview only; no ground-truth or dimensional-accuracy claim", fontsize=13)
        figure.tight_layout(rect=[0, 0, 1, 0.93])
        destination = output / filename
        figure.savefig(destination, dpi=130)
        plt.close(figure)
        outputs.append({"path": str(destination), "sha256": sha(destination)})
        if textured:
            # Retain the historical output name; the report identifies vertex RGB vs UV.
            alias = output / "textured_views_8.png"
            alias.write_bytes(destination.read_bytes())
            outputs.append({"path": str(alias), "sha256": sha(alias), "alias_of": filename})
    report = {"schema_version": 2, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "passed": True, "mesh_source": str(mesh), "source_files": provenance,
              "method": "OBJ fan triangulation; Matplotlib CPU 3D at 8 angles; vertex RGB averaged per face or UV texture centroid when present",
              "appearance_source": appearance_source, "obj_vertex_rgb_present": vertex_rgb is not None,
              "uv_texture_present": texture_path is not None and bool(uv.size),
              "unique_vertex_rgb": int(len(np.unique(vertex_rgb, axis=0))) if vertex_rgb is not None else None,
              "vertices": len(vertices), "triangulated_faces": len(faces),
              "finite_vertices": True, "finite_uvs": True,
              "degenerate_faces_skipped_for_preview": int(np.count_nonzero(~nondegenerate)),
              "nondegenerate_faces_rendered": len(triangles),
              "bounding_box_min_xyz": lo.tolist(), "bounding_box_max_xyz": hi.tolist(),
              "extents_xyz": extent.tolist(), "equal_axis_limits_xyz": limits,
              "axis_span": half_span * 2, "coordinate_unit_label": "model meters inherited from RGB-D reconstruction, physical accuracy not verified",
              "view_elevation_azimuth_degrees": views, "outputs": outputs,
              "mesh_unchanged": sha(mesh) == provenance[0]["sha256"],
              "gpu_used": False, "ssh_or_camera_access": False, "is_ground_truth": False,
              "manual_visual_review_completed": False,
              "limitations": ["CPU preview is not photorealistic; one color per face", "Vertex RGB is not a high-resolution UV texture atlas", "Metric mesh extents do not certify actual cup dimensions", "Recovered model axes may not match physical upright axes", "No pose or reconstruction accuracy evaluation is provided"]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "vertices": len(vertices), "triangles": len(faces),
                      "extents_xyz": extent.tolist(), "output": str(output)}), flush=True)


if __name__ == "__main__":
    main()
