"""Explicit inherited CUDA library directories for the isolated SAM2 Python."""
import os
from pathlib import Path


def sam2_runtime_environment(root):
    root = Path(root)
    bases = [root / 'foundationpose_data/environments/sam2/lib/python3.11/site-packages/nvidia',
             Path('/home/ni/anaconda3/envs/foundationpose/lib/python3.11/site-packages/nvidia')]
    directories = [str(path) for base in bases for path in sorted(base.glob('*/lib')) if path.is_dir()]
    child = os.environ.copy()
    child['LD_LIBRARY_PATH'] = ':'.join(directories + ([child['LD_LIBRARY_PATH']] if child.get('LD_LIBRARY_PATH') else []))
    return child, directories
