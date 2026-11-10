#!/usr/bin/env python3
"""Reconstruct the pinned clean kernel and compare every source with a build tree."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--reference-tree', type=Path, required=True)
    parser.add_argument('--dest', type=Path, default=ROOT / 'kernel/linux-7.4-rc2')
    args = parser.parse_args()
    reference = args.reference_tree.resolve(strict=True)
    dest = args.dest.resolve()
    if dest != ROOT / 'kernel/linux-7.4-rc2' or dest.exists():
        parser.error('Use the new kernel/linux-7.4-rc2 snapshot directory')
    info = json.loads((ROOT / 'docs/mainline/sources.json').read_text())
    subprocess.run([sys.executable, str(ROOT / 'tools/project/prepare-mainline.py'),
                    '--archive', str(args.archive), '--dest', str(dest)], check=True)
    # A tracked .config prevents Kbuild O= builds; retain the exact bytes under
    # an ordinary source filename, with the canonical copy in configs/kernel.
    (dest / '.config').rename(dest / 'j716f.config')
    paths = sorted(path for path in dest.rglob('*') if path.is_symlink() or path.is_file())

    def check(path):
        name = path.relative_to(dest).as_posix()
        other = reference / ('.config' if name == 'j716f.config' else name)
        if path.is_symlink():
            if not other.is_symlink() or os.readlink(path) != os.readlink(other):
                raise RuntimeError('Reference symlink mismatch: ' + name)
            data = os.fsencode(os.readlink(path))
            return name, '120000', hashlib.sha256(data).hexdigest(), len(data)
        if not other.is_file() or other.is_symlink() or digest(path) != digest(other):
            raise RuntimeError('Reference source mismatch: ' + name)
        mode = '100755' if path.stat().st_mode & stat.S_IXUSR else '100644'
        size = path.stat().st_size
        if size >= 100_000_000:
            raise RuntimeError('Source file exceeds the publication limit: ' + name)
        return name, mode, digest(path), size

    records = []
    with ThreadPoolExecutor(max_workers=8) as workers:
        for index, record in enumerate(workers.map(check, paths), 1):
            records.append(record)
            if index % 20000 == 0:
                print('Verified source entries:', index, flush=True)
    inventory = hashlib.sha256()
    for name, mode, sha, _ in records:
        inventory.update((mode + ' ' + sha + ' ' + name + '\0').encode('utf-8'))
    config_sha = digest(dest / 'j716f.config')
    if config_sha != info['config_sha256']:
        raise RuntimeError('Snapshot configuration differs from the source pins')
    manifest = {
        'path': 'kernel/linux-7.4-rc2',
        'upstream_commit': info['kernel']['commit'],
        'archive_sha256': next(item['sha256'] for item in info['files']
                               if item['filename'] == 'linux-7.4-rc2.tar.gz'),
        'patch_sha256': info['patch_sha256'],
        'config_path': 'kernel/linux-7.4-rc2/j716f.config',
        'config_sha256': config_sha,
        'source_files': len(records),
        'source_bytes': sum(item[3] for item in records),
        'source_inventory_sha256': inventory.hexdigest(),
        'every_exported_entry_matches_debugged_tree': True,
        'configuration_reference_name': '.config',
        'generated_build_outputs_included': False,
        'upstream_test_and_documentation_assets_preserved': True,
        'largest_files': [{'path': name, 'bytes': size} for name, _, _, size
                          in sorted(records, key=lambda item: item[3], reverse=True)[:5]],
    }
    output = ROOT / 'docs/mainline/kernel-source-manifest.json'
    with output.open('x') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == '__main__':
    main()
