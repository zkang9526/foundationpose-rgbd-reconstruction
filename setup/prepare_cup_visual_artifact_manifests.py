#!/usr/bin/env python3
"""Write/verify manifests only for selected new derived cup visual artifacts."""
import argparse
import subprocess
import sys
from pathlib import Path
import re
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--check-absent', action='store_true')
    parser.add_argument('--folders', nargs='+', required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    derived = root / 'foundationpose_data/derived'
    folders = []
    for name in args.folders:
        if not re.fullmatch(r'cup_[A-Za-z0-9._-]+', name):
            raise ValueError('Expected one explicit derived cup directory name')
        folder = derived / name
        if args.check_absent:
            if os.path.lexists(str(folder)):
                raise FileExistsError('Preserve existing destination: ' + str(folder))
            folders.append(folder)
            continue
        if folder.is_symlink() or folder.resolve(strict=True).parent != derived.resolve(strict=True):
            raise ValueError('Artifact directory resolves outside derived project data')
        for item in folder.rglob('*'):
            if item.is_symlink() or folder.resolve() not in item.resolve().parents:
                raise ValueError('Artifact contains an indirect or outside path')
        if args.write and (folder / 'transfer_manifest.json').exists():
            raise FileExistsError('Refusing to replace an existing artifact transfer manifest')
        folders.append(folder)
    if args.check_absent:
        print('All explicit destination folders are absent: ' + ', '.join(str(folder) for folder in folders))
        return
    for folder in folders:
        command = [sys.executable, str(root / 'setup/finalize_transfer.py'), '--root', str(folder)]
        if args.write:
            command.append('--write-manifest')
        print(str(folder), flush=True)
        subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
