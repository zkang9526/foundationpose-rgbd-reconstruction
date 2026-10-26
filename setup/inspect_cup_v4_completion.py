#!/usr/bin/env python3
"""Read exact reconstruction report and recorded process status, no mutation."""
import json
from pathlib import Path

root = Path('/data/ZJC/foundationPos')
result = {}
paths = {
    'reconstruction': root / 'foundationpose_data/derived/cup_reconstruction_side36_v4_20261013_2150/report.json',
    'server_run': root / 'foundationpose_data/runs/20261013_215033_528375_cup_bundlesdf_side36_reconstruction_v4_7f5f2c18/run.json',
}
for key, path in paths.items():
    document = json.loads(path.read_text())
    if key == 'reconstruction':
        names = ('passed', 'status', 'elapsed_seconds', 'error', 'metric_textured_mesh_candidates',
                 'estimated_pose_files', 'official_entry_returned', 'repo_commit')
        result[key] = {name: document.get(name) for name in names}
        result[key]['estimated_pose_files'] = len(document.get('estimated_pose_files', []))
    else:
        names = ('run_id', 'status', 'exit_code', 'child_exitcode', 'end', 'duration_seconds', 'warnings')
        result[key] = {name: document.get(name) for name in names}
pipeline = root / 'foundationpose_data/derived/cup_reconstruction_side36_v4_20261013_2150/pipeline'
result['final_mesh_files'] = [{ 'path': str(p), 'bytes': p.stat().st_size }
                            for p in sorted(pipeline.glob('textured_mesh*')) if p.is_file()]
print(json.dumps(result, indent=2))
