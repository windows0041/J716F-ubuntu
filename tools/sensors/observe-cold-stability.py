#!/usr/bin/python3
"""Ten-minute boot observation without sensor claims or display changes."""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

os.umask(0o077)
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
base = Path('/var/lib/j716f-sensors/stability-20261023') / ('cold-' + boot)
base.mkdir(mode=0o700)
kernel_log = (base / 'kernel.log').open('w')
kernel = subprocess.Popen(['dmesg', '--follow'], stdout=kernel_log, stderr=subprocess.STDOUT)
seen = set()
deadline = time.monotonic() + 600

def read_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=4)
        return result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 'timeout while collecting state'

print('Observing natural SLPI startup/crashes: ' + str(base), flush=True)
try:
    with (base / 'state.jsonl').open('w', buffering=1) as log:
        while time.monotonic() < deadline:
            status = read_command(['systemctl', 'show', 'j716f-sensor-rpc.service',
                                     'iio-sensor-proxy.service', '-p', 'Id', '-p', 'ActiveState',
                                     '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'NRestarts'])
            lux = read_command(['busctl', '--system', 'get-property', 'net.hadess.SensorProxy',
                                  '/net/hadess/SensorProxy', 'net.hadess.SensorProxy', 'LightLevel'])
            log.write(json.dumps(dict(monotonic=time.monotonic(), services=status,
                                      light=lux)) + '\n')
            for core in Path('/sys/class/devcoredump').glob('devcd*'):
                if core.name in seen:
                    continue
                seen.add(core.name)
                target = str((core / 'failing_device').resolve())
                if '5c00000' not in target and 'remoteproc0' not in target:
                    continue
                dest = base / (core.name + '.elf')
                with (core / 'data').open('rb') as src, dest.open('wb') as out:
                    shutil.copyfileobj(src, out)
                digest = hashlib.sha256(dest.read_bytes()).hexdigest()
                print('Saved SLPI crash core: ' + json.dumps(dict(file=str(dest),
                    bytes=dest.stat().st_size, sha256=digest)), flush=True)
            time.sleep(5)
finally:
    kernel.terminate()
    try:
        kernel.wait(timeout=3)
    except subprocess.TimeoutExpired:
        kernel.kill()
        kernel.wait()
    kernel_log.close()
print('Observation complete', flush=True)
