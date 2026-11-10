#!/usr/bin/env python3
"""Prepare the pinned experimental mainline source, patch and config in a new tree.

Requires Python 3.12 or later and patch. No build or device operation is run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--dest', type=Path,
                        default=ROOT / 'build/mainline/linux-7.4-rc2')
    args = parser.parse_args()
    info = json.loads((ROOT / 'docs/mainline/sources.json').read_text())
    archive = next(e for e in info['files'] if e['filename'] == 'linux-7.4-rc2.tar.gz')
    patch, config = ROOT / info['patch'], ROOT / info['config']
    if sha(args.archive) != archive['sha256']:
        parser.error('Archive does not match the pinned upstream source')
    if sha(patch) != info['patch_sha256'] or sha(config) != info['config_sha256']:
        parser.error('Saved patch or configuration checksum mismatch')
    if args.dest.exists() or args.dest.is_symlink():
        parser.error('Destination must be new; existing trees are not overwritten')
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='j716f-mainline-', dir=args.dest.parent) as temporary:
        work = Path(temporary)
        with tarfile.open(args.archive, 'r:gz') as source:
            source.extractall(work, filter='data')
        children = list(work.iterdir())
        if len(children) != 1 or not children[0].is_dir():
            parser.error('Expected one upstream source directory')
        tree = children[0]
        makefile = (tree / 'Makefile').read_text()
        if not all(line in makefile.splitlines() for line in
                   ('VERSION = 7', 'PATCHLEVEL = 4', 'SUBLEVEL = 0', 'EXTRAVERSION = -rc2')):
            parser.error('Unexpected kernel version')
        subprocess.run(['patch', '--batch', '--forward', '-p1', '-i', str(patch)],
                       cwd=tree, check=True)
        shutil.copyfile(config, tree / '.config')
        os.rename(tree, args.dest)
    print('Prepared experimental source:', args.dest)
    print('No kernel build, flash, slot change or reboot was performed.')


if __name__ == '__main__':
    main()
