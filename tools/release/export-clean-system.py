#!/usr/bin/python3
"""Read-only system export. Personal/authentication state is excluded before streaming."""
import crypt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOTS = [
    'usr', 'etc', 'bin', 'sbin', 'lib',
    'opt/google', 'opt/v4l', 'opt/j716f-input',
    'opt/j716f-display-scaling/bin', 'opt/j716f-display-scaling/lib',
    'opt/j716f-display-scaling/xorg-dirty-modules',
    'opt/j716f-fingerprint/sbin/qsee-supplicant',
    'opt/j716f-fingerprint/sbin/qsee-app-loader',
    'opt/j716f-fingerprint/lib/aarch64-linux-gnu',
    'opt/j716f-fingerprint/lib/security',
    'opt/j716f-sensors/bin', 'opt/j716f-sensors/lib', 'opt/j716f-sensors/libexec',
    'opt/j716f-stability/kernel-evidence.py',
    'var/lib/dpkg', 'var/lib/apt/extended_states',
    'var/lib/sgml-base', 'var/lib/xml-core', 'var/lib/dictionaries-common',
    'var/lib/aspell', 'var/lib/ispell', 'var/lib/ghostscript',
    'var/lib/j716f-sensors/root',
]
BLOCKED = [
    'etc/NetworkManager/system-connections', 'etc/wpa_supplicant', 'etc/iwd',
    'etc/netplan', 'etc/ssl/private', 'etc/letsencrypt', 'etc/openvpn',
    'etc/ipsec.secrets', 'etc/ppp/chap-secrets', 'etc/ppp/pap-secrets',
    'etc/apt/auth.conf', 'etc/apt/auth.conf.d', 'etc/krb5.keytab',
    'etc/sudoers', 'etc/sudoers.d', 'etc/ssh/sshd_config', 'etc/ssh/sshd_config.d',
    'etc/ssh/authorized_keys', 'etc/shadow', 'etc/shadow-', 'etc/gshadow', 'etc/gshadow-',
    'etc/passwd', 'etc/passwd-', 'etc/group', 'etc/group-',
    'etc/machine-id', 'etc/hostname', 'etc/hosts', 'etc/resolv.conf',
    'etc/fstab', 'etc/crypttab', 'etc/wifi-auto.conf', 'etc/skel',
    'etc/gdm3/custom.conf', 'etc/default/grub',
    'etc/systemd/system/j716f-als-stability-capture.service',
    'etc/systemd/system/multi-user.target.wants/j716f-als-stability-capture.service',
    'usr/local/sbin/j716f-fingerprint',
    'usr/local/bin/j716f-speaker-test',
    'usr/local/share/applications/j716f-speaker-test.desktop',
    'usr/share/applications/j716f-speaker-test.desktop',
]
caps = {}
counts = {'files': 0, 'bytes': 0, 'excluded': 0}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def allowed(info):
    name = info.name.rstrip('/')
    if (any(name == p or name.startswith(p + '/') for p in BLOCKED)
            or name.startswith('etc/ssh/ssh_host_')
            or name.endswith(('.dpkg-old', '.dpkg-dist', '.bak', '.save', '~'))
            or '/__pycache__/' in name or name.endswith('.pyc')
            or (name.startswith('etc/') and any(p in name.lower() for p in
                ('private_key', 'id_rsa', 'id_ed25519', 'wifi-auto')))):
        counts['excluded'] += 1
        return None
    # Only package/system roots above can reach this filter. No /home, /root,
    # logs, fingerprint library, pairing keys, browser profiles or raw blocks.
    if info.ischr() or info.isblk() or info.isfifo():
        return None
    info.uname = info.gname = ''
    if info.isfile():
        counts['files'] += 1
        counts['bytes'] += info.size
        try:
            cap = os.getxattr('/' + name, 'security.capability', follow_symlinks=False)
            caps['/' + name] = cap.hex()
        except OSError:
            pass
    return info


def add_bytes(archive, name, data, mode=0o644):
    if isinstance(data, str):
        data = data.encode()
    info = tarfile.TarInfo(name)
    info.mode, info.uid, info.gid, info.size = mode, 0, 0, len(data)
    archive.addfile(info, io.BytesIO(data))


def main():
    assert os.geteuid() == 0
    assert b'lenovo,j716f' in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    assert '#530 ' in subprocess.check_output(['uname', '-v'], text=True)
    os.sched_setaffinity(0, os.sched_getaffinity(0) - {5})
    status_before = sha('/var/lib/dpkg/status')
    users = [line.split(':') for line in Path('/etc/passwd').read_text().splitlines()]
    users = [u for u in users if int(u[2]) < 1000 or int(u[2]) == 65534]
    users.append(['ubuntu', 'x', '1000', '1000', 'Ubuntu', '/home/ubuntu', '/bin/bash'])
    names = {u[0] for u in users}
    groups = []
    for line in Path('/etc/group').read_text().splitlines():
        fields = line.split(':')
        if int(fields[2]) >= 1000 and int(fields[2]) != 65534:
            continue
        members = [m for m in fields[3].split(',') if m in names and m != 'ubuntu']
        if fields[0] in ('sudo', 'adm', 'audio', 'video', 'input', 'render', 'plugdev', 'netdev', 'bluetooth'):
            members.append('ubuntu')
        fields[3] = ','.join(members)
        groups.append(fields)
    groups.append(['ubuntu', 'x', '1000', ''])
    # Fresh public installer credential, unrelated to the live device's password.
    password_hash = crypt.crypt('ubuntu', crypt.mksalt(crypt.METHOD_SHA512))
    shadow = '\n'.join(':'.join([u[0], password_hash if u[0] == 'ubuntu' else '!',
                                '20000', '0', '99999', '7', '', '', '']) for u in users) + '\n'
    with gzip.GzipFile(fileobj=sys.stdout.buffer, mode='wb', compresslevel=1, mtime=0) as compressed, \
            tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT,
                         dereference=False) as archive:
        for root in ROOTS:
            path = Path('/') / root
            if path.exists() or path.is_symlink():
                archive.add(str(path), arcname=root, filter=allowed)
        assert sha('/var/lib/dpkg/status') == status_before, 'Package database changed during export'
        add_bytes(archive, 'etc/passwd', '\n'.join(':'.join(u) for u in users) + '\n')
        add_bytes(archive, 'etc/group', '\n'.join(':'.join(g) for g in groups) + '\n')
        add_bytes(archive, 'etc/shadow', shadow, 0o640)
        add_bytes(archive, 'etc/gshadow', '\n'.join(f'{g[0]}:!::{g[3]}' for g in groups) + '\n', 0o640)
        add_bytes(archive, 'usr/share/j716f-release/capabilities.json', json.dumps(caps, indent=2) + '\n')
        add_bytes(archive, 'usr/share/j716f-release/export.json', json.dumps({
            'kernel': '6.15.11 #530', 'method': 'allowlisted system-only file export',
            'dpkg_status_sha256': status_before, 'counts': counts,
            'personal_state_exported': False, 'source_roots': ROOTS,
        }, indent=2) + '\n')
    print(json.dumps(counts), file=sys.stderr)


if __name__ == '__main__':
    main()
