#!/usr/bin/python3
"""Wait for actual ambient-light discovery before starting SensorProxy."""
import re
import subprocess
import time

for attempt in range(3):
    try:
        result = subprocess.run(
            ['/usr/bin/python3', '/opt/j716f-sensors/libexec/ssc-discover.py', 'ambient_light'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        print('Ambient-light discovery timed out (attempt %d/3)' % (attempt + 1),
              flush=True)
    else:
        print(result.stdout, flush=True)
        if result.returncode == 0 and re.search(
                r"data-type 'ambient_light': [0-9a-f]{32}(?:\s|,|$)", result.stdout):
            raise SystemExit(0)
    # Three 30-second discovery attempts and two 2-second pauses leave six
    # seconds of headroom under the unit's TimeoutStartSec=100.
    if attempt < 2:
        time.sleep(2)
raise SystemExit('SLPI did not publish an ambient-light sensor')
