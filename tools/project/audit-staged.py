#!/usr/bin/env python3
"""Review staged additions/changes; print finding labels and paths, never secrets."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_TOP = {'backup', 'build', 'kernel', 'artifacts', 'artifacts-v615', 'firmware',
                 'releases', 'release-v1', 'out', 'logs'}
PATTERNS = {
    'legacy_device_password': re.compile(rb'L[i]velinux', re.I),
    'private_key': re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----'),
    'github_token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'aws_access_key': re.compile(rb'A[K]IA[0-9A-Z]{16}'),
    'password_on_ssh_command': re.compile(rb'sshpass\s+-p\s+[^\s]+'),
    'device_serial_in_log': re.compile(rb'androidboot\.serialno=\S+'),
    'potential_device_uuid': re.compile(rb'\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b', re.I),
    'personal_windows_path': re.compile(rb'[A-Z]:[/\\]+Users[/\\]+[^/\\\s]+', re.I),
    'ssh_public_key': re.compile(rb'(?m)^ssh-(?:rsa|ed25519)\s+[A-Za-z0-9+/]{40,}'),
    'password_hash': re.compile(rb'\$(?:[156]|y)\$[A-Za-z0-9./]{8,}\$[A-Za-z0-9./]{16,}'),
}
PUBLIC_BUG_REFERENCE = re.compile(
    rb'Closes: https://sashiko\.dev/#/bug/linux-[0-9a-f-]{36}\r?', re.I)


def main():
    changed = set(subprocess.check_output(
        ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'],
        cwd=ROOT).split(b'\0'))
    rows = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).split(b'\0')
    findings, files = [], []
    for row in rows:
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
        if raw_name not in changed:
            continue
        mode, object_id, stage = metadata.decode().split()
        name = raw_name.decode()
        parts = Path(name).parts
        if mode == '160000' or stage != '0':
            findings.append({'path': name, 'reason': 'unexpected submodule or unmerged index entry'})
            continue
        if parts[0] in FORBIDDEN_TOP or parts[0].startswith('backup') or 'local-history' in parts:
            findings.append({'path': name, 'reason': 'private or generated directory'})
        data = subprocess.check_output(['git', 'cat-file', 'blob', object_id], cwd=ROOT)
        files.append({'path': name, 'bytes': len(data)})
        if len(data) > 10 * 1024 * 1024 or b'\0' in data:
            findings.append({'path': name, 'reason': 'large or binary payload'})
        for label, pattern in PATTERNS.items():
            matches = list(pattern.finditer(data))
            if label == 'potential_device_uuid':
                # The saved upstream RPMh mail links a public bug, not a disk.
                matches = [match for match in matches if not PUBLIC_BUG_REFERENCE.fullmatch(
                    data[data.rfind(b'\n', 0, match.start()) + 1:
                         data.find(b'\n', match.end()) if b'\n' in data[match.end():] else len(data)])]
            if matches:
                findings.append({'path': name, 'reason': label})
    report = {'scope': 'staged additions and modifications; existing history is not rewritten',
              'files': len(files), 'source_bytes': sum(x['bytes'] for x in files),
              'largest_files': sorted(files, key=lambda x: x['bytes'], reverse=True)[:5],
              'findings': findings, 'remote_configured': bool(subprocess.check_output(['git', 'remote'], cwd=ROOT).strip())}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
