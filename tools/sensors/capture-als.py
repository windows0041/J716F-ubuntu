#!/usr/bin/python3
"""Read SensorProxy and backlight until the user signals test completion."""
import json
import subprocess
import sys
import time
from pathlib import Path

label = sys.argv[1] if len(sys.argv) > 1 else '1'
if label not in ('1', '2'):
    raise SystemExit('Unsupported capture label')
base = Path('/tmp/j716f-als-cover-' + label)
base.mkdir(mode=0o700, exist_ok=True)
monitor_log = (base / 'monitor.log').open('w')
monitor = subprocess.Popen(
    ['/usr/bin/stdbuf', '-oL', '/opt/j716f-sensors/bin/monitor-sensor', '--light'],
    stdout=monitor_log, stderr=subprocess.STDOUT)
deadline = time.monotonic() + 300
previous = None
try:
    with (base / 'values.jsonl').open('w', buffering=1) as log:
        print('READY: ambient-light/backlight capture active', flush=True)
        while time.monotonic() < deadline and not (base / 'stop').exists():
            read = subprocess.run(
                ['busctl', '--system', 'get-property', 'net.hadess.SensorProxy',
                 '/net/hadess/SensorProxy', 'net.hadess.SensorProxy', 'LightLevel'],
                capture_output=True, text=True, timeout=3)
            brightness = Path('/sys/class/backlight/ae94000.dsi.0/brightness').read_text().strip()
            value = (read.stdout.strip(), brightness)
            if value != previous:
                log.write(json.dumps({'monotonic': time.monotonic(), 'light': value[0],
                                      'brightness': brightness}) + '\n')
                previous = value
            time.sleep(.2)
finally:
    monitor.terminate()
    try:
        monitor.wait(timeout=3)
    except subprocess.TimeoutExpired:
        monitor.kill()
        monitor.wait()
    monitor_log.close()
print('DONE: ' + str(base), flush=True)
