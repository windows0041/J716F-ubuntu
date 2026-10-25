#!/usr/bin/python3
"""Enable audio for clean accounts and remove the optional Speaker Test app.

Use --root TREE under fakeroot for packaging. Without --root, only a clean
TB-J716F installation is accepted; modified system files are backed up first.
No sound is played, and no boot partition, GPT or user credential is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'))
    args = parser.parse_args()
    root = args.root.resolve()
    live = root == Path('/')
    assert os.geteuid() == 0, 'Root or fakeroot is required'
    assert (root / 'etc/j716f-release').read_text().startswith('J716F_UBUNTU_CLEAN=')
    if live:
        assert b'lenovo,j716f' in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    assert (root / 'usr/lib/systemd/user/pulseaudio.service').is_file()
    assert (root / 'usr/lib/systemd/user/pulseaudio.socket').is_file()
    backup = root / 'var/lib/j716f-release-fixes' / ('audio-r2-' + str(time.time_ns())) if live else None
    record = {'revision': 2, 'audio_default': 'PulseAudio service and socket enabled globally',
              'speaker_test_removed': True, 'boot_partitions_changed': False,
              'preserved_runtime': '/usr/local/libexec/j716f-configure-speakers.py', 'removed': []}

    def save(path):
        if backup is not None and (path.exists() or path.is_symlink()):
            dest = backup / path.relative_to(root)
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.is_dir() and not path.is_symlink():
                shutil.copytree(path, dest, symlinks=True)
            else:
                shutil.copy2(path, dest, follow_symlinks=False)

    def write(path, data, mode=0o644):
        save(path)
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        temporary = path.with_name('.' + path.name + '.r2-new')
        with temporary.open('wb') as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, 0)
            stream.write(data.encode() if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    old_helper = root / 'opt/j716f-speaker-test/configure-four-speakers.py'
    helper = root / 'usr/local/libexec/j716f-configure-speakers.py'
    data = (old_helper if old_helper.exists() else helper).read_text()
    data = ''.join(line for line in data.splitlines(True) if "assert 'androidboot.serialno=" not in line)
    assert 'lenovo,j716f' in data and 'Digital PCM Volume' in data
    write(helper, data, 0o755)
    record['runtime_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
    service = root / 'etc/systemd/system/speaker-mixer.service'
    body = service.read_text().replace('/opt/j716f-speaker-test/configure-four-speakers.py',
                                       '/usr/local/libexec/j716f-configure-speakers.py')
    assert 'ExecStart=/usr/bin/python3 /usr/local/libexec/j716f-configure-speakers.py' in body
    write(service, body)
    # System defaults must work for a fresh account without copying the source
    # user's ~/.config/systemd/user enablement links into an installation image.
    for target, unit in [('default.target', 'pulseaudio.service'), ('sockets.target', 'pulseaudio.socket')]:
        path = root / 'etc/systemd/user' / (target + '.wants') / unit
        save(path)
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            assert path.is_symlink(), str(path)
            path.unlink()
        path.symlink_to('/usr/lib/systemd/user/' + unit)
        os.lchown(path, 0, 0)
    for name in ('usr/local/bin/j716f-speaker-test',
                 'usr/local/share/applications/j716f-speaker-test.desktop',
                 'usr/share/applications/j716f-speaker-test.desktop',
                 'home/ubuntu/Desktop/j716f-speaker-test.desktop',
                 'home/ubuntu/.local/share/applications/j716f-speaker-test.desktop',
                 'etc/sudoers.d/j716f-speaker-readonly', 'opt/j716f-speaker-test'):
        path = root / name
        if path.exists() or path.is_symlink():
            save(path)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            record['removed'].append('/' + name)
    note = root / 'home/ubuntu/Desktop/首次使用.txt'
    if note.is_file():
        owner = note.stat()
        data = ''.join(line for line in note.read_text().splitlines(True) if 'Speaker Test' not in line)
        write(note, data)
        os.chown(note, owner.st_uid, owner.st_gid)
    version = root / 'etc/j716f-release'
    data = ''.join(line for line in version.read_text().splitlines(True) if not line.startswith('IMAGE_REVISION='))
    write(version, data + 'IMAGE_REVISION=2\n')
    if live:
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['update-desktop-database', '/usr/local/share/applications'], check=True)
        record['backup'] = str(backup)
        backup.mkdir(mode=0o700, parents=True, exist_ok=True)
        (backup / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
