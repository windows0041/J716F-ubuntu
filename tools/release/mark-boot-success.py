#!/usr/bin/python3
"""Mark the current J716F boot slot successful after the desktop has started."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    assert os.geteuid() == 0
    assert b'lenovo,j716f' in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    assert Path('/var/lib/j716f-first-boot/complete.json').is_file()
    subprocess.run(['systemctl', 'is-active', '--quiet', 'display-manager.service'], check=True)
    slot = re.search(r'(?:^| )androidboot.slot_suffix=_(a|b)(?: |$)', Path('/proc/cmdline').read_text())
    assert slot
    tool = Path('/usr/local/libexec/j716f-qbootctl')
    assert hashlib.sha256(tool.read_bytes()).hexdigest() == '6809613f9aa6382bae6baeeb21f2b98261b73d7a5ce80435d6f85c67b4e4ceb7'
    result = subprocess.run([str(tool), '-m', slot[1]], check=True, capture_output=True, text=True, timeout=30)
    state = Path('/var/lib/j716f-first-boot/slot-success.json')
    state.write_text(json.dumps({'slot': slot[1], 'result': result.stdout}, indent=2) + '\n')


if __name__ == '__main__':
    main()
