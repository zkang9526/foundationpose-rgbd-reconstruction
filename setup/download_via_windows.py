#!/usr/bin/env python3
"""Download verified official assets into this Windows workspace."""
import json
from pathlib import Path
import sys

workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / '.bootstrap_tools'))
import gdown

destination = workspace / '.assets_download'
files = [
    ('1E9FPB5WFIBMLrOJqZLpoVOK4Mjzrrxhv', 'refiner_model_best.pth'),
    ('1Zdjnkn4EHOI5_k08apofwRgTjWpai4E4', 'scorer_model_best.pth'),
    ('1AwV9sESDKMgXGUu2n1o0Pc4x2JGYdVB3', 'mustard0.zip'),
]
destination.mkdir(exist_ok=True)
for file_id, filename in files:
    path = destination / filename
    if not path.is_file():
        print('Downloading official ' + filename, flush=True)
        temporary = path.with_name(path.name + '.download')
        result = gdown.download(id=file_id, output=str(temporary), quiet=True)
        if result is None:
            raise RuntimeError('Download failed: ' + filename)
        temporary.replace(path)
    print(json.dumps(dict(file=filename, bytes=path.stat().st_size)), flush=True)
