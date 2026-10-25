#!/usr/bin/env python3
"""Prepare a NEW source tree from the pinned upstream archive and saved patch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', required=True, type=Path)
    p.add_argument('--dest', type=Path, default=ROOT / 'build/kernel-6.15.11-source')
    a = p.parse_args()
    info = json.loads((ROOT / 'patches/kernel/snapshot.json').read_text())
    patch = ROOT / info['patch']
    assert sha(a.archive) == info['upstream_archive_sha256'], 'Wrong upstream archive'
    assert sha(patch) == info['patch_sha256'], 'Patch checksum mismatch'
    assert not a.dest.exists(), 'Destination must be new; existing trees are never overwritten'
    a.dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='j716f-prepare-', dir=a.dest.parent) as temporary:
        with tarfile.open(a.archive, 'r:xz') as tar:
            for member in tar.getmembers():
                name = posixpath.normpath(member.name)
                assert name == 'linux-6.15.11' or name.startswith('linux-6.15.11/')
                assert not member.isdev() and not member.isfifo()
                if member.issym() or member.islnk():
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname))
                    assert target == 'linux-6.15.11' or target.startswith('linux-6.15.11/')
            # The complete archive digest is pinned before extraction.
            tar.extractall(temporary)
        tree = Path(temporary) / 'linux-6.15.11'
        subprocess.run(['patch', '--batch', '--forward', '-p1', '-i', str(patch)], cwd=tree, check=True)
        config = ROOT / 'configs/kernel/j716f-6.15.11.config'
        assert sha(config) == info['config_sha256']
        shutil.copyfile(config, tree / '.config')
        os.rename(tree, a.dest)
    print('Prepared source and configuration:', a.dest)
    print('No kernel build or device operation was performed.')


if __name__ == '__main__':
    main()
