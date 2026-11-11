#!/usr/bin/env python3
"""Install verified camera modules on the matching J716F kernel."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    if os.geteuid() or len(sys.argv) != 2:
        raise SystemExit('Usage: sudo python3 install-modules.py /path/to/module-output')
    if b'lenovo,j716f' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
        raise SystemExit('This installer only supports TB-J716F.')
    output = Path(sys.argv[1]).resolve(strict=True)
    manifest = json.loads((output / 'manifest.json').read_text())
    release = os.uname().release
    if release != manifest['kernel_release']:
        raise SystemExit('Running kernel release differs from build.')
    if digest(Path('/boot/Image')) != manifest['kernel_image_sha256']:
        raise SystemExit('Installed kernel Image differs from build.')
    expected = {name + '.ko' for name in ('v4l2-cci', 'gc5035', 's5k4h7', 'ov13b10')}
    if set(manifest['modules']) != expected:
        raise SystemExit('Unexpected module manifest entries.')
    for name, sha in manifest['modules'].items():
        if digest(output / name) != sha:
            raise SystemExit('Module digest mismatch: ' + name)
        vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic', str(output / name)], text=True)
        if vermagic.split()[0] != release:
            raise SystemExit('Module kernel ABI mismatch: ' + name)

    target = Path('/lib/modules') / release / 'updates/j716f-camera'
    backup = Path('/var/backups/j716f-camera') / time.strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True, mode=0o700)
    if target.exists():
        shutil.copytree(target, backup / 'modules')
    autoload = Path('/etc/modules-load.d/j716f-camera.conf')
    if autoload.exists():
        shutil.copy2(autoload, backup / autoload.name)
    target.mkdir(parents=True, exist_ok=True)
    for name in sorted(expected):
        stage = target / (name + '.stage')
        shutil.copyfile(output / name, stage)
        stage.chmod(0o644)
        os.replace(stage, target / name)
    subprocess.run(['depmod', '-a', release], check=True)
    autoload.write_text('v4l2-cci\ngc5035\ns5k4h7\nov13b10\n')
    print('Modules installed. Normal reboot required to activate; backup:', backup)
    print('Use cma=256M in the boot command line for desktop camera buffers.')


if __name__ == '__main__':
    main()
