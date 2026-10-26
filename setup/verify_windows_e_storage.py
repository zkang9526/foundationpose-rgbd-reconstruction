import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
root = Path(r'E:\foundationPos')
legacy = Path(r'C:\Users\YOUR_USER\Desktop\foundationPos')
assert legacy.resolve(strict=True) == root.resolve(strict=True)
assert args.output.resolve().drive.upper() == 'E:'
policy = json.loads((root/'setup/windows_storage_policy.json').read_text())
observed = {name: os.environ.get(name) for name in policy['environment']}
assert observed == policy['environment'], observed
assert Path(tempfile.gettempdir()).resolve() == Path(policy['environment']['TEMP']).resolve()
with tempfile.NamedTemporaryFile(prefix='foundationpos_e_storage_', suffix='.txt', mode='w+', encoding='utf-8') as stream:
    temp_path = Path(stream.name)
    assert temp_path.resolve().drive.upper() == 'E:'
    stream.write('actual temporary-file write on E\n'); stream.flush()
    temp_written = temp_path.stat().st_size
probe = root/'foundationpose_data/storage_checks/verified_E_20261015.txt'
probe.parent.mkdir(parents=True, exist_ok=True)
probe.write_text('Actual project data write on E; same file through the C compatibility junction.\n', encoding='utf-8')
assert (legacy/probe.relative_to(root)).samefile(probe)
import cv2
import numpy
import pyrealsense2
result = dict(passed=True, project_root=str(root), legacy_resolved=str(legacy.resolve()), sys_prefix=sys.prefix,
              environment=observed, temporary_file_path=str(temp_path), temporary_bytes=temp_written,
              project_probe=str(probe), project_probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
              legacy_is_same_file=True, opencv=cv2.__version__, numpy=numpy.__version__, realsense_imported=True)
args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result), flush=True)
