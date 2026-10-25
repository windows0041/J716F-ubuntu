#!/usr/bin/python3
"""Read the completed ext4 image and check shipped drivers, identity and permissions."""
import crypt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
WORK = PROJECT / 'build/clean-release'
IMAGE = WORK / 'userdata.raw.img'


def debug(command):
    result = subprocess.run(['debugfs', '-R', command, str(IMAGE)], check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout


def main():
    manifest = json.loads((WORK / 'rootfs-manifest.json').read_text())
    passwd = debug('cat /etc/passwd')
    assert 'maoyu:' not in passwd
    users = [line.split(':') for line in passwd.splitlines()]
    assert [u[0] for u in users if u[2] == '1000'] == ['ubuntu']
    shadow = dict((line.split(':')[0], line.split(':')[1]) for line in debug('cat /etc/shadow').splitlines())
    assert shadow['root'] == '!' and crypt.crypt('ubuntu', shadow['ubuntu']) == shadow['ubuntu']
    assert debug('cat /etc/machine-id') == ''
    assert 'WaylandEnable=false' in debug('cat /etc/gdm3/custom.conf')
    assert 'ListenAddress 172.16.30.1' in debug('cat /etc/ssh/sshd_config')
    for path in ('/home/maoyu', '/root/.ssh', '/etc/ssh/ssh_host_rsa_key',
                 '/etc/ssh/ssh_host_ed25519_key', '/var/lib/j716f-fingerprint/enrolled-owner.json',
                 '/var/lib/j716f-fingerprint/linux-state-active', '/var/lib/j716f-first-boot/complete.json',
                 '/usr/local/bin/j716f-speaker-test', '/opt/j716f-speaker-test',
                 '/usr/local/share/applications/j716f-speaker-test.desktop'):
        assert not debug('stat ' + path).startswith('Inode:'), path
    for target, unit in [('default.target', 'pulseaudio.service'), ('sockets.target', 'pulseaudio.socket')]:
        link = '/etc/systemd/user/' + target + '.wants/' + unit
        assert '/usr/lib/systemd/user/' + unit in debug('stat ' + link), link
    assert '/usr/local/libexec/j716f-configure-speakers.py' in debug('cat /etc/systemd/system/speaker-mixer.service')
    assert 'libfprint-2.so.2.0.0' in debug('stat /opt/j716f-fingerprint/lib/aarch64-linux-gnu/libfprint-2.so.2')
    assert '/opt/j716f-fingerprint/lib/security/pam_fprintd.so' in debug('cat /etc/pam.d/gdm-fingerprint')
    metadata = {}
    for path, uid, mode in [('/', 0, 0o755), ('/usr/bin/sudo', 0, 0o4755),
                            ('/etc/shadow', 0, 0o640), ('/home/ubuntu', 1000, 0o750)]:
        output = debug('stat ' + path)
        owner = re.search(r'User:\s*(\d+)\s+Group:\s*(\d+)', output)
        permissions = re.search(r'Mode:\s*([0-7]+)', output)
        assert owner and int(owner[1]) == uid and permissions and int(permissions[1], 8) == mode, path
        metadata[path] = {'uid': uid, 'gid': int(owner[2]), 'mode': oct(mode)}
    confirmed = {}
    with tempfile.TemporaryDirectory(prefix='j716f-image-audit-') as temporary:
        for index, (path, expected) in enumerate(manifest['critical_files'].items()):
            destination = Path(temporary) / str(index)
            debug('dump /' + path + ' ' + str(destination))
            assert destination.is_file(), 'Missing image dependency: ' + path
            actual = hashlib.sha256(destination.read_bytes()).hexdigest()
            assert actual == expected, 'Image/tree dependency mismatch: ' + path
            confirmed[path] = actual
    report = {'status': 'completed image metadata and critical-file checks passed',
              'only_regular_user': 'ubuntu', 'root_locked': True, 'initial_password_verified': True,
              'machine_id_empty': True, 'no_original_home_or_fingerprint_identity': True,
              'ssh_usb_only': True, 'critical_files_read_back_from_image': confirmed,
              'pulseaudio_enabled_globally': True, 'speaker_test_removed': True,
              'fingerprint_private_libraries_included': True,
              'inode_permissions': metadata, 'actual_tablet_reflash_performed': False}
    (WORK / 'image-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
