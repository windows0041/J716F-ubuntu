#!/usr/bin/env python3
"""Verify staged kernel blob bytes/modes against the clean export inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-index-tree', action='store_true')
    args = parser.parse_args()
    manifest_path = ROOT / 'docs/mainline/kernel-source-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    prefix = manifest['path'] + '/'
    if prefix != 'kernel/linux-7.4-rc2/':
        raise RuntimeError('Unexpected kernel path')
    output = subprocess.check_output(['git', 'ls-files', '--stage', '-z', '--', manifest['path']], cwd=ROOT)
    entries = []
    for row in output.split(b'\0'):
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
        mode, oid, stage = metadata.decode().split()
        name = raw_name.decode().removeprefix(prefix)
        if stage != '0' or mode not in ('100644', '100755', '120000'):
            raise RuntimeError('Unexpected index entry: ' + name)
        entries.append((name, mode, oid))
    entries.sort(key=lambda entry: Path(entry[0]))
    if len(entries) != manifest['source_files']:
        raise RuntimeError('Kernel entry count differs from the export')
    inventory, total = hashlib.sha256(), 0
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for index, (name, mode, oid) in enumerate(entries, 1):
            process.stdin.write((oid + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b'blob':
                raise RuntimeError('Invalid Git blob: ' + name)
            size = int(header[2])
            if size >= 100_000_000:
                raise RuntimeError('Git blob exceeds publication limit: ' + name)
            data = process.stdout.read(size)
            if len(data) != size or process.stdout.read(1) != b'\n':
                raise RuntimeError('Truncated Git blob: ' + name)
            inventory.update((mode + ' ' + hashlib.sha256(data).hexdigest() + ' ' + name + '\0').encode())
            total += size
            if index % 20000 == 0:
                print('Verified staged source entries:', index, flush=True)
        process.stdin.close()
        if process.wait(timeout=10):
            raise RuntimeError('Git blob reader failed')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    if total != manifest['source_bytes'] or inventory.hexdigest() != manifest['source_inventory_sha256']:
        raise RuntimeError('Staged bytes or file modes differ from the verified export')
    root_tree = subprocess.check_output(['git', 'write-tree'], cwd=ROOT).decode().strip()
    oid = subprocess.check_output(['git', 'rev-parse', root_tree + ':' + manifest['path']], cwd=ROOT).decode().strip()
    if args.record_index_tree:
        manifest['git_tree_oid'] = oid
        manifest['staged_inventory_matches_verified_export'] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    elif manifest.get('git_tree_oid') != oid:
        raise RuntimeError('Kernel tree object differs from the manifest')
    print(json.dumps({'verified_entries': len(entries), 'source_bytes': total,
                      'inventory_sha256': inventory.hexdigest(), 'git_tree_oid': oid}), flush=True)


if __name__ == '__main__':
    main()
