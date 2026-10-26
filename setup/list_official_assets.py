#!/usr/bin/env python3
import json
import gdown

for label, folder_id in (
    ('weights', '1DFezOAD0oD1BblsXVxqDsl8fj0qzB82i'),
    ('demo', '1pRyFmxYXmAnpku7nGRioZaKrVJtIsroP'),
):
    print('=== ' + label + ' ===', flush=True)
    files = gdown.download_folder(id=folder_id, skip_download=True, quiet=False)
    if files is None:
        raise RuntimeError('Unable to read official ' + label + ' folder')
    print(json.dumps([dict(id=f.id, path=f.path, local_path=f.local_path) for f in files], indent=2), flush=True)
