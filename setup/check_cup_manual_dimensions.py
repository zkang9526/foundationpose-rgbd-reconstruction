#!/usr/bin/env python3
"""Record coarse dimension screens without treating arbitrary mesh axes as GT."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--measurements', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    root = args.root.resolve(strict=True)
    if args.output.exists():
        p.error('Preserve earlier evidence; choose a new output file')
    import numpy as np
    manual = json.loads(args.measurements.read_text(encoding='utf-8'))
    actual = np.asarray([manual['height_mm'], manual['body_outer_diameter_mm'],
                         manual['overall_width_including_handle_mm']], dtype=np.float64)
    if manual['units'] != 'millimeters' or not np.isfinite(actual).all() or np.any(actual <= 0):
        raise ValueError('Expected finite positive human dimensions in millimeters')
    meshes = (
        ('side_default_v4', 'cup_reconstruction_side36_v4_20261013_2150',
         '400e8409fa537ae2b20995c93c93aa05564408a158e82e5bb05bee5e87bb5c33'),
        ('top_default_v1', 'cup_reconstruction_top36_v1_20261013_2220',
         'e0e5e16781dcc28847a0ab991f182c04cd98f415751ef1742d8bc78a41ab5134'),
        ('side_frozen_pose_v1', 'cup_reconstruction_side36_frozen_pose_v1_20261013_2238',
         'a5edffb0237aaefab7ee83f9601c9e1586128d32a0bc163c79e8c85095feda3f'),
    )
    result = {'passed': False, 'purpose': 'approximate scale screen, not geometric or pose accuracy',
              'measurements_path': args.measurements.resolve().relative_to(root).as_posix(),
              'measurements_sha256': sha(args.measurements), 'human_measurements': manual,
              'sorted_manual_spans_mm': sorted(actual.tolist()),
              'mesh_units': 'meters inherited from validated real-world export',
              'pose_ground_truth_available': False, 'semantic_mesh_axes_confirmed': False,
              'scale_accuracy_validated': False, 'uniform_rescale_performed': False,
              'source_meshes_or_poses_changed': False, 'meshes': [],
              'limitations': [
                  'Human values are approximate; no instrument or numeric uncertainty was supplied.',
                  'Original mesh XYZ axes are arbitrary reconstruction object frames, not semantic cup axes.',
                  'PCA spans and sorted associations are heuristic diagnostics, not measured height/diameter/width.',
                  'PCA is affected by deformation and vertex sampling; it is not a minimum-volume bounding box.',
                  'A uniform scale factor cannot repair folded surfaces, missing handle geometry or wrong pose.',
                  'All previous negative visual QA and exit139 evidence remain valid.',
              ]}
    for role, name, expected in meshes:
        path = root / 'foundationpose_data/derived' / name / 'pipeline/textured_mesh.obj'
        digest = sha(path)
        if digest != expected:
            raise ValueError('Candidate mesh differs from verified export: ' + role)
        vertices = np.asarray([list(map(float, line.split()[1:4]))
                               for line in path.read_text(encoding='utf-8').splitlines()
                               if line.startswith('v ')], dtype=np.float64) * 1000.0
        if vertices.shape[1] != 3 or not np.isfinite(vertices).all():
            raise ValueError('Nonfinite mesh vertices')
        unique = np.unique(vertices, axis=0)
        centered = unique - unique.mean(axis=0)
        eigenvalues, axes = np.linalg.eigh(centered.T @ centered / len(centered))
        axes = axes[:, np.argsort(eigenvalues)[::-1]]
        principal = np.ptp(centered @ axes, axis=0)
        sorted_principal = np.sort(principal)
        result['meshes'].append({
            'role': role, 'path': path.relative_to(root).as_posix(), 'sha256': digest,
            'exported_vertices': len(vertices), 'unique_vertex_positions': len(unique),
            'original_xyz_bounds_mm': [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
            'original_xyz_aabb_spans_mm': np.ptp(vertices, axis=0).tolist(),
            'original_xyz_spans_are_semantic_cup_dimensions': False,
            'pca_frame_spans_mm': principal.tolist(), 'sorted_pca_spans_mm': sorted_principal.tolist(),
            'sorted_pca_to_sorted_manual_ratio_diagnostic': (sorted_principal / np.sort(actual)).tolist(),
            'ratio_is_true_dimension_error': False, 'reliable_geometry_accepted': False,
        })
        if sha(path) != digest:
            raise ValueError('Mesh changed during screen')
    if sha(args.measurements) != result['measurements_sha256']:
        raise ValueError('Manual measurement record changed during screen')
    result['passed'] = True
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
