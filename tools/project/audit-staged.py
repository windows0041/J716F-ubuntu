#!/usr/bin/env python3
"""Review index contents for local snapshots; print finding labels, never secrets."""
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
    'original_device_serial': re.compile(rb'HA1H[L]J83'),
    'original_filesystem_uuid': re.compile(rb'615495dc-cdbf-4aaf-a4f8-1a1ccc0125f[3]'),
}


def main():
    rows = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).split(b'\0')
    findings, files = [], []
    for row in rows:
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
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
            if pattern.search(data):
                findings.append({'path': name, 'reason': label})
    report = {'files': len(files), 'source_bytes': sum(x['bytes'] for x in files),
              'largest_files': sorted(files, key=lambda x: x['bytes'], reverse=True)[:5],
              'findings': findings, 'remote_configured': bool(subprocess.check_output(['git', 'remote'], cwd=ROOT).strip())}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
