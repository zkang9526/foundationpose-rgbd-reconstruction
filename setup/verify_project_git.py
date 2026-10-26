"""Verify clean/dirty recorded Git provenance and safe ignore scope."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from project_git_state import project_git_state


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--child', action='store_true')
    args = p.parse_args()
    if args.child:
        print('Git run-provenance probe; no camera/data operation')
        return
    root, output = args.root.resolve(), args.output.resolve()
    output.relative_to(root / 'foundationpose_data')
    output.mkdir(parents=True, exist_ok=False)
    before = project_git_state(root)
    assert before.get('commit') and not before['dirty'], before
    tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
    forbidden = ['foundationpose_data/', '.windows-camera-venv/', '.camera-venv/', 'reviews/', 'FoundationPose/', 'BundleSDF/']
    assert not any(name.startswith(tuple(forbidden)) for name in tracked)
    ignored = ['foundationpose_data/runs/probe/run.json', '.windows-camera-venv/probe.py', '.camera-venv/probe.py',
               'reviews/probe.png', '.assets_download/probe.pth', 'FoundationPose/probe.py', 'EXPERIMENT_LOG.md', 'ISSUES.md']
    result = subprocess.run(['git', '-C', str(root), 'check-ignore', '--stdin'], input='\n'.join(ignored).encode(), capture_output=True)
    assert set(result.stdout.decode().splitlines()) == set(ignored)

    def recorded_probe(label):
        known = set((root / 'foundationpose_data/runs').iterdir())
        subprocess.run([sys.executable, '-B', str(root / 'setup/run_logged.py'), '--root', str(root), '--label', label,
                        '--', sys.executable, '-B', str(Path(__file__).resolve()), '--child'], check=True)
        added = set((root / 'foundationpose_data/runs').iterdir()) - known
        matching = [folder for folder in added if label in folder.name]
        assert len(matching) == 1
        folder = matching[0]
        info = json.loads((folder / 'project_git.json').read_text(encoding='utf-8'))
        metadata = json.loads((folder / 'environment.json').read_text(encoding='utf-8'))
        assert metadata['project_git'] == info and info['commit'] == before['commit']
        return folder, info

    clean_folder, clean = recorded_probe('git_clean_provenance_probe')
    assert not clean['dirty']
    target = root / 'setup/project_git_state.py'
    original = target.read_bytes()
    changed = original + b'\n# Temporary Git provenance verification marker.\n'
    target.write_bytes(changed)
    try:
        dirty_folder, dirty = recorded_probe('git_dirty_provenance_probe')
        assert dirty['dirty'] and any('project_git_state.py' in v for v in dirty['status_porcelain'])
        patch = dirty_folder / dirty['tracked_diff_snapshot']
        assert b'Temporary Git provenance verification marker' in patch.read_bytes()
        assert hashlib.sha256(patch.read_bytes()).hexdigest() == dirty['snapshot_diff_sha256']
    finally:
        if target.read_bytes() != changed:
            raise RuntimeError('Source changed concurrently; refusing to overwrite it')
        target.write_bytes(original)
    after = project_git_state(root)
    assert after['commit'] == before['commit'] and not after['dirty']
    report = dict(passed=True, commit=before['commit'], branch=before['branch'], tracked_files=len([n for n in tracked if n]),
                  clean_run=clean_folder.name, dirty_run=dirty_folder.name,
                  clean_and_dirty_provenance_verified=True, dirty_patch_and_sha_verified=True,
                  original_source_restored_exactly=hashlib.sha256(target.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest(),
                  runtime_and_models_ignored=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
