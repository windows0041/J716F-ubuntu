#!/usr/bin/python3
"""Normalize an exported system tree for a clean J716F installation (under fakeroot)."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    assert root != Path('/') and (root / 'usr/lib/systemd/systemd').exists()
    assert os.geteuid() == 0, 'Use fakeroot so image ownership is preserved'
    os.chown(root, 0, 0)
    root.chmod(0o755)

    def directory(name, mode=0o755, uid=0, gid=0):
        path = root / name
        path.mkdir(mode=mode, parents=True, exist_ok=True)
        path.chmod(mode)
        os.chown(path, uid, gid)
        return path

    def write(name, data, mode=0o644, uid=0, gid=0):
        path = root / name
        directory(str(Path(name).parent), uid=0, gid=0)
        if path.is_symlink():
            path.unlink()
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        path.chmod(mode)
        os.chown(path, uid, gid)
        return path

    def link(name, target):
        path = root / name
        directory(str(Path(name).parent))
        if path.is_symlink() or path.is_file():
            path.unlink()
        path.symlink_to(target)
        os.lchown(path, 0, 0)

    for name in ('dev', 'proc', 'sys', 'run', 'mnt', 'media', 'srv', 'boot', 'home', 'root',
                 'var/log', 'var/cache', 'var/tmp', 'var/spool', 'var/lib/alsa', 'var/lib/dbus',
                 'var/lib/fprint', 'var/lib/bluetooth', 'var/lib/NetworkManager', 'var/lib/AccountsService/users',
                 'var/lib/gdm3', 'var/lib/j716f-speakers', 'var/lib/j716f-input',
                 'etc/NetworkManager/system-connections', 'etc/ssh/sshd_config.d', 'etc/sudoers.d',
                 'etc/skel', 'var/lib/boot-guard', 'var/lib/j716f-fingerprint'):
        directory(name)
    directory('root', 0o700)
    directory('tmp', 0o1777)
    directory('var/tmp', 0o1777)
    directory('var/lib/fprint', 0o700)
    directory('var/lib/j716f-fingerprint', 0o700)
    directory('etc/NetworkManager/system-connections', 0o700)
    for name in ('snap', 'var/lib/snapd', 'var/lib/snapd/snaps', 'var/lib/snapd/seed',
                 'var/cache/snapd', 'var/lib/apt/lists/partial', 'var/cache/apt/archives/partial'):
        directory(name)
    # Old snap mounts refer to deleted per-install state; let snapd initialize
    # a fresh store without copying its account, tokens or refresh history.
    for path in (root / 'etc/systemd/system').rglob('snap-*.mount'):
        if path.is_file() or path.is_symlink():
            path.unlink()
    for line in (root / 'etc/passwd').read_text().splitlines():
        account = line.split(':')
        if account[5].startswith(('/var/lib/', '/var/spool/')):
            directory(account[5].lstrip('/'), 0o750, int(account[2]), int(account[3]))
    write('etc/j716f-release', 'J716F_UBUNTU_CLEAN=2026.10.24-530\nBASE=Ubuntu-22.04-arm64\n')
    write('etc/hostname', 'j716f-ubuntu\n')
    write('etc/timezone', 'Asia/Shanghai\n')
    link('etc/localtime', '/usr/share/zoneinfo/Asia/Shanghai')
    write('etc/hosts', '127.0.0.1 localhost\n127.0.1.1 j716f-ubuntu\n::1 localhost ip6-localhost ip6-loopback\n')
    write('etc/machine-id', '')
    link('var/lib/dbus/machine-id', '/etc/machine-id')
    link('etc/resolv.conf', '/run/systemd/resolve/stub-resolv.conf')
    link('etc/mtab', '/proc/self/mounts')
    link('var/run', '/run')
    link('var/lock', '/run/lock')
    write('etc/fstab', 'LABEL=j716f-ubuntu / ext4 defaults,noatime 0 1\ntmpfs /tmp tmpfs defaults,nosuid 0 0\n')
    write('etc/crypttab', '')
    write('etc/subuid', 'ubuntu:100000:65536\n')
    write('etc/subgid', 'ubuntu:100000:65536\n')
    write('etc/cloud/cloud-init.disabled', '')
    if (root / 'etc/lightdm').exists():
        write('etc/lightdm/lightdm.conf', '[Seat:*]\nuser-session=gnome-xorg\n')
    write('etc/sudoers', 'Defaults env_reset\nDefaults mail_badpass\nDefaults secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"\nroot ALL=(ALL:ALL) ALL\n%sudo ALL=(ALL:ALL) ALL\n#includedir /etc/sudoers.d\n', 0o440)
    write('etc/ssh/sshd_config', 'Port 22\nAddressFamily inet\nListenAddress 172.16.30.1\nPermitRootLogin no\nPasswordAuthentication yes\nKbdInteractiveAuthentication no\nUsePAM yes\nAllowUsers ubuntu\nX11Forwarding no\nSubsystem sftp /usr/lib/openssh/sftp-server\n')
    write('etc/gdm3/custom.conf', '[daemon]\nAutomaticLoginEnable=False\nWaylandEnable=false\n\n[security]\n[xdmcp]\n[chooser]\n[debug]\n')
    for path in (root / 'etc/systemd/system').glob('*getty*.service.d'):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
    for path in (root / 'etc/systemd/system').rglob('*'):
        if path.is_file() and not path.is_symlink() and path.suffix in ('.service', '.conf'):
            body = path.read_text(errors='replace')
            if 'maoyu' in body:
                path.write_text(body.replace('maoyu', 'ubuntu'))
    for binary in ('first-boot.py', 'mark-boot-success.py'):
        write('usr/local/libexec/j716f-' + binary, (PROJECT / 'tools/release' / binary).read_bytes(), 0o755)
    write('usr/local/libexec/j716f-qbootctl', (PROJECT / 'build/brightness-candidate/qbootctl').read_bytes(), 0o755)
    write('usr/local/bin/j716f-touchscreen-calibration.sh',
          (PROJECT / 'configs/j716f-touchscreen-calibration.sh').read_bytes(), 0o755)
    write('etc/xdg/autostart/j716f-touchscreen-calibration.desktop', '[Desktop Entry]\nType=Application\nName=J716F touchscreen calibration\nExec=/usr/local/bin/j716f-touchscreen-calibration.sh\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
    write('etc/systemd/system/j716f-first-boot.service', '[Unit]\nDescription=Initialize clean J716F Ubuntu installation\nWants=systemd-udev-settle.service\nAfter=local-fs.target systemd-udev-settle.service\nBefore=display-manager.service ssh.service j716f-qsee-supplicant.service j716f-goodixfp-loader.service\nConditionPathExists=!/var/lib/j716f-first-boot/complete.json\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /usr/local/libexec/j716f-first-boot.py\nTimeoutStartSec=240\nRemainAfterExit=yes\n\n[Install]\nWantedBy=multi-user.target\n')
    write('etc/systemd/system/j716f-boot-success.service', '[Unit]\nDescription=Mark current J716F slot successful after desktop starts\nAfter=display-manager.service j716f-first-boot.service\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /usr/local/libexec/j716f-mark-boot-success.py\nTimeoutStartSec=40\n\n[Install]\nWantedBy=graphical.target\n')
    for unit, target in [('j716f-first-boot.service', 'multi-user.target'), ('j716f-boot-success.service', 'graphical.target')]:
        link(f'etc/systemd/system/{target}.wants/{unit}', '../' + unit)
    # Canonical host keys are generated by first-boot, not shipped in the image.
    ssh_drop = '[Unit]\nAfter=j716f-first-boot.service\nRequires=j716f-first-boot.service\n'
    write('etc/systemd/system/ssh.service.d/20-j716f-first-boot.conf', ssh_drop)
    for unit in ('gdm3.service', 'j716f-qsee-supplicant.service', 'j716f-goodixfp-loader.service'):
        write(f'etc/systemd/system/{unit}.d/20-clean-first-boot.conf', ssh_drop)
    link('etc/systemd/system/multi-user.target.wants/ssh.service', '/lib/systemd/system/ssh.service')
    link('etc/systemd/system/ssh.socket', '/dev/null')
    for path in (root / 'etc/systemd/system').glob('*.wants/ssh.socket'):
        path.unlink()
    # A model default, not a copy of the existing user's dconf database.
    write('etc/dconf/profile/user', 'user-db:user\nsystem-db:local\n')
    write('etc/dconf/db/local.d/00-j716f', "[org/gnome/mutter]\nexperimental-features=['x11-randr-fractional-scaling']\n[org/gnome/desktop/interface]\ncursor-size=32\ncursor-theme='Adwaita'\n[org/gnome/settings-daemon/plugins/power]\nambient-enabled=true\n")
    subprocess.run(['dconf', 'compile', str(root / 'etc/dconf/db/local'), str(root / 'etc/dconf/db/local.d')], check=True)
    os.chown(root / 'etc/dconf/db/local', 0, 0)
    for filename in ('gnome-control-center.desktop', 'gnome-display-panel.desktop'):
        path = root / 'usr/share/applications' / filename
        if path.exists():
            path.write_text(path.read_text().replace('Exec=gnome-control-center', 'Exec=/opt/j716f-display-scaling/bin/gnome-control-center'))
    path = root / 'usr/share/dbus-1/services/org.gnome.ControlCenter.service'
    path.write_text(path.read_text().replace('Exec=/usr/bin/gnome-control-center', 'Exec=/opt/j716f-display-scaling/bin/gnome-control-center'))
    directory('home/ubuntu', 0o750, 1000, 1000)
    for name in ('Desktop', 'Documents', 'Downloads', 'Pictures', 'Music', 'Videos', '.config', '.local'):
        directory('home/ubuntu/' + name, 0o755, 1000, 1000)
    for name in ('.profile', '.bashrc'):
        source = root / 'usr/share/base-files' / ('dot' + name)
        write('home/ubuntu/' + name, source.read_bytes() if source.exists() else '# Clean Ubuntu account\n', uid=1000, gid=1000)
    monitors = '''<monitors version="2"><configuration><logicalmonitor><x>0</x><y>0</y><scale>1.502347469329834</scale><primary>yes</primary><monitor><monitorspec><connector>DSI-1</connector><vendor>unknown</vendor><product>unknown</product><serial>unknown</serial></monitorspec><mode><width>2560</width><height>1600</height><rate>89.999969482421875</rate></mode></monitor></logicalmonitor></configuration></monitors>\n'''
    write('home/ubuntu/.config/monitors.xml', monitors, uid=1000, gid=1000)
    write('var/lib/AccountsService/users/ubuntu', '[User]\nSession=gnome-xorg\nXSession=gnome-xorg\nSystemAccount=false\n')
    # A desktop note, with no copied personal files or previous profile.
    write('home/ubuntu/Desktop/首次使用.txt', '用户名：ubuntu\n初始密码：ubuntu\n请登录后在终端运行 passwd 更改密码。\n请重新连接 Wi-Fi、配对蓝牙、录入指纹。\n显示缩放支持 100%、150%、200%。\nSSH 仅监听 USB 网络 172.16.30.1。\n', uid=1000, gid=1000)
    subprocess.run(['/usr/bin/python3', str(PROJECT / 'tools/release/fix-audio-r2.py'), '--root', str(root)], check=True)
    subprocess.run(['/usr/bin/python3', str(PROJECT / 'tools/release/fix-fingerprint-r3.py'), '--root', str(root)], check=True)
    for path in (root / 'home/ubuntu').rglob('*'):
        os.chown(path, 1000, 1000, follow_symlinks=False)
    for path in (root / 'home/ubuntu').rglob('*'):
        if path.is_dir():
            path.chmod(0o755)
    directory('home/ubuntu', 0o750, 1000, 1000)
    shadow_gid = next(int(x.split(':')[2]) for x in (root/'etc/group').read_text().splitlines() if x.startswith('shadow:'))
    for filename in ('shadow', 'gshadow'):
        os.chown(root / 'etc' / filename, 0, shadow_gid)
    # Never carry an original user, private identity or enrolled print.
    assert 'maoyu:' not in (root / 'etc/passwd').read_text()
    assert not list((root / 'var/lib/fprint').iterdir())
    assert not list((root / 'var/lib/NetworkManager').iterdir())
    assert not list((root / 'etc/NetworkManager/system-connections').iterdir())
    assert not list((root / 'etc/ssh').glob('ssh_host_*'))
    assert (root / 'opt/j716f-display-scaling/xorg-dirty-modules/drivers/modesetting_drv.so').is_file()
    forbidden = [p for p in root.rglob('*') if p.is_file() and not p.is_symlink()
                 and (re.fullmatch(r'core\.\d+', p.name) or p.name in ('id_rsa', 'id_ed25519', 'linux-state-active', 'enrolled-owner.json'))]
    assert not forbidden, [str(p.relative_to(root)) for p in forbidden]
    print('Clean root prepared: new ubuntu account; personal/auth state excluded; drivers and model defaults retained.')


if __name__ == '__main__':
    main()
