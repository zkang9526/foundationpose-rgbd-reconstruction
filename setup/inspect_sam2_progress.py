"""Package download sizes only; no environment or unrelated temporary content."""
from pathlib import Path
import json

out = []
for directory in Path('/tmp').glob('pip-unpack-*'):
    try:
        for p in directory.glob('*'):
            if p.name.startswith(('torch-2.5.1', 'torchvision-0.20', 'triton-3.1')):
                out.append(dict(package=p.name, bytes=p.stat().st_size))
    except OSError:
        pass
print(json.dumps(out))
