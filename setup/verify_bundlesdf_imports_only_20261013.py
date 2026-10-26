#!/usr/bin/env python3
"""Isolated import-only process, do not mix reference model CPU allocation."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
sys.path.insert(0, '/workspace/BundleSDF')
sys.path.insert(0, '/workspace/BundleSDF/BundleTrack/build')
report = {'passed': False, 'scope': 'imports_only_no_model_construction', 'modules': []}
import torch
report['torch'] = torch.__version__
for name in ['kaolin', 'common', 'gridencoder', 'my_cpp', 'bundlesdf', 'run_custom']:
    module = importlib.import_module(name)
    path = Path(module.__file__)
    report['modules'].append({'name': name, 'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
report['passed'] = True
path = Path(args.output)
if path.exists():
    raise FileExistsError(str(path))
path.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
