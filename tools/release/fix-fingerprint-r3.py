#!/usr/bin/python3
"""Restore public fingerprint runtime libraries omitted from clean R1/R2 images.

No templates, enrollment metadata, passwords or source-device identity are copied.
The existing fprintd and GDM configuration is retained.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

PROJECT = Path(__file__).resolve().parent.parent.parent
FILES = {
    'libfprint-2.so.2.0.0': ('opt/j716f-fingerprint/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0',
                          '8a0243f2d35d222ef9d9e9b73f79c506fa0979ca9896e72f8a29f997bcff12da', 0o755),
    'pam_fprintd.so': ('opt/j716f-fingerprint/lib/security/pam_fprintd.so',
                      '08aeaf9f16426cd117760006edec6b00e5a97859e63a16266100bf7e98bae45c', 0o644),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/'))
    p.add_argument('--payload', type=Path, default=PROJECT / 'build/clean-release/fingerprint-runtime')
    a = p.parse_args()
    root = a.root.resolve()
    live = root == Path('/')
    assert os.geteuid() == 0
    assert (root / 'etc/j716f-release').read_text().startswith('J716F_UBUNTU_CLEAN=')
    if live:
        assert b'lenovo,j716f' in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    for filename, (destination, expected, mode) in FILES.items():
        source = a.payload / filename
        assert source.is_file() and not source.is_symlink()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        target.parent.chmod(0o755)
        if target.exists():
            assert not target.is_symlink() and hashlib.sha256(target.read_bytes()).hexdigest() == expected
        else:
            with target.open('xb') as stream:
                os.fchmod(stream.fileno(), mode)
                os.fchown(stream.fileno(), 0, 0)
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        os.chown(target, 0, 0)
        target.chmod(mode)
    link = root / 'opt/j716f-fingerprint/lib/aarch64-linux-gnu/libfprint-2.so.2'
    if link.is_symlink():
        assert os.readlink(link) == 'libfprint-2.so.2.0.0'
    else:
        assert not link.exists()
        link.symlink_to('libfprint-2.so.2.0.0')
        os.lchown(link, 0, 0)
    assert 'LD_LIBRARY_PATH=/opt/j716f-fingerprint/lib/aarch64-linux-gnu' in (
        root / 'etc/systemd/system/fprintd.service.d/j716f.conf').read_text()
    assert '/opt/j716f-fingerprint/lib/security/pam_fprintd.so' in (root / 'etc/pam.d/gdm-fingerprint').read_text()
    release = root / 'etc/j716f-release'
    record = {'revision': 3, 'fingerprint_libraries_restored': {name: info[1] for name, info in FILES.items()},
              'fingerprint_templates_copied': False, 'pam_policy_changed': False, 'boot_partitions_changed': False}
    if live:
        backup = root / 'var/lib/j716f-release-fixes' / ('fingerprint-r3-' + str(time.time_ns()))
        backup.mkdir(parents=True, mode=0o700)
        shutil.copy2(release, backup / 'j716f-release.before')
    body = ''.join(line for line in release.read_text().splitlines(True) if not line.startswith('IMAGE_REVISION='))
    release.write_text(body + 'IMAGE_REVISION=3\n')
    os.chown(release, 0, 0)
    release.chmod(0o644)
    if live:
        subprocess.run(['systemctl', 'restart', 'fprintd.service'], check=True)
        (backup / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
