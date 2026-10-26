#!/usr/bin/env python3
"""Preserve source and align optional ray IDs with GPU ray_batch before masks."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from deploy_bundlesdf_isolated_20261013 import CODE, AUDIT

source = CODE/'nerf_runner.py'
original = source.read_text()
backup = AUDIT/'nerf_runner_before_ray_device_v4.py'
if backup.exists():
    raise FileExistsError(str(backup))
backup.write_text(original)
signature = '  def render_rays(self,ray_batch,retraw=True,lindisp=False,perturb=False,raw_noise_std=0.,depth=None, get_normals=False, ray_ids=None):'
start = original.index(signature)
point = original.index('    N_rays = ray_batch.shape[0]\n', start)
replacement = '''    N_rays = ray_batch.shape[0]
    # DataLoader keeps row IDs on CPU while batches/masks are moved to CUDA.
    if ray_ids is not None:
      ray_ids = ray_ids.to(device=ray_batch.device)
'''
updated = original[:point] + original[point:].replace('    N_rays = ray_batch.shape[0]\n', replacement, 1)
old_argument = 'ray_ids=ray_ids[invalid_depth_mask],rays_d=viewdirs[invalid_depth_mask]'
new_argument = 'ray_ids=ray_ids[invalid_depth_mask] if ray_ids is not None else None,rays_d=viewdirs[invalid_depth_mask]'
if updated.count(old_argument) != 1:
    raise RuntimeError('Expected unique invalid-depth ray-ID call')
updated = updated.replace(old_argument, new_argument)
ast.parse(updated)
source.write_text(updated)
diff = subprocess.run(['git', '-C', str(CODE), 'diff'], capture_output=True, text=True, check=True)
(AUDIT/'deployment_adaptations_v4_ray_device.diff').write_text(diff.stdout)
report = {'source': str(source), 'backup': str(backup),
          'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
          'after_sha256': hashlib.sha256(updated.encode()).hexdigest(),
          'syntax_ast_passed': True,
          'root_cause': 'DataLoader.batch_ray_ids CPU torch.randperm; batch.cuda() causes GPU valid_depth_mask index into CPU ray_ids.',
          'change': 'Align optional ray IDs with ray_batch.device before sampling; retain values/order; guard optional None.',
          'sampling_algorithm_changed': False, 'gpu_retest_pending': True}
(AUDIT/'ray_device_patch_v4.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
print(diff.stdout)
