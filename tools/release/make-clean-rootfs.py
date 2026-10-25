#!/usr/bin/python3
"""Build and check a fresh ext4 Android-sparse image from the cleaned tree."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from release_config import ROOT, WORK, PACKAGE

TREE = WORK / 'rootfs'
OUTPUT = PACKAGE / 'images/userdata.img'
RAW = WORK / 'userdata.raw.img'
ROUNDTRIP = WORK / 'userdata.roundtrip.img'
SIZE = 8 * 1024 ** 3


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def main():
    assert os.geteuid() == 0, 'Invoke under fakeroot with the saved metadata database'
    assert (TREE / 'etc/j716f-release').exists()
    assert not RAW.exists() and not OUTPUT.exists() and not ROUNDTRIP.exists()
    with RAW.open('xb') as stream:
        stream.truncate(SIZE)
    subprocess.run(['mke2fs', '-q', '-F', '-t', 'ext4', '-b', '4096', '-m', '1',
                    '-L', 'j716f-ubuntu', '-E', 'lazy_itable_init=0,lazy_journal_init=0',
                    '-d', str(TREE), str(RAW)], check=True)
    # Capabilities are preserved explicitly, without needing host root access.
    caps = json.loads((TREE / 'usr/share/j716f-release/capabilities.json').read_text())
    with tempfile.TemporaryDirectory(prefix='j716f-filecaps-') as directory:
        for index, (name, value) in enumerate(caps.items()):
            assert re.fullmatch(r'/[A-Za-z0-9_./+@-]+', name)
            binary = Path(directory) / str(index)
            binary.write_bytes(bytes.fromhex(value))
            subprocess.run(['debugfs', '-w', '-R', f'ea_set -f {binary} {name} security.capability', str(RAW)], check=True)
    subprocess.run(['e2fsck', '-f', '-n', str(RAW)], check=True)
    subprocess.run(['img2simg', str(RAW), str(OUTPUT), '4096'], check=True)
    with OUTPUT.open('rb') as stream:
        header = stream.read(28)
    magic, major, minor, file_h, chunk_h, block, total, chunks, checksum = struct.unpack('<I4H4I', header)
    assert magic == 0xed26ff3a and major == 1 and block * total == SIZE
    subprocess.run(['simg2img', str(OUTPUT), str(ROUNDTRIP)], check=True)
    raw_sha = sha(RAW)
    assert ROUNDTRIP.stat().st_size == SIZE and sha(ROUNDTRIP) == raw_sha
    subprocess.run(['e2fsck', '-f', '-n', str(ROUNDTRIP)], check=True)
    critical = [
        'usr/lib/xorg/modules/drivers/modesetting_drv.so',
        'opt/j716f-display-scaling/xorg-dirty-modules/drivers/modesetting_drv.so',
        'opt/j716f-display-scaling/lib/limited-scales.so',
        'usr/local/libexec/j716f-configure-speakers.py',
        'etc/systemd/system/speaker-mixer.service',
        'opt/j716f-input/reprobe-touchpad.py',
        'opt/j716f-sensors/libexec/hexagonrpcd',
        'usr/local/libexec/j716f-microphone-setup',
        'usr/local/libexec/j716f-first-boot.py',
        'usr/local/libexec/j716f-qbootctl',
        'opt/j716f-fingerprint/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0',
        'opt/j716f-fingerprint/lib/security/pam_fprintd.so',
    ]
    manifest = {'format': 'Android sparse ext4', 'label': 'j716f-ubuntu',
                'expanded_bytes': SIZE, 'sparse_bytes': OUTPUT.stat().st_size,
                'sha256': sha(OUTPUT), 'expanded_sha256': raw_sha,
                'filesystem_check': 'clean; e2fsck -fn on original and roundtrip',
                'sparse_roundtrip_identical': True, 'file_capabilities': caps,
                'critical_files': {name: sha(TREE / name) for name in critical},
                'initial_user': 'ubuntu', 'initial_password': 'ubuntu',
                'new_machine_id_on_boot': True, 'ssh_host_keys_in_image': False,
                'wifi_profiles_in_image': False, 'enrolled_fingerprints_in_image': False,
                'pulseaudio_enabled_for_fresh_accounts': True, 'speaker_test_app_included': False,
                'fingerprint_private_libraries_included': True,
                'actual_clean_install_tested': False}
    (WORK / 'rootfs-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
