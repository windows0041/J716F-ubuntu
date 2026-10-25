#!/usr/bin/python3
"""Build the static ARM64 initramfs helper against the clean image's UUID."""
import json
import os
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/clean-release'
with (WORK / 'userdata.raw.img').open('rb') as stream:
    stream.seek(1024)
    sb = stream.read(1024)
assert sb[56:58] == b'\x53\xef' and sb[120:136] == b'j716f-ubuntu'.ljust(16, b'\0')
assert struct.unpack_from('<I', sb, 4)[0] == 2097152
uuid = sb[104:120].hex()
sysroot = ROOT / 'build/light-sysroot'
env = os.environ.copy()
for name in ('CPATH', 'LIBRARY_PATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
    env.pop(name, None)
command = ['aarch64-linux-gnu-gcc', '--sysroot=' + str(sysroot),
           '-B' + str(sysroot / 'usr/lib/aarch64-linux-gnu/'),
           '-O2', '-static', '-no-pie', '-Wall', '-Wextra', '-Werror',
           '-DROOTFS_UUID_HEX="' + uuid + '"',
           str(ROOT / 'tools/release/merge-root.c'), '-o', str(WORK / 'j716f-merge-root')]
subprocess.run(command, env=env, check=True)
print(json.dumps({'rootfs_uuid_hex': uuid, 'binary': str(WORK / 'j716f-merge-root'),
                  'linkage': 'static ARM64'}, indent=2))
