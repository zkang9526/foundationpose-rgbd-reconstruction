#!/usr/bin/env python3
"""Read a failed small stage inventory; no source or payload changes."""
import json
from pathlib import Path

stage = Path('/data/ZJC/foundationPos/foundationpose_data/incoming/cup_pilot_updates_20261014_0220')
manifest = json.loads((stage / 'manifest.json').read_text())
expected = {item['path'] for item in manifest['files']}
actual = {path.relative_to(stage / 'payload').as_posix()
          for path in (stage / 'payload').rglob('*') if path.is_file()}
print(json.dumps({'extra': sorted(actual - expected), 'missing': sorted(expected - actual)}, indent=2))
