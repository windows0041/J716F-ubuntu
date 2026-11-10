#!/usr/bin/env python3
"""Restore the saved software clock after PMIC hctosys; never write the RTC."""
import json
import os
from pathlib import Path
import subprocess
import time

if os.geteuid() != 0 or b'lenovo,j716f' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
    raise SystemExit('J716F root context required')
rtc = Path('/sys/class/rtc/rtc0/hctosys')
deadline = time.monotonic() + 12
while time.monotonic() < deadline:
    try:
        if rtc.read_text().strip() == '1':
            break
    except OSError:
        pass
    time.sleep(.1)
else:
    raise SystemExit('RTC hctosys did not complete; system clock left unchanged')
before = time.time()
subprocess.run(['/usr/sbin/fake-hwclock', 'load'], check=True, timeout=5)
print(json.dumps({'rtc_hctosys_complete': True, 'before_epoch': before, 'after_epoch': time.time()}))
