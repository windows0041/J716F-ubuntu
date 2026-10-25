#!/usr/bin/python3
"""Start the tablet's SLPI after the root firmware filesystem is available."""
import time
from pathlib import Path

matches = [p for p in Path('/sys/class/remoteproc').glob('remoteproc*')
           if (p / 'name').read_text().strip() == 'slpi']
if len(matches) != 1:
    raise SystemExit('Expected exactly one SLPI remote processor')
state = matches[0] / 'state'
current = state.read_text().strip()
if current == 'offline':
    state.write_text('start\n')
elif current != 'running':
    raise SystemExit('SLPI has unexpected state: ' + current)
for _ in range(100):
    if state.read_text().strip() == 'running' and Path('/dev/fastrpc-sdsp').exists():
        print('SLPI running, fastrpc-sdsp available', flush=True)
        break
    time.sleep(.2)
else:
    raise SystemExit('SLPI/FastRPC did not become ready')
