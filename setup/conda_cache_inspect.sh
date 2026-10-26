#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile, BadZipFile
destination = Path('/home/ni/foundationpose_data/conda_setup/cached_wheels')
destination.mkdir(exist_ok=True)
reusable = {'triton', 'sympy', 'mpmath', 'markupsafe', 'filelock', 'typing_extensions', 'networkx', 'jinja2', 'fsspec', 'numpy', 'pillow', 'scipy', 'opencv-python', 'cmake', 'ninja', 'setuptools', 'pybind11'}
for path in Path('/home/ni/.cache/pip').rglob('*.body'):
    try:
        with ZipFile(path) as wheel:
            metadata = next((x for x in wheel.namelist() if x.endswith('.dist-info/METADATA')), None)
            if not metadata:
                continue
            lines = wheel.read(metadata).decode(errors='replace').splitlines()
            name = next(x[6:] for x in lines if x.startswith('Name: '))
            version = next(x[9:] for x in lines if x.startswith('Version: '))
            tags_file = metadata.replace('METADATA', 'WHEEL')
            tags = [x[5:] for x in wheel.read(tags_file).decode().splitlines() if x.startswith('Tag: ')]
            if not (name.startswith('nvidia-') or name.lower() in reusable):
                continue
            compatible = [tag for tag in tags if tag.startswith(('py3-', 'cp311-')) or '-abi3-' in tag]
            if not compatible:
                continue
            interpreter, abi, _ = compatible[0].split('-', 2)
            platforms = [tag.split('-', 2)[2] for tag in compatible
                         if tag.startswith(interpreter + '-' + abi + '-')]
            tag = '{}-{}-{}'.format(interpreter, abi, '.'.join(platforms))
            filename = '{}-{}-{}.whl'.format(name.replace('-', '_'), version, tag)
            target = destination / filename
            if not target.exists():
                target.symlink_to(path)
            print(name, version, compatible[0], path.stat().st_size, path)
    except (BadZipFile, KeyError, StopIteration):
        pass
PY
