#!/usr/bin/python3
"""Bounded passive ALS/FastRPC observation; no display or restart commands."""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

os.umask(0o077)
base = Path('/var/lib/j716f-sensors/stability-20261023/observation-1')
base.mkdir(mode=0o700)
light_log = (base / 'light.log').open('w')
kernel_log = (base / 'kernel.log').open('w')
sample = subprocess.Popen(['/usr/bin/stdbuf', '-oL', '-eL', '/opt/j716f-sensors/bin/ssccli',
                           '--sensor=light', '--timeout=250'],
                          stdout=light_log, stderr=subprocess.STDOUT)
kernel = subprocess.Popen(['dmesg', '--follow-new'], stdout=kernel_log, stderr=subprocess.STDOUT)
seen = set()
deadline = time.monotonic() + 240
print('READY: four-minute native ALS and crash observation; no automatic brightness', flush=True)
try:
    with (base / 'state.jsonl').open('w', buffering=1) as state_log:
        while time.monotonic() < deadline:
            status = subprocess.run(['systemctl', 'show', 'j716f-als-rpc-capture.service',
                                     '-p', 'ActiveState', '-p', 'Result', '-p', 'ExecMainStatus'],
                                    capture_output=True, text=True, timeout=3)
            state_log.write(json.dumps(dict(monotonic=time.monotonic(),
                remoteproc=Path('/sys/class/remoteproc/remoteproc0/state').read_text().strip(),
                service=status.stdout.strip(), light_exit=sample.poll())) + '\n')
            for core in Path('/sys/class/devcoredump').glob('devcd*'):
                if core.name in seen:
                    continue
                seen.add(core.name)
                target = str((core / 'failing_device').resolve())
                if '5c00000' not in target and 'remoteproc0' not in target:
                    print('Other device core ignored: ' + target, flush=True)
                    continue
                dest = base / (core.name + '.elf')
                with (core / 'data').open('rb') as source, dest.open('wb') as output:
                    shutil.copyfileobj(source, output)
                digest = hashlib.sha256(dest.read_bytes()).hexdigest()
                print('Saved SLPI core: ' + json.dumps(dict(path=str(dest), bytes=dest.stat().st_size,
                                                          sha256=digest)), flush=True)
            time.sleep(2)
finally:
    for proc in (sample, kernel):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    light_log.close()
    kernel_log.close()
print('DONE: ' + str(base), flush=True)
