#!/usr/bin/env python3
"""Execute an explicit command on the USB-only diagnostic shell and save output."""
import argparse
from pathlib import Path
import secrets
import socket
import time


class DiagnosticShell:
    def __init__(self, host='172.16.30.1'):
        self.last_output = b''
        self.socket = socket.create_connection((host, 23), timeout=5)
        self.socket.settimeout(.4)
        self.state, self.option_command, self.suboption = 0, 0, False
        self.read(1)
        self.socket.sendall(b'stty -echo 2>/dev/null || /bin/busybox stty -echo 2>/dev/null\r\n')
        self.read(.5)

    def decode(self, data):
        output = bytearray()
        for value in data:
            if self.suboption:
                if self.state == 1 and value == 240:
                    self.suboption, self.state = False, 0
                else:
                    self.state = 1 if value == 255 else 0
                continue
            if self.state == 0:
                if value == 255:
                    self.state = 1
                else:
                    output.append(value)
            elif self.state == 1:
                if value == 255:
                    output.append(value)
                    self.state = 0
                elif value in (251, 252, 253, 254):
                    self.option_command, self.state = value, 2
                elif value == 250:
                    self.suboption, self.state = True, 0
                else:
                    self.state = 0
            else:
                if self.option_command == 253:
                    self.socket.sendall(bytes([255, 252, value]))
                elif self.option_command == 251:
                    self.socket.sendall(bytes([255, 254, value]))
                self.state = 0
        return output

    def read(self, seconds, marker=None):
        result = bytearray()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                data = self.socket.recv(65536)
            except socket.timeout:
                continue
            if not data:
                break
            result += self.decode(data)
            if marker and marker in result:
                break
            if len(result) > 16 * 1024 * 1024:
                raise RuntimeError('Diagnostic response exceeded 16 MiB')
        return bytes(result)

    def run(self, command, timeout=30):
        token = secrets.token_hex(8)
        marker = ('__J716F_' + token + '__').encode()
        line = "{\nprintf '\\n'\n" + command + "\nprintf '\\n__J716F_%s__\\n' " + token + "\n}"
        self.socket.sendall(line.encode() + b'\r\n')
        data = self.read(timeout, marker)
        self.last_output = data.replace(b'\r\n', b'\n').replace(b'\r\0', b'\r')
        if marker not in data:
            raise RuntimeError('Diagnostic command did not complete')
        return self.last_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='172.16.30.1')
    parser.add_argument('--command', default='collect-status')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    shell = DiagnosticShell(args.host)
    try:
        data = shell.run(args.command, args.timeout)
    except RuntimeError:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(shell.last_output)
        raise
    finally:
        shell.socket.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print('Saved diagnostic output:', args.output, len(data), 'bytes')


if __name__ == '__main__':
    main()
