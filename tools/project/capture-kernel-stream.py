#!/usr/bin/env python3
"""Bounded, read-only J716F kernel stream capture over the USB diagnostic shell."""
import argparse
import importlib.util
from pathlib import Path
import re
import socket
import time

ROOT = Path(__file__).resolve().parents[2]


def redact(text):
    text = re.sub(r'(?i)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', '[MAC]', text)
    return re.sub(r'(?i)((?:androidboot\.)?serialno=)\S+', r'\1[REDACTED]', text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=3600)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 14400:
        parser.error('Capture duration must be 30..14400 seconds')
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'build/mainline') or output.exists():
        parser.error('Use a new private output file below build/mainline')
    spec = importlib.util.spec_from_file_location('td', ROOT/'tools/project/telnet-diagnostic.py')
    td = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(td)
    deadline, previous_boot, total = time.monotonic()+args.seconds, None, 0
    stopfile = output.with_suffix('.stop')
    with output.open('x') as log:
        while time.monotonic() < deadline and not stopfile.exists():
            shell = None
            try:
                shell = td.DiagnosticShell()
                state = shell.run("tr '\\000' '\\n' < /proc/device-tree/compatible; cat /proc/sys/kernel/random/boot_id; cat /proc/uptime", 10).decode(errors='replace')
                if 'lenovo,j716f' not in state.splitlines():
                    raise RuntimeError('Wrong board')
                boot = re.search(r'(?m)^([0-9a-f-]{36})\s*$', state).group(1)
                uptime = re.search(r'(?m)^(\d+\.\d+) \d+\.\d+\s*$', state).group(1)
                log.write('\nCAPTURE_CONNECTION boot='+boot+' uptime='+uptime+'\n');log.flush()
                print('Kernel stream connected; uptime',uptime,flush=True)
                if previous_boot is not None and boot != previous_boot:
                    data=shell.run('cat /sys/fs/pstore/console-ramoops-0; cat /sys/fs/pstore/dmesg-ramoops-* 2>/dev/null',30).decode(errors='replace')
                    dump=output.with_name(output.stem+'-reboot-'+boot[:8]+'.pstore.log')
                    dump.write_text(redact(data));print('Collected reboot pstore:',dump.name,flush=True)
                previous_boot=boot
                shell.socket.sendall(b'dmesg --color=never --follow\r\n')
                pending=''
                while time.monotonic()<deadline and not stopfile.exists():
                    try:data=shell.socket.recv(65536)
                    except socket.timeout:continue
                    if not data:break
                    decoded=shell.decode(data).decode(errors='replace').replace('\r\n','\n').replace('\r\0','\r')
                    total+=len(data);pending+=decoded
                    while '\n' in pending:
                        line,pending=pending.split('\n',1);line=redact(line)
                        log.write(line+'\n')
                        if re.search(r'watchdog:|hard LOCKUP|Kernel panic|Rebooting in|rcu: INFO|BUG:',line,re.I):
                            print(line,flush=True)
                    log.flush()
                if pending:log.write(redact(pending)+'\n');log.flush()
            except Exception as error:
                print('Kernel stream link:',type(error).__name__,flush=True)
                log.write('LINK_ERROR '+type(error).__name__+'\n');log.flush()
            finally:
                if shell:shell.socket.close()
            if time.monotonic()<deadline and not stopfile.exists():time.sleep(5)
    print('Kernel stream capture ended; bytes received',total,flush=True)


if __name__ == '__main__':
    main()
