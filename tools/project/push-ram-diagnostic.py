#!/usr/bin/env python3
"""Copy one file to the USB diagnostic's /run, verify SHA-256, then rename it.

Does not flash partitions or start the desktop. Requires the existing USB-only
Telnet diagnostic; data is sent through a temporary BusyBox TCP listener.
"""
import argparse
import hashlib
import importlib.util
import ipaddress
import re
import uuid
from pathlib import Path, PurePosixPath
import shlex
import socket
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--host', default='172.16.30.1')
    parser.add_argument('--remote', default='/run/j716f-ram-desktop/rootfs.squashfs')
    parser.add_argument('--port', type=int, default=23457)
    parser.add_argument('--installed-root-uuid', help='Allow the known installed ext4 root; /run must still be tmpfs')
    args = parser.parse_args()
    host = str(ipaddress.IPv4Address(args.host))
    root_uuid = str(uuid.UUID(args.installed_root_uuid)) if args.installed_root_uuid else None
    remote = PurePosixPath(args.remote)
    if ('..' in remote.parts or len(remote.parts) < 4 or remote.parts[1] != 'run'
            or not remote.parts[2].startswith('j716f-') or not 1024 <= args.port <= 65535):
        parser.error('Use /run/j716f-*/filename and an unprivileged TCP port')
    file = args.file.resolve(strict=True)
    if not file.is_file():
        parser.error('Regular source file required')
    with file.open('rb') as stream:
        expected = hashlib.file_digest(stream, 'sha256').hexdigest()
    spec = importlib.util.spec_from_file_location('telnet_diag', Path(__file__).with_name('telnet-diagnostic.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shell = module.DiagnosticShell(host)
    quote = shlex.quote
    try:
        probe = shell.run('bb=/bin/busybox; [ -x "$bb" ] || bb=/usr/bin/busybox-static; [ -x "$bb" ] && echo BUSYBOX_READY', timeout=10)
        if b'BUSYBOX_READY' not in probe:
            parser.error('Remote BusyBox missing')
        check = shell.run("$bb tr '\\000' '\\n' < /sys/firmware/devicetree/base/compatible; cat /proc/mounts; $bb df -Pk /run", timeout=10)
        text = check.decode(errors='replace')
        if 'lenovo,j716f' not in text.splitlines():
            parser.error('Wrong diagnostic board')
        mounts = [line.split() for line in text.splitlines() if len(line.split()) == 6]
        if not any(row[1:3] == ['/run', 'tmpfs'] for row in mounts):
            parser.error('Remote /run must be tmpfs')
        internal = [row for row in mounts if row[0].startswith('/dev/') and not row[0].startswith(('/dev/loop', '/dev/ram'))]
        if internal:
            if not root_uuid or len(internal) != 1 or internal[0][1:3] != ['/', 'ext4']:
                parser.error('Only the explicitly identified installed ext4 root may be mounted')
            identity = shell.run('/usr/sbin/blkid ' + quote(internal[0][0]) + '; $bb cat /etc/j716f-disk-desktop', timeout=10).decode(errors='replace')
            if not re.search(r'(?<![A-Z])UUID="' + re.escape(root_uuid) + r'"', identity) or '26.10-j716f-disk-diag-v1' not in identity.splitlines():
                parser.error('Installed root identity mismatch')
        rows = [line.split() for line in text.splitlines() if line.split() and line.split()[-1] == '/run']
        if not rows or int(rows[-1][3]) * 1024 < file.stat().st_size + 128 * 1024 * 1024:
            parser.error('Insufficient free space in remote RAM filesystem')
        part = str(remote) + '.part'
        if internal:
            # Ubuntu's BusyBox nc lacks -s; use a one-shot Python listener bound
            # only to the already validated USB IPv4 address.
            receiver_code = ('import socket,sys,shutil; s=socket.socket(); '
                             's.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); '
                             's.settimeout(60); s.bind((sys.argv[1],int(sys.argv[2]))); '
                             's.listen(1); c=s.accept()[0]; c.settimeout(60); '
                             'f=open(sys.argv[3],"wb"); '
                             'shutil.copyfileobj(c.makefile("rb"),f,1048576); '
                             'f.close(); c.close(); s.close()')
            receiver = 'python3 -c ' + quote(receiver_code) + ' ' + quote(host) + ' ' + str(args.port) + ' ' + quote(part)
            redirect = ' < /dev/null > ' + quote(part + '.log') + ' 2>&1'
        else:
            receiver = '$bb nc -l -s ' + host + ' -p ' + str(args.port)
            redirect = ' < /dev/null > ' + quote(part) + ' 2> ' + quote(part + '.log')
        result = shell.run('if [ -e ' + quote(str(remote)) + ' ] || [ -L ' + quote(str(remote)) +
                           ' ]; then echo TARGET_EXISTS; else $bb mkdir -p ' + quote(str(remote.parent)) +
                           '; ' + receiver + redirect + ' &\necho $! > ' + quote(part + '.pid') + '\nfi', timeout=10)
        if b'TARGET_EXISTS' in result:
            parser.error('Remote destination already exists')
        time.sleep(.5)
        total, reported = 0, 0
        start = time.monotonic()
        with socket.create_connection((host, args.port), timeout=20) as connection, file.open('rb') as stream:
            while data := stream.read(1024 * 1024):
                connection.sendall(data)
                total += len(data)
                if total - reported >= 64 * 1024 * 1024:
                    print(f'Sent {total // (1024 * 1024)} MiB', flush=True)
                    reported = total
            connection.shutdown(socket.SHUT_WR)
        result = shell.run('wait $(cat ' + quote(part + '.pid') + ') && $bb sha256sum ' + quote(part), timeout=90)
        if expected.encode() not in result:
            raise RuntimeError('Remote SHA-256 mismatch; RAM partial file retained')
        result = shell.run('$bb mv ' + quote(part) + ' ' + quote(str(remote)) + ' && echo RAM_COPY_RENAMED', timeout=10)
        if b'RAM_COPY_RENAMED' not in result:
            raise RuntimeError('Remote rename not confirmed')
        print(f'Verified {total} bytes in {time.monotonic() - start:.1f}s at {remote}; SHA-256 {expected}')
    finally:
        shell.socket.close()


if __name__ == '__main__':
    main()
