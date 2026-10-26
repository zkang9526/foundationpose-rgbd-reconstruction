#!/usr/bin/env python3
"""CPU-only import and exact vendor LoFTR checkpoint validation; no GPU inference."""
import argparse
import datetime
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import traceback

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default='/workspace/BundleSDF')
    parser.add_argument('--output', required=True)
    parser.add_argument('--require-weight', action='store_true')
    args = parser.parse_args()
    repo = Path(args.repo)
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / 'BundleTrack/build'))
    output = Path(args.output)
    if output.exists():
        raise FileExistsError('New evidence path required: ' + str(output))
    report = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'repo': str(repo), 'python': sys.version, 'cpu_only': True, 'checks': [], 'passed': False}
    try:
        import torch
        report['torch_version'] = torch.__version__
        for name in ['kaolin', 'common', 'gridencoder', 'my_cpp', 'bundlesdf', 'run_custom']:
            module = importlib.import_module(name)
            path = getattr(module, '__file__', None)
            report['checks'].append({'name': name, 'import': True, 'file': path,
                                     'sha256': sha(path) if path and Path(path).is_file() else None})
        weight = repo / 'BundleTrack/LoFTR/weights/outdoor_ds.ckpt'
        if weight.is_file():
            from BundleTrack.LoFTR.src.loftr import LoFTR, default_cfg
            checkpoint = torch.load(str(weight), map_location='cpu')
            matcher = LoFTR(config=default_cfg).cpu()
            result = matcher.load_state_dict(checkpoint['state_dict'], strict=True)
            finite = all(torch.isfinite(value).all().item() for value in matcher.state_dict().values())
            report['weight'] = {'file': str(weight), 'size': weight.stat().st_size, 'sha256': sha(weight),
                                'state_dict_keys': len(checkpoint['state_dict']), 'strict_load_passed': True,
                                'missing_keys': result.missing_keys, 'unexpected_keys': result.unexpected_keys,
                                'finite_parameters': finite}
            if not finite:
                raise RuntimeError('Non-finite LoFTR parameters')
        elif args.require_weight:
            raise FileNotFoundError(str(weight))
        else:
            report['weight'] = {'exists': False, 'validation_pending': True}
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)

if __name__ == '__main__':
    main()
