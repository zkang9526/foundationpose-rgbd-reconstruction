"""CPU-only provenance/frame contract for a neural-field-derived FP model."""
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_neural_model(manifest_path, expected_manifest_sha256=None):
    path=Path(manifest_path).resolve(strict=True)
    manifest_sha=sha(path)
    if expected_manifest_sha256 and manifest_sha!=expected_manifest_sha256:
        raise ValueError('Neural pose manifest SHA mismatch')
    manifest=json.loads(path.read_text(encoding='utf-8'))
    identity=[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]]
    if (manifest.get('passed') is not True or manifest.get('backend')!='neural_field_surface_foundationpose'
        or manifest.get('online_unit')!='m' or manifest.get('recentered') is not False
        or manifest.get('rescaled') is not False or manifest.get('direct_neural_renderer') is not False
        or manifest.get('surface_from_field_object')!=identity
        or manifest.get('pose_definition')!='T_camera_from_field_object_meters'):
        raise ValueError('Unsupported neural pose model units, object frame or backend')
    if manifest.get('model_file')!='model.obj':raise ValueError('Unexpected model filename')
    for key in ['model_sha256','source_checkpoint_sha256','source_config_sha256','source_metric_surface_sha256']:
        if not re.fullmatch('[0-9a-f]{64}',str(manifest.get(key,''))):raise ValueError('Missing provenance SHA: '+key)
    model=(path.parent/'model.obj').resolve(strict=True)
    model.relative_to(path.parent)
    if sha(model)!=manifest['model_sha256']:raise ValueError('Neural field surface/color model SHA mismatch')
    return dict(path=str(model),sha256=manifest['model_sha256'],unit='m',manifest_path=str(path),
                manifest_sha256=manifest_sha,backend=manifest['backend'],direct_neural_renderer=False,
                field_checkpoint_sha256=manifest['source_checkpoint_sha256'],
                pose_definition=manifest['pose_definition'],field_object_from_model=identity,
                source_training_ids=manifest['source_training_ids'],reserved_view_ids=manifest['reserved_view_ids'],
                geometry_quality_accepted=False,is_ground_truth=False,
                description='Learned neural SDF surface and learned colors; official FoundationPose triangle rendering')
