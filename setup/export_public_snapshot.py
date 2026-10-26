#!/usr/bin/env python3
"""Export a reviewed source snapshot, without private Git history or runtime data.

This command does not initialize Git, authenticate, upload, or delete anything.
Run with run_logged.py. An existing output directory is always rejected.
"""
import argparse
import ast
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote


ROOT_EXCLUDED = {'AGENTS.md', 'EXPERIMENT_LOG.md', 'ISSUES.md'}
EXTENSIONS = {'.py', '.ps1', '.cmd', '.sh', '.json', '.yaml', '.yml', '.toml', '.txt', '.ini', '.cfg', '.rules'}
ATTACHMENTS = {'reports/CUP_FAST_ARUCO_PROFILE_20261014.json'}
SECRET_PATTERNS = {
    'private_key': rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
    'github_token': rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}',
    'openai_key': rb'sk-(?:proj-)?[A-Za-z0-9_-]{35,}',
    'aws_access': rb'AKIA[0-9A-Z]{16}',
    'literal_secret': rb'(?im)^\s*(?:[A-Za-z_]*password|passwd|api_key|access_token)\s*=\s*[\x22\x27][^\x22\x27\r\n]{8,}[\x22\x27]',
}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Output already exists; use a fresh directory')
    if output == source or output in source.parents:
        raise ValueError('Output cannot replace the source or a parent')

    def git(*arguments):
        return subprocess.check_output(['git', '-C', str(source)] + list(arguments)).decode('utf-8').strip()

    tracked = git('ls-files', '-z').split('\0')
    # New publication docs are explicit; runtime directories are never traversed.
    candidates = set(tracked)
    candidates.update(p.relative_to(source).as_posix() for p in (source / 'docs').rglob('*.md'))
    candidates.update(p.relative_to(source).as_posix() for p in (source / 'third_party/licenses').glob('*.txt'))
    candidates.update({'README.md', 'README_LEGACY.md', 'THIRD_PARTY_NOTICES.md', 'setup/export_public_snapshot.py'})
    selected = []
    for name in sorted(candidates):
        if not name:
            continue
        path = Path(name)
        parts = path.parts
        keep = (len(parts) == 1 and path.suffix == '.md' and name not in ROOT_EXCLUDED)
        keep |= name == '.gitattributes'
        keep |= len(parts) == 2 and parts[0] in {'setup', 'tools'} and path.suffix in EXTENSIONS
        keep |= len(parts) == 2 and parts[0] == 'camera_calibration' and (path.suffix in {'.py', '.ps1', '.cmd', '.sh', '.md'} or path.name == 'board.json')
        keep |= len(parts) == 2 and parts[0] == 'reports' and path.suffix == '.md'
        keep |= parts[0] == 'docs' and path.suffix == '.md'
        keep |= name.startswith('third_party/licenses/') and path.suffix == '.txt'
        keep |= name in ATTACHMENTS
        if keep and (source / name).is_file():
            selected.append(name)

    replacements = [
        ('USER@UBUNTU_HOST', 'USER@UBUNTU_HOST'),
        ('UBUNTU_HOST', 'UBUNTU_HOST'),
        ('C:\\Users\\YOUR_USER', 'C:\\Users\\YOUR_USER'),
        ('C:\\\\Users\\\\zkang', 'C:\\\\Users\\\\YOUR_USER'),
        ('C:/Users/YOUR_USER', 'C:/Users/YOUR_USER'),
    ]
    output.mkdir(parents=True)
    entries, issues = [], []
    for name in selected:
        origin = source / name
        if origin.is_symlink():
            raise ValueError('Symlinks are not exported: ' + name)
        raw = origin.read_bytes()
        if len(raw) > 2 * 1024 ** 2 or b'\0' in raw[:8192]:
            raise ValueError('Unexpected large/binary source: ' + name)
        text = raw.decode('utf-8-sig')
        redactions = 0
        for old, new in replacements:
            redactions += text.count(old)
            text = text.replace(old, new)
        exported = text.replace('\r\n', '\n').encode('utf-8')
        for rule, pattern in SECRET_PATTERNS.items():
            if re.search(pattern, exported):
                issues.append({'path': name, 'rule': rule})
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(exported)
        entries.append({'path': name, 'source_sha256': digest(raw), 'exported_sha256': digest(exported),
                        'bytes': len(exported), 'private_host_or_profile_replacements': redactions})
    if issues:
        # Never expose the matched values. Failed export is retained for review.
        print(json.dumps({'passed': False, 'issues': issues}))
        raise ValueError('Review potential secrets before publishing')

    # Preserve link labels while explicitly identifying unavailable local evidence.
    omitted_links = []
    link = re.compile(r'(?<!!)\[([^\]\n]+)\]\(([^)\n]+)\)')
    for entry in entries:
        path = output / entry['path']
        if path.suffix != '.md':
            continue
        def fix(match):
            label, href = match.groups()
            target = href.strip('<>').split('#', 1)[0]
            if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('//'):
                return match.group(0)
            candidate = (path.parent / unquote(target)).resolve()
            if candidate.exists():
                return match.group(0)
            omitted_links.append({'document': entry['path'], 'target': target})
            return label + '（原始附件未随公开快照提供）'
        updated = link.sub(fix, path.read_text(encoding='utf-8'))
        path.write_text(updated, encoding='utf-8', newline='\n')
        entry['exported_sha256'] = digest(path.read_bytes())
        entry['bytes'] = path.stat().st_size

    ignore = '\n'.join(['foundationpose_data/', '.windows-camera-venv/', '.camera-venv/', '.assets_download/',
        '.bootstrap_tools/', 'FoundationPose/', 'FoundationPose-conda/', 'reviews/', 'history/',
        'EXPERIMENT_LOG.md', 'ISSUES.md', '.records.lock', '**/__pycache__/', '**/*venv*/', '**/node_modules/',
        '**/.env', '**/.env.*', '*.pem', '*.key', '*.p12', '*.pfx', '*.bag', '*.pth', '*.pt', '*.onnx',
        '*.npy', '*.npz', '*.obj', '*.ply', '*.mp4', '*.avi', '*.zip', '*.tar', '*.gz',
        'reports/*/', 'camera_calibration/sessions/', 'camera_calibration/preflight/', 'camera_calibration/results/', ''])
    (output / '.gitignore').write_text(ignore, encoding='utf-8')
    validation = {'python_files_parsed': 0, 'json_files_parsed': 0}
    for entry in entries:
        path = output / entry['path']
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'), filename=entry['path'])
            validation['python_files_parsed'] += 1
        elif path.suffix == '.json':
            json.loads(path.read_text(encoding='utf-8'))
            validation['json_files_parsed'] += 1
    manifest = {'schema': 'foundationpos_public_snapshot_v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_commit': git('rev-parse', 'HEAD'), 'source_branch': git('branch', '--show-current'),
        'source_tracked_changes': git('diff', '--name-only', 'HEAD').splitlines(),
        'private_history_included': False, 'assets_included': False, 'raw_runtime_records_included': False,
        'transformations': ['UTF-8/LF normalization', 'known private SSH host and Windows profile redaction', 'missing local evidence links explicitly marked'],
        'unpublished_links': omitted_links, 'files': entries,
        'generated_files': {'.gitignore': digest((output / '.gitignore').read_bytes())}, 'validation': validation}
    (output / 'PUBLICATION_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'output': str(output), 'files': len(entries) + 2,
        'source_commit': manifest['source_commit'], 'bytes': sum(v['bytes'] for v in entries),
        'redacted_occurrences': sum(v['private_host_or_profile_replacements'] for v in entries),
        'unpublished_evidence_links_marked': len(omitted_links), **validation}, ensure_ascii=False))


if __name__ == '__main__':
    main()
