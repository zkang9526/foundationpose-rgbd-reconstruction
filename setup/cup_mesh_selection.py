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
    'cup_smoothed_20261112': dict(relative='derived/cup_smoothed_20261112/cup_smoothed.obj',
                                sha256='16ffcc896a0a827399143437a0378123dc07c5c7e8d3e85e5378e74c7fa70022',
                                description='2026-11-12 cylinder/dimension-prior cup with mask-inferred handle repair and bounded local smoothing'),
    'neural_field': dict(relative='derived/redcup_neural_pose_model_20261103_v1/model.obj',
                        sha256='af6d62318a540ba29ec62c1d1f67113b954400229147bfadd9d374114fbd14dd',
                        manifest_relative='derived/redcup_neural_pose_model_20261103_v1/manifest.json',
                        manifest_sha256='ad2fc49a2ec2d4305d72213ff3184063ca7dca7f434014311d5cb2e63f05d329',
                        description='2026-11-03 learned neural SDF surface and learned vertex colors; cached GPU triangle renderer'),
    'cup_neural_20261116': dict(relative='derived/cup_neural_20261116_v1/model/model.obj',
                              sha256='b9588de9cc9199ae99ce4bb5231317b892506e93d76177ee8ace333f59efb85c',
                              manifest_relative='derived/cup_neural_20261116_v1/model/manifest.json',
                              manifest_sha256='9363c37d786f2d961c1ef94719ccee80f30fad6e76022d9b40c9f557a057a5d1',
                              description='2026-11-16 local reviewed72 RGB-D, fixed-ICP official neural SDF and learned vertex colors'),
    'cup_neural_20261117': dict(relative='derived/cup_neural_20261117_v1/model/model.obj',
                              sha256='defdda0140708b536c8e1c96fc1f14205efa1ee7af46e41595116fa3c975276a',
                              manifest_relative='derived/cup_neural_20261117_v1/model/manifest.json',
                              manifest_sha256='762f7961489f7b7705ce32b622da71b64a1aec62ba76cb48fb644dc29b03dffd',
                              description='2026-11-17 completed local RGB-D neural SDF and learned vertex colors'),
}


def add_mesh_arguments(parser):
    parser.add_argument('--mesh-profile', choices=tuple(MESH_PROFILES), default='legacy',
                        help='Select a SHA-pinned metric cup model profile')


def resolve_mesh(dataroot, profile):
    """Reject missing, changed, or data-root-escaping meshes before camera access."""
    spec = MESH_PROFILES[profile]
    base = Path(dataroot).resolve(strict=True)
    path = (base / spec['relative']).resolve(strict=True)
    path.relative_to(base)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != spec['sha256']:
        raise ValueError('Selected metric mesh SHA mismatch: ' + profile)
    selection=dict(profile=profile, path=str(path), relative=path.relative_to(base).as_posix(),
                   sha256=digest, description=spec['description'], unit='m',
                   geometry_quality_accepted=False, is_ground_truth=False)
    if 'manifest_relative' in spec:
        from cup_neural_pose_model import validate_neural_model
        manifest=(base/spec['manifest_relative']).resolve(strict=True)
        manifest.relative_to(base)
        proof=validate_neural_model(manifest,spec['manifest_sha256'])
        if Path(proof['path'])!=path:raise ValueError('Neural manifest/profile model mismatch')
        selection.update(proof)
    return selection
