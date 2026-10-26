#!/usr/bin/env python3
"""Strict CPU-only vendor checkpoint check; no forward inference or CUDA calls."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, '/workspace/BundleSDF')
import torch
from BundleTrack.LoFTR.src.loftr import LoFTR, default_cfg

checkpoint_file = Path('/workspace/BundleSDF/BundleTrack/LoFTR/weights/outdoor_ds.ckpt')
checkpoint = torch.load(str(checkpoint_file), map_location='cpu')
matcher = LoFTR(config=default_cfg).cpu()
result = matcher.load_state_dict(checkpoint['state_dict'], strict=True)
finite = all(torch.isfinite(value).all().item() for value in matcher.state_dict().values())
report = {'passed': finite, 'cpu_only': True, 'forward_inference': False,
          'torch': torch.__version__, 'vendor_code': '/workspace/BundleSDF/BundleTrack/LoFTR/src/loftr',
          'checkpoint_file': str(checkpoint_file), 'size': checkpoint_file.stat().st_size,
          'sha256': hashlib.sha256(checkpoint_file.read_bytes()).hexdigest(),
          'strict_load_passed': True, 'state_dict_key_count': len(checkpoint['state_dict']),
          'missing_keys': result.missing_keys, 'unexpected_keys': result.unexpected_keys,
          'finite_parameters': finite}
output = Path('/data/bundlesdf_setup_20261013/loftr_cpu_strict_validation.json')
if output.exists():
    raise FileExistsError(str(output))
output.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
