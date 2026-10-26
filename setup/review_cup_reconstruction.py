#!/usr/bin/env python3
"""CPU geometry/pose audit for a BundleSDF cup reconstruction.

Raw inputs and reconstruction files are read only. A successful numeric audit
does not certify correct tracking, physical dimensions or mesh quality. Mesh
projection uses only a separately documented matching pose coordinate frame.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def file_info(path, expected=None):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError("Input changed during hashing: {}".format(path))
    value = {"path": str(path), "bytes": after.st_size, "sha256": digest.hexdigest()}
    if expected is not None and value["sha256"] != expected:
        raise ValueError("Source hash mismatch: {}".format(path))
    return value


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: {}".format(path))
    return value


def write_report(report, path):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def rigid_pose(path, np):
    pose = np.loadtxt(str(path), dtype=np.float64)
    result = {"source": file_info(path), "shape": list(pose.shape),
              "finite": bool(np.isfinite(pose).all()), "pose_is_ground_truth": False}
    if pose.shape != (4, 4) or not result["finite"]:
        result["numerically_valid_rigid_pose"] = False
        return pose, result
    rotation = pose[:3, :3]
    with np.errstate(over="ignore", invalid="ignore"):
        determinant = float(np.linalg.det(rotation))
        orthogonality = float(np.linalg.norm(rotation.T @ rotation - np.eye(3)))
        row_error = float(np.linalg.norm(pose[3] - [0, 0, 0, 1]))
    numeric_finite = bool(np.isfinite([determinant, orthogonality, row_error]).all())
    result.update(rotation_determinant=determinant if np.isfinite(determinant) else None,
                  rotation_orthogonality_error=orthogonality if np.isfinite(orthogonality) else None,
                  homogeneous_row_error=row_error if np.isfinite(row_error) else None,
                  translation_m=pose[:3, 3].tolist(),
                  origin_camera_z_positive=bool(pose[2, 3] > 0),
                  numerically_valid_rigid_pose=bool(numeric_finite and abs(determinant - 1) < 1e-3
                                                   and orthogonality < 1e-3 and row_error < 1e-5))
    return pose, result


def mesh_components(vertices, faces, np):
    """Vertex-connected components, preserving texture-seam vertex identity."""
    parent = list(range(len(vertices)))
    rank = [0] * len(vertices)

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(first, second):
        first, second = find(first), find(second)
        if first == second:
            return
        if rank[first] < rank[second]:
            first, second = second, first
        parent[second] = first
        if rank[first] == rank[second]:
            rank[first] += 1

    for first, second, third in faces:
        union(int(first), int(second))
        union(int(first), int(third))
    roots = np.array([find(index) for index in range(len(vertices))], dtype=np.int64)
    face_roots = roots[faces[:, 0]]
    labels, face_counts = np.unique(face_roots, return_counts=True)
    result = []
    for root, face_count in zip(labels, face_counts):
        selected_faces = np.flatnonzero(face_roots == root)
        selected_vertices = np.unique(faces[selected_faces].ravel())
        subset = vertices[selected_vertices]
        bounds = np.stack([subset.min(axis=0), subset.max(axis=0)])
        result.append({"faces": int(face_count), "vertices": len(selected_vertices),
                       "bounds_m": bounds.tolist(), "extents_m": (bounds[1] - bounds[0]).tolist()})
    result.sort(key=lambda item: item["faces"], reverse=True)
    return result


def choose_mesh(reconstruction, explicit):
    if explicit is not None:
        candidates = [explicit]
    else:
        preferred = reconstruction / "final/textured_mesh.obj"
        candidates = [preferred] if preferred.is_file() else sorted(reconstruction.rglob("textured_mesh.obj"))
    if len(candidates) != 1:
        raise ValueError("Expected one final metric textured_mesh.obj; use --mesh to disambiguate")
    mesh = candidates[0].resolve(strict=True)
    if mesh.name != "textured_mesh.obj" or reconstruction not in mesh.parents:
        raise ValueError("Mesh must be textured_mesh.obj inside the reconstruction; normalized meshes are refused")
    return mesh


def audit_official_export_source(repo, report):
    """Read source as evidence; never import BundleSDF or initialize CUDA."""
    records = []
    statements = []
    for filename in ("bundlesdf.py", "nerf_runner.py", "Utils.py"):
        path = repo / filename
        if not path.is_file():
            continue
        records.append(file_info(path))
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "mesh_to_real_world" in line or "textured_mesh.obj" in line or "poses_after_nerf.txt" in line:
                statements.append({"file": filename, "line": index + 1,
                                   "source_context": "\n".join(lines[max(0, index - 4):index + 5])})
    report["official_export_source"] = {"files": records, "statements": statements,
                                        "source_imported": False, "source_is_executable_instruction": False}
    if not any("mesh_to_real_world" in item["source_context"] for item in statements):
        raise ValueError("Cannot establish metric mesh export from the local official source")
    if not any("textured_mesh.obj" in item["source_context"] for item in statements):
        raise ValueError("Cannot establish textured_mesh export from the local official source")


def sampled_edges(faces, np, maximum=8000):
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges.sort(axis=1)
    edges = np.unique(edges, axis=0)
    count = len(edges)
    if count > maximum:
        indices = np.linspace(0, count - 1, maximum).astype(np.int64)
        edges = edges[indices]
    return edges, count


def fit_static_view(vertices, horizontal, vertical, np, size=640):
    matrix = np.stack([horizontal, vertical], axis=1)
    projected = vertices @ matrix
    minimum, maximum = projected.min(axis=0), projected.max(axis=0)
    extents = maximum - minimum
    scale = (size - 100) / max(float(extents.max()), 1e-9)
    points = (projected - (minimum + maximum) / 2) * scale
    points[:, 0] += size / 2
    points[:, 1] = size / 2 - points[:, 1]
    return points, extents


def static_mesh_views(mesh, output, report, np, cv2):
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    edges, total_edges = sampled_edges(faces, np)
    views = [
        ("xy_front", [1, 0, 0], [0, 1, 0]),
        ("xz_front", [1, 0, 0], [0, 0, 1]),
        ("yz_side", [0, 1, 0], [0, 0, 1]),
        ("oblique_a", [1, -1, 0], [1, 1, 2]),
        ("oblique_b", [1, 1, 0], [-1, 1, 2]),
        ("oblique_bottom", [1, -1, 0], [-1, -1, 2]),
    ]
    report["static_mesh_views"] = []
    for name, horizontal, vertical in views:
        horizontal = np.asarray(horizontal, dtype=np.float64)
        vertical = np.asarray(vertical, dtype=np.float64)
        horizontal /= np.linalg.norm(horizontal)
        vertical -= horizontal * float(vertical @ horizontal)
        vertical /= np.linalg.norm(vertical)
        projected, projected_extents = fit_static_view(vertices, horizontal, vertical, np)
        points = np.rint(projected).astype(np.int32)
        canvas = np.full((640, 640, 3), 248, dtype=np.uint8)
        silhouette = np.zeros((640, 640), dtype=np.uint8)
        # Each triangle is painted separately so overlaps form a union rather
        # than fillPoly's even/odd polygon-hole behavior.
        for triangle in faces:
            cv2.fillConvexPoly(silhouette, points[triangle], 255)
        canvas[silhouette > 0] = [202, 228, 220]
        for first, second in edges:
            cv2.line(canvas, tuple(points[first]), tuple(points[second]), (95, 140, 100), 1, cv2.LINE_AA)
        contours = cv2.findContours(silhouette, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
        cv2.drawContours(canvas, contours, -1, (25, 70, 25), 2)
        cv2.putText(canvas, name + " | CPU geometry view", (16, 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (20, 20, 20), 1, cv2.LINE_AA)
        cv2.putText(canvas, "Auto-fit; reconstructed metric geometry, no physical measurement", (16, 620),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.37, (20, 20, 20), 1, cv2.LINE_AA)
        path = output / "mesh_views" / (name + ".png")
        if not cv2.imwrite(str(path), canvas):
            raise RuntimeError("Could not save CPU mesh view")
        report["static_mesh_views"].append({"name": name, "image": file_info(path),
                                            "projected_extents_m": projected_extents.tolist(),
                                            "display_edges": len(edges), "total_edges": total_edges,
                                            "all_faces_used_for_silhouette": True})
    tiles = [cv2.imread(item["image"]["path"]) for item in report["static_mesh_views"]]
    montage = np.concatenate([np.concatenate(tiles[:3], axis=1), np.concatenate(tiles[3:], axis=1)], axis=0)
    montage_path = output / "mesh_views_montage.png"
    cv2.imwrite(str(montage_path), montage)
    report["static_mesh_montage"] = file_info(montage_path)


def audit_pose_directory(directory, expected_ids, np):
    records = []
    poses = {}
    present = {path.stem: path for path in directory.glob("*.txt")} if directory.is_dir() else {}
    missing = sorted(set(expected_ids) - set(present))
    extra = sorted(set(present) - set(expected_ids))
    for identifier in expected_ids:
        record = {"id": identifier, "pose_is_ground_truth": False}
        if identifier not in present:
            record.update(status="missing", numerically_valid_rigid_pose=False)
        else:
            try:
                pose, inspection = rigid_pose(present[identifier], np)
                record.update(inspection, status="numeric_check_completed")
                if inspection["numerically_valid_rigid_pose"]:
                    poses[identifier] = pose
            except Exception as error:
                record.update(status="invalid", numerically_valid_rigid_pose=False,
                              error="{}: {}".format(type(error).__name__, error))
        records.append(record)
    return poses, {"directory": str(directory), "expected_frames": len(expected_ids),
                   "missing_frame_ids": missing, "extra_frame_ids": extra, "frames": records,
                   "all_expected_poses_numerically_valid": len(poses) == len(expected_ids),
                   "all_expected_origins_camera_z_positive": bool(len(poses) == len(expected_ids)
                        and all(record.get("origin_camera_z_positive") for record in records)),
                   "tracking_quality_validated": False,
                   "origin_z_note": "Positive origin z is a numeric observation; gauge origin and visibility must be interpreted separately"}


def matching_projection_evidence(args, mesh_path, report, np):
    if args.coordinate_evidence is None:
        report["reference_projection"] = {
            "status": "not_generated_coordinate_correspondence_unverified",
            "reason": "Final global mesh and online ob_in_cam can use different gauge; no implicit matching is assumed"}
        return None
    evidence = read_json(args.coordinate_evidence)
    report["coordinate_evidence"] = file_info(args.coordinate_evidence)
    # Preferred form is the separately source- and numerically-verified V4
    # coordinate audit; a directory-form evidence interface is also supported.
    if "global_refined_pose_file" in evidence and "frame_id_order" in evidence:
        if (evidence.get("passed") is not True or evidence.get("metric_units") != "meters"
                or evidence.get("camera_convention") != "OpenCV"
                or evidence.get("gt_available") is not False
                or evidence.get("global_refined_poses_camera_in_object") is not True
                or evidence.get("online_pose_file_object_in_camera") is not True
                or Path(evidence.get("pipeline", "")).resolve() != args.reconstruction):
            raise ValueError("Coordinate audit does not confirm metric OpenCV pose conventions for this reconstruction")
        anchor = float(evidence.get("refined_first_frame_anchor_max_abs", float("inf")))
        offset = np.asarray(evidence.get("theoretical_offset_if_fixed_first_pose"), dtype=np.float64)
        if (not np.isfinite(anchor) or anchor > 1e-6 or offset.shape != (4, 4)
                or not np.allclose(offset, np.eye(4), rtol=0, atol=1e-8)):
            raise ValueError("Final metric mesh/online object-gauge offset is not confirmed as identity")
        hashes = evidence.get("sha256", {})
        mesh_info = file_info(mesh_path)
        if not isinstance(hashes, dict) or hashes.get(str(mesh_path)) != mesh_info["sha256"]:
            raise ValueError("Coordinate audit SHA table does not match the selected final metric mesh")
        sources = [file_info(Path(name), digest) for name, digest in sorted(hashes.items())]
        pose_path = Path(evidence["global_refined_pose_file"]).resolve(strict=True)
        keyframes_path = Path(evidence["global_keyframe_yaml"]).resolve(strict=True)
        if (args.reconstruction not in pose_path.parents or args.reconstruction not in keyframes_path.parents
                or not evidence.get("source_formula")):
            raise ValueError("Coordinate audit poses/keyframes/formula are outside reconstruction or absent")
        identifiers = evidence["frame_id_order"]
        if (not isinstance(identifiers, list) or not identifiers or len(set(identifiers)) != len(identifiers)
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value) for value in identifiers)):
            raise ValueError("Coordinate audit keyframe order is invalid")
        global_poses = np.loadtxt(str(pose_path), dtype=np.float64)
        if global_poses.shape != (4 * len(identifiers), 4) or not np.isfinite(global_poses).all():
            raise ValueError("Global pose file shape does not match audited keyframe order")
        global_poses = global_poses.reshape(-1, 4, 4)
        entries = {str(item.get("frame_id")): item for item in evidence.get("frames", [])}
        if set(entries) != set(identifiers):
            raise ValueError("Coordinate audit per-frame matrices do not match its keyframe list")
        pose_directory = args.output / "estimated_refined_poses"
        pose_directory.mkdir()
        for index, identifier in enumerate(identifiers):
            entry = entries[identifier]
            recorded_camera_in_object = np.asarray(entry["camera_in_object_matrix"], dtype=np.float64)
            recorded_object_in_camera = np.asarray(entry["object_in_camera_matrix"], dtype=np.float64)
            inverse = np.linalg.inv(global_poses[index])
            if (entry.get("global_row_index") != index
                    or recorded_camera_in_object.shape != (4, 4) or recorded_object_in_camera.shape != (4, 4)
                    or not np.allclose(global_poses[index], recorded_camera_in_object, rtol=0, atol=1e-8)
                    or not np.allclose(inverse, recorded_object_in_camera, rtol=0, atol=1e-8)):
                raise ValueError("Coordinate audit matrix differs from original refined pose file")
            np.savetxt(str(pose_directory / (identifier + ".txt")), inverse, fmt="%.12g")
        report["reference_projection"] = {
            "status": "matching_global_keyframe_coordinates_audited_requires_visual_review",
            "source_formula": evidence["source_formula"], "source_files": sources,
            "source_pose_definition": "T_object_from_camera in meters, OpenCV camera convention",
            "projection_pose_definition": "T_camera_from_final_metric_mesh = inverse(audited T_object_from_camera)",
            "pose_directory": str(pose_directory), "refined_keyframe_ids": identifiers,
            "refined_keyframe_count": len(identifiers), "pose_is_ground_truth": False,
            "online_remaining_frames_are_not_global_refined": True,
        }
        return pose_directory, identifiers
    if (evidence.get("mesh_and_poses_same_coordinate_frame") is not True
            or evidence.get("pose_definition") != "T_camera_from_final_metric_mesh"
            or evidence.get("mesh_sha256") != file_info(mesh_path)["sha256"]
            or not evidence.get("source_formula") or not evidence.get("source_files")):
        raise ValueError("Projection evidence does not establish matching final metric mesh/pose coordinates")
    directory = Path(evidence["pose_directory"]).resolve(strict=True)
    if args.reconstruction not in directory.parents:
        raise ValueError("Matching projection poses must remain inside reconstruction")
    source_records = []
    for source in evidence["source_files"]:
        source_records.append(file_info(Path(source["path"]), source["sha256"]))
    report["reference_projection"] = {"status": "matching_frame_documented_requires_visual_review",
                                       "source_formula": evidence["source_formula"],
                                       "source_files": source_records,
                                       "pose_directory": str(directory), "pose_definition": evidence["pose_definition"],
                                       "pose_is_ground_truth": False}
    return directory, report["expected_frame_ids"]


def reference_overlays(mesh, poses, args, report, np, cv2, frame_ids=None,
                       folder="reference_overlays", report_key="reference_projection", label="estimated refined"):
    K = np.loadtxt(str(args.scene / "cam_K.txt")).reshape(3, 3)
    if not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0:
        raise ValueError("Invalid prepared camera matrix")
    report["camera_matrix"] = K.tolist()
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    edges, edge_count = sampled_edges(faces, np, maximum=5000)
    minimum, maximum = vertices.min(axis=0), vertices.max(axis=0)
    corners = np.array([[x, y, z] for x in (minimum[0], maximum[0])
                        for y in (minimum[1], maximum[1]) for z in (minimum[2], maximum[2])])
    box_edges = [(first, second) for first in range(8) for second in range(first + 1, 8)
                 if np.count_nonzero(corners[first] != corners[second]) == 1]
    report[report_key]["overlays"] = []
    (args.output / folder).mkdir(exist_ok=True)
    for identifier in (frame_ids or report["expected_frame_ids"]):
        frame = {"id": identifier, "pose_is_ground_truth": False}
        report[report_key]["overlays"].append(frame)
        if identifier not in poses:
            frame["status"] = "missing_or_invalid_matching_pose"
            continue
        image_path = args.scene / "rgb" / (identifier + ".png")
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Cannot read prepared RGB " + str(image_path))
        height, width = image.shape[:2]
        pose = poses[identifier]
        transformed = vertices @ pose[:3, :3].T + pose[:3, 3]
        positive = transformed[:, 2] > 0.001
        projected = np.full((len(vertices), 2), np.nan)
        raw_projection = transformed[positive] @ K.T
        projected[positive] = raw_projection[:, :2] / raw_projection[:, 2:3]
        valid_faces = faces[np.all(positive[faces], axis=1)]
        silhouette = np.zeros((height, width), dtype=np.uint8)
        count_in_view = 0
        for triangle in valid_faces:
            points = projected[triangle]
            if (points[:, 0].max() < 0 or points[:, 0].min() >= width
                    or points[:, 1].max() < 0 or points[:, 1].min() >= height):
                continue
            if np.abs(points).max() > 1000000:
                continue
            cv2.fillConvexPoly(silhouette, np.rint(points).astype(np.int32), 255)
            count_in_view += 1
        tint = image.copy()
        tint[silhouette > 0] = [210, 150, 40]
        overlay = cv2.addWeighted(image, 0.7, tint, 0.3, 0)
        for first, second in edges:
            if positive[first] and positive[second]:
                segment = projected[[first, second]]
                if np.abs(segment).max() < 1000000:
                    points = np.rint(segment).astype(np.int32)
                    ok, start, end = cv2.clipLine((0, 0, width, height), tuple(points[0]), tuple(points[1]))
                    if ok:
                        cv2.line(overlay, start, end, (170, 115, 30), 1, cv2.LINE_AA)
        contour = cv2.findContours(silhouette, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
        cv2.drawContours(overlay, contour, -1, (255, 80, 0), 2)
        camera_corners = corners @ pose[:3, :3].T + pose[:3, 3]
        if np.all(camera_corners[:, 2] > 0.001):
            box_uv = camera_corners @ K.T
            box_uv = box_uv[:, :2] / box_uv[:, 2:3]
            if np.isfinite(box_uv).all() and np.abs(box_uv).max() < 1000000:
                box_uv = np.rint(box_uv).astype(np.int32)
                for first, second in box_edges:
                    cv2.line(overlay, tuple(box_uv[first]), tuple(box_uv[second]), (0, 255, 255), 1, cv2.LINE_AA)
        axis_length = float(np.max(maximum - minimum) * 0.25)
        axes = np.vstack([np.zeros(3), np.eye(3) * axis_length])
        camera_axes = axes @ pose[:3, :3].T + pose[:3, 3]
        if np.all(camera_axes[:, 2] > 0.001):
            axis_uv = camera_axes @ K.T
            axis_uv = axis_uv[:, :2] / axis_uv[:, 2:3]
            if np.isfinite(axis_uv).all() and np.abs(axis_uv).max() < 1000000:
                axis_uv = np.rint(axis_uv).astype(np.int32)
                for index, color in enumerate(((0, 0, 255), (0, 220, 0), (255, 0, 0)), 1):
                    cv2.line(overlay, tuple(axis_uv[0]), tuple(axis_uv[index]), color, 2, cv2.LINE_AA)
        # Comparison mask remains an observation, never pixel ground truth.
        mask_path = args.scene / "masks" / (identifier + ".png")
        mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        if mask is not None and mask.ndim == 2 and mask.shape == silhouette.shape:
            contours = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
            cv2.drawContours(overlay, contours, -1, (0, 220, 0), 1)
        cv2.putText(overlay, identifier + " " + label + "; NOT GT", (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.putText(overlay, "Blue: mesh | Yellow: box | Green: observed mask", (10, height - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1, cv2.LINE_AA)
        target = args.output / folder / (identifier + ".png")
        if not cv2.imwrite(str(target), overlay):
            raise RuntimeError("Cannot save reference overlay")
        frame.update(status="projected_requires_manual_review", image=file_info(target),
                     input_rgb=file_info(image_path), camera_positive_vertices=int(positive.sum()),
                     camera_nonpositive_vertices=int((~positive).sum()),
                     projected_triangles_in_view=count_in_view, projected_silhouette_pixels=int(np.count_nonzero(silhouette)),
                     display_edges=len(edges), total_edges=edge_count,
                     mesh_origin_axis_length_m=axis_length,
                     hidden_surface_removal=False, physical_visibility_validated=False,
                     tracking_quality_validated=False)


def run(args, report):
    import cv2
    import numpy as np
    import trimesh
    audit_official_export_source(args.repo, report)
    mesh_path = choose_mesh(args.reconstruction, args.mesh)
    report["metric_mesh"] = file_info(mesh_path)
    mesh = trimesh.load(str(mesh_path), force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("Expected a triangle mesh")
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3
            or len(vertices) < 4 or len(faces) < 4 or not np.isfinite(vertices).all()
            or np.any(faces < 0) or np.any(faces >= len(vertices))):
        raise ValueError("Mesh has invalid vertices/faces or nonfinite geometry")
    bounds = np.stack([vertices.min(axis=0), vertices.max(axis=0)])
    area_twice = np.linalg.norm(np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                                         vertices[faces[:, 2]] - vertices[faces[:, 0]]), axis=1)
    report["mesh_geometry"] = {
        "vertices": len(vertices), "triangles": len(faces), "finite_vertices": True,
        "valid_face_indices": True, "degenerate_triangles_area_under_1e_12_m2": int(np.count_nonzero(area_twice < 2e-12)),
        "axis_aligned_bounds_m": bounds.tolist(), "axis_aligned_extents_m": (bounds[1] - bounds[0]).tolist(),
        "mesh_units": "meters from BundleSDF textured_mesh real-world export",
        "units_independently_measured": False, "physical_dimensions_validated": False,
        "connected_components_vertex_topology": mesh_components(vertices, faces, np),
        "component_method_note": "Vertex connectivity without welding; duplicated texture seams can split components",
        "mesh_is_ground_truth": False, "mesh_quality_validated": False,
    }
    expected_ids = ["{:06d}".format(index) for index in range(args.expected_frames)]
    if sorted(path.stem for path in (args.scene / "rgb").glob("*.png")) != expected_ids:
        raise ValueError("Prepared scene does not contain the expected full reference ring")
    report["expected_frame_ids"] = expected_ids
    online_poses, report["online_pose_numeric_audit"] = audit_pose_directory(args.reconstruction / "ob_in_cam", expected_ids, np)
    report["online_pose_numeric_audit"]["definition_status"] = "Online estimate gauge; do not pair with final globally refined mesh implicitly"
    static_mesh_views(mesh, args.output, report, np, cv2)
    matched = matching_projection_evidence(args, mesh_path, report, np)
    if matched is not None:
        directory, refined_ids = matched
        poses, audit = audit_pose_directory(directory, refined_ids, np)
        report["matching_pose_numeric_audit"] = audit
        reference_overlays(mesh, poses, args, report, np, cv2, frame_ids=refined_ids)
        # Audit evidence establishes the same metric object gauge, but online
        # poses remain earlier estimates; show them only as clearly labeled
        # historical diagnostics, never substitute them for global refinement.
        if "global_refined_pose_file" in read_json(args.coordinate_evidence):
            report["online_historical_projection"] = {
                "status": "historical_online_estimates_diagnostic_only",
                "not_global_refined": True, "tracking_quality_validated": False,
                "coordinate_basis": "Separately verified global first-frame anchor/metric export audit",
                "pose_is_ground_truth": False,
            }
            reference_overlays(mesh, online_poses, args, report, np, cv2,
                               folder="online_historical_overlays", report_key="online_historical_projection",
                               label="HISTORICAL online")
    valid = (report["online_pose_numeric_audit"]["all_expected_poses_numerically_valid"]
             and report["online_pose_numeric_audit"]["all_expected_origins_camera_z_positive"])
    if matched is not None:
        valid = (valid and report["matching_pose_numeric_audit"]["all_expected_poses_numerically_valid"]
                 and report["matching_pose_numeric_audit"]["all_expected_origins_camera_z_positive"])
    file_info(mesh_path, report["metric_mesh"]["sha256"])
    report.update(passed=valid, status="numeric_audit_completed_requires_manual_geometry_and_projection_review",
                  cpu_only=True, gpu_used=False, tracking_quality_validated=False,
                  pose_accuracy_evaluated=False, physical_mesh_scale_validated=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconstruction", type=Path, required=True, help="BundleSDF pipeline output directory")
    parser.add_argument("--scene", "--sceneprepared", dest="scene", type=Path, required=True,
                        help="Single prepared complete reference scene")
    parser.add_argument('--expected-frames', type=int, choices=(36, 72), default=36)
    parser.add_argument("--output", type=Path, required=True, help="New CPU audit directory")
    parser.add_argument("--mesh", type=Path, help="Optional exact final textured_mesh.obj")
    parser.add_argument("--repo", type=Path, default=Path("/workspace/BundleSDF"),
                        help="Local official source, read as export provenance without importing its modules")
    parser.add_argument("--coordinate-evidence", type=Path,
                        help="Optional JSON establishing matching final mesh and refined pose gauge before projection")
    args = parser.parse_args()
    for name in ("reconstruction", "scene", "output", "mesh", "coordinate_evidence", "repo"):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).expanduser().resolve())
    report = {"schema_version": 1, "passed": False, "started_at_utc": utc_now(), "frames": [],
              "reconstruction": str(args.reconstruction), "scene": str(args.scene), "output": str(args.output),
              "status": "validating", "cpu_only": True, "gpu_used": False, "network_or_ssh_used": False,
              "gt_available": False, "gt_or_add_metrics_computed": False, "tracking_quality_validated": False,
              "limitations": [
                  "Numerically valid poses do not establish correct tracking.",
                  "Metric bounds describe reconstructed geometry, not independently measured object dimensions.",
                  "Final global mesh and online poses can use different gauges; matching coordinates must be evidenced.",
                  "CPU silhouettes include every front-of-camera triangle; occlusion/hidden-surface accuracy is not certified.",
                  "Raw and failed reconstruction evidence is retained; this tool modifies only its new output directory.",
              ]}
    created = False
    started = time.monotonic()
    try:
        if os.path.lexists(str(args.output)):
            raise ValueError("Output already exists; choose a new directory")
        for source in (args.reconstruction, args.scene):
            if source == args.output or source in args.output.parents or args.output in source.parents:
                raise ValueError("Input/output containment is refused")
        args.output.mkdir(parents=True, exist_ok=False)
        created = True
        for folder in ("mesh_views", "reference_overlays"):
            (args.output / folder).mkdir()
        report["script"] = file_info(Path(__file__))
        run(args, report)
    except (Exception, KeyboardInterrupt) as error:
        report.update(passed=False, status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                      error={"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
        traceback.print_exc()
    finally:
        report.update(ended_at_utc=utc_now(), elapsed_seconds=time.monotonic() - started)
        if created:
            write_report(report, args.output / "report.json")
    print(json.dumps({"passed": report["passed"], "status": report["status"],
                      "report": str(args.output / "report.json") if created else None,
                      "tracking_quality_validated": False}), flush=True)
    return 0 if report["passed"] else (130 if report["status"] == "interrupted" else 1)


if __name__ == "__main__":
    sys.exit(main())
