#!/usr/bin/env python3
"""Run a command in the local ARM64 rootfs using a private mount namespace.

Invoke as root with: unshare --mount --fork --propagation private python3 ...
"""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path,
                        default=ROOT / 'build/mainline/ubuntu-26.10-rootfs')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    assert os.geteuid() == 0
    assert root.is_relative_to((ROOT / 'build').resolve())
    assert 'VERSION_ID="26.10"' in (root / 'etc/os-release').read_text()
    assert Path('/proc/self/ns/mnt').readlink() != Path('/proc/1/ns/mnt').readlink(), 'Use unshare'
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    assert command, 'Command required'
    subprocess.run(['mount', '--make-rprivate', '/'], check=True)
    for name in ['dev', 'proc', 'run']:
        (root / name).mkdir(exist_ok=True)
    subprocess.run(['mount', '-t', 'tmpfs', '-o', 'mode=755,nosuid', 'tmpfs', str(root / 'dev')], check=True)
    for name, major, minor in [('null', 1, 3), ('zero', 1, 5), ('random', 1, 8),
                               ('urandom', 1, 9), ('tty', 5, 0)]:
        os.mknod(root / 'dev' / name, stat.S_IFCHR | 0o666, os.makedev(major, minor))
    (root / 'dev/pts').mkdir()
    subprocess.run(['mount', '-t', 'devpts', '-o', 'newinstance,ptmxmode=666',
                    'devpts', str(root / 'dev/pts')], check=True)
    (root / 'dev/ptmx').symlink_to('pts/ptmx')
    for name, target in [('fd', '/proc/self/fd'), ('stdin', '/proc/self/fd/0'),
                         ('stdout', '/proc/self/fd/1'), ('stderr', '/proc/self/fd/2')]:
        (root / 'dev' / name).symlink_to(target)
    subprocess.run(['mount', '-t', 'proc', 'proc', str(root / 'proc')], check=True)
    subprocess.run(['mount', '-t', 'tmpfs', '-o', 'mode=755,nosuid,nodev',
                    'tmpfs', str(root / 'run')], check=True)
    environment = os.environ.copy()
    environment.update(DEBIAN_FRONTEND='noninteractive', LC_ALL='C.UTF-8', LANG='C.UTF-8')
    result = subprocess.run(['chroot', str(root)] + command, env=environment)
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
