"""Initialize/audit a source-only repository and preserve platform journals.

No push, checkout, reset of worktree, cleanup, or recursive deletion is performed.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--action', choices=['inspect', 'init', 'audit', 'commit', 'import-baseline', 'bundle'], required=True)
    parser.add_argument('--message')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--identity-name')
    parser.add_argument('--identity-email')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)

    def git(*argv, check=True):
        result = subprocess.run(['git', '-C', str(root)] + list(argv), capture_output=True, check=False)
        if check and result.returncode:
            raise RuntimeError('git ' + argv[0] + ': ' + result.stderr.decode('utf-8', errors='replace'))
        return result

    def snapshot_journals():
        folder = root / 'history' / ('windows' if os.name == 'nt' else 'ubuntu') / 'baseline_20261015'
        folder.mkdir(parents=True, exist_ok=True)
        entries = []
        for name in ['EXPERIMENT_LOG.md', 'ISSUES.md']:
            source, target = root / name, folder / name
            if source.exists() and not target.exists():
                shutil.copy2(source, target)
            if target.exists():
                data = target.read_bytes()
                entries.append(dict(path=target.relative_to(root).as_posix(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        (folder / 'manifest.json').write_text(json.dumps(dict(files=entries), indent=2) + '\n')

    if args.action == 'inspect':
        result = dict(root=str(root), git_directory=(root / '.git').exists(), top_level={}, text_files={})
        for path in root.iterdir():
            result['top_level'][path.name] = 'directory' if path.is_dir() else path.stat().st_size
        for name in ['setup', 'tools', 'reports']:
            paths = [p for p in (root / name).rglob('*') if p.is_file()]
            result['text_files'][name] = dict(files=len(paths), bytes=sum(p.stat().st_size for p in paths),
                                             extensions=sorted(set(p.suffix for p in paths)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.action == 'init':
        if (root / '.git').exists():
            raise RuntimeError('Existing root Git repository must be inspected; refusing reinitialization')
        git('init')
        git('symbolic-ref', 'HEAD', 'refs/heads/main')
        git('config', '--local', 'core.autocrlf', 'false')
        git('config', '--local', 'core.quotepath', 'false')
        # Keep author identity local; use caller values only when explicitly passed.
        if args.identity_name:
            git('config', '--local', 'user.name', args.identity_name)
        if args.identity_email:
            git('config', '--local', 'user.email', args.identity_email)
        snapshot_journals()
        print(json.dumps(dict(passed=True, action='initialized', worktree_files_overwritten=False)))
        return
    if args.action == 'import-baseline':
        if git('rev-parse', '--verify', 'HEAD', check=False).returncode == 0:
            raise RuntimeError('Refusing to replace an existing commit history')
        if not args.bundle:
            raise ValueError('--bundle required')
        git('bundle', 'verify', str(args.bundle))
        git('fetch', str(args.bundle), 'main:refs/remotes/windows/main')
        commit = git('rev-parse', 'refs/remotes/windows/main').stdout.decode().strip()
        # Populate only index and refs. Existing Ubuntu source/docs/logs are untouched.
        git('read-tree', commit)
        git('update-ref', 'refs/heads/ubuntu', commit)
        git('symbolic-ref', 'HEAD', 'refs/heads/ubuntu')
        restored = []
        for raw in git('ls-tree', '-r', '--name-only', '-z', commit).stdout.decode('utf-8').split('\0'):
            if not raw:
                continue
            target = root / raw
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(git('show', commit + ':' + raw).stdout)
                restored.append(raw)
        snapshot_journals()
        print(json.dumps(dict(passed=True, imported_commit=commit, branch='ubuntu', worktree_files_overwritten=False,
                              missing_baseline_files_restored=len(restored))))
        return
    if args.action in ['audit', 'commit']:
        files = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').stdout.decode('utf-8').split('\0')
        files = sorted(set(name for name in files if name))
        issues = []
        total = 0
        patterns = [
            ('private_key', re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')),
            ('github_token', re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}')),
            ('openai_key', re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{35,}')),
            ('aws_access', re.compile(rb'AKIA[0-9A-Z]{16}')),
            ('literal_password', re.compile(rb'(?im)^\s*(?:[A-Za-z_]*password|passwd|api_key|access_token)\s*=\s*[\x22\x27][^\x22\x27\r\n]{8,}[\x22\x27]')),
        ]
        for name in files:
            path = root / name
            if not path.exists():
                continue  # Staged deletion is handled by git add -A later.
            if path.is_symlink() or root not in path.resolve().parents:
                issues.append(dict(path=name, rule='symlink_or_escape'))
                continue
            data = path.read_bytes()
            total += len(data)
            if len(data) > 5 * 1024 ** 2 or b'\0' in data[:8192]:
                issues.append(dict(path=name, rule='large_or_binary'))
            for rule, pattern in patterns:
                for match in pattern.finditer(data):
                    # Never print matched values to logs.
                    issues.append(dict(path=name, line=data[:match.start()].count(b'\n') + 1, rule=rule))
        report = dict(passed=not issues, files=len(files), bytes=total, issues=issues,
                      data_models_venvs_caches_are_excluded=True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if issues:
            raise RuntimeError('Review audit findings before staging; values omitted from log')
        if args.action == 'commit':
            if not args.message:
                raise ValueError('--message required')
            git('add', '-A', '--', '.')
            result = git('commit', '-m', args.message)
            print(result.stdout.decode('utf-8', errors='replace')[:1500])
            print('COMMIT', git('rev-parse', 'HEAD').stdout.decode().strip())
        return
    if args.action == 'bundle':
        if args.bundle is None or args.bundle.exists():
            raise ValueError('A new --bundle path is required')
        args.bundle.parent.mkdir(parents=True, exist_ok=True)
        git('bundle', 'create', str(args.bundle), '--all')
        git('bundle', 'verify', str(args.bundle))
        print(json.dumps(dict(passed=True, path=str(args.bundle), bytes=args.bundle.stat().st_size,
                              sha256=hashlib.sha256(args.bundle.read_bytes()).hexdigest())))


if __name__ == '__main__':
    main()
