#!/usr/bin/env python3
"""Pinned metric cup mesh profiles shared by the legacy and fast live entries."""
import hashlib
from pathlib import Path

MESH_PROFILES = {
    'legacy': dict(relative='derived/cup_new72_geometric_tsdf_v2_clean_20261014_1920/cup_clean.obj',
                   sha256='5b52c3fd9904aaac2b155960d6faabb72be9330e8bb6741c470ec1f4dae4d9de',
                   description='2026-10-14 geometric TSDF candidate'),
    'redcup72': dict(relative='derived/redcup_geometric_clean_v1_20261017_2050/cup_clean.obj',
                     sha256='88e127e4cd4388bedcd77e7a0fb2cd5bde31c0557f861a7b60f8250bdac32f53',
                     description='2026-10-17 reviewed red-painted cup72 geometric TSDF candidate'),
}


def add_mesh_arguments(parser):
    parser.add_argument('--mesh-profile', choices=tuple(MESH_PROFILES), default='legacy',
                        help='Pinned metric mesh: legacy or the reviewed redcup72 candidate')


def resolve_mesh(dataroot, profile):
    """Reject missing, changed, or data-root-escaping meshes before camera access."""
    spec = MESH_PROFILES[profile]
    base = Path(dataroot).resolve(strict=True)
    path = (base / spec['relative']).resolve(strict=True)
    path.relative_to(base)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != spec['sha256']:
        raise ValueError('Selected metric mesh SHA mismatch: ' + profile)
    return dict(profile=profile, path=str(path), relative=path.relative_to(base).as_posix(),
                sha256=digest, description=spec['description'], unit='m',
                geometry_quality_accepted=False, is_ground_truth=False)
