#!/usr/bin/python3
"""Initialize a newly flashed clean root. Never used on the working tablet."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def run(args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=180).stdout


def main():
    assert os.geteuid() == 0
    assert b'lenovo,j716f' in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    assert Path('/etc/j716f-release').read_text().startswith('J716F_UBUNTU_CLEAN=')
    state = Path('/var/lib/j716f-first-boot')
    state.mkdir(mode=0o700, exist_ok=True)
    if (state / 'complete.json').exists():
        return
    root = Path(run(['findmnt', '-nro', 'SOURCE', '/']).strip()).resolve()
    userdata = Path('/dev/disk/by-partlabel/userdata').resolve(strict=True)
    assert root == userdata and root.is_block_device(), 'Unexpected root partition'
    assert run(['blkid', '-s', 'LABEL', '-o', 'value', str(root)]).strip() == 'j716f-ubuntu'
    # Grow the clean image within the existing userdata partition; no GPT edits.
    resize_output = run(['/sbin/resize2fs', str(root)])
    os.umask(0o077)
    misc = Path('/dev/disk/by-partlabel/misc').resolve(strict=True)
    before = misc.read_bytes()
    assert len(before) == 1048576
    command = before[:32].split(b'\0', 1)[0]
    recovery_commands = (b'boot-recovery', b'boot-fastboot', b'boot-rescue', b'bootonce-bootloader')
    if command in recovery_commands:
        (state / 'misc.before.bin').write_bytes(before)
        fd = os.open(misc, os.O_RDWR)
        try:
            assert os.pwrite(fd, b'\0' * 32, 0) == 32
            os.fsync(fd)
        finally:
            os.close(fd)
        after = misc.read_bytes()
        assert after[:32] == b'\0' * 32 and after[32:] == before[32:]
    # ssh-keygen -A creates only missing keys, so an interrupted initialization
    # can safely resume. The release build independently checks none are shipped.
    run(['/usr/bin/ssh-keygen', '-A'])
    # The fingerprint store starts empty; no prior template or account metadata.
    fp = Path('/var/lib/j716f-fingerprint')
    fp.mkdir(mode=0o700, exist_ok=True)
    for path in ('state/data/vendor_de/0/fpdata', 'state/data/vendor/goodix'):
        (fp / path).mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = fp / 'linux-state-active'
    marker.write_text('/var/lib/j716f-fingerprint/state\n')
    marker.chmod(0o600)
    record = {'status': 'clean first boot initialized', 'root': str(root),
              'resize_output': resize_output, 'cleared_boot_command': command.decode('ascii', errors='replace') if command in recovery_commands else None,
              'unrecognized_boot_command_left_unchanged': bool(command and command not in recovery_commands),
              'fingerprint_store': 'created empty', 'new_ssh_host_keys': True,
              'misc_before_sha256': hashlib.sha256(before).hexdigest()}
    (state / 'complete.json').write_text(json.dumps(record, indent=2) + '\n')
    os.sync()


if __name__ == '__main__':
    main()
