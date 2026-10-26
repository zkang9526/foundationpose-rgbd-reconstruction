"""Non-blocking, credential-free project Git state for each recorded run."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def project_git_state(root):
    root = Path(root).resolve()
    if not shutil.which('git') or not (root / '.git').exists():
        return dict(available=False, reason='Project root has no Git repository')

    def run(*args):
        result = subprocess.run(['git', '-C', str(root)] + list(args), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if result.returncode:
            raise RuntimeError('Git inspection failed: ' + args[0])
        return result.stdout

    try:
        try:
            head = run('rev-parse', '--verify', 'HEAD').decode().strip()
        except RuntimeError:
            return dict(available=True, unborn=True, commit=None)
        branch = run('rev-parse', '--abbrev-ref', 'HEAD').decode().strip()
        status = run('status', '--porcelain=v1', '-z', '--untracked-files=all')
        # Paths only; remote URLs, credentials and arbitrary Git config are not collected.
        paths = status.decode('utf-8', errors='replace').split('\0')
        patch = run('diff', '--binary', '--no-ext-diff', 'HEAD', '--')
        return dict(available=True, commit=head, branch=branch, dirty=bool(status),
                    status_porcelain=[p for p in paths if p],
                    tracked_diff_sha256=hashlib.sha256(patch).hexdigest(),
                    tracked_diff_bytes=len(patch))
    except Exception as error:
        return dict(available=True, inspection_error=str(error))


def snapshot_project_git(root, run_dir):
    state = project_git_state(root)
    if state.get('commit') and state.get('dirty'):
        result = subprocess.run(['git', '-C', str(root), 'diff', '--binary', '--no-ext-diff', 'HEAD', '--'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if result.returncode == 0 and len(result.stdout) <= 8 * 1024 ** 2:
            patch = Path(run_dir) / 'project_worktree.patch'
            patch.write_bytes(result.stdout)
            state.update(tracked_diff_snapshot=patch.name,
                         snapshot_diff_sha256=hashlib.sha256(result.stdout).hexdigest(),
                         untracked_contents='Listed by path; selected setup source files are separately snapshotted by recorder')
    (Path(run_dir) / 'project_git.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return state
