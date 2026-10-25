#!/usr/bin/python3
"""Enable capture of a natural SLPI crash; never trigger a crash."""
from pathlib import Path

nodes = [p for p in Path('/sys/class/remoteproc').glob('remoteproc*')
         if (p / 'name').read_text().strip() == 'slpi']
if len(nodes) != 1:
    raise SystemExit('Expected exactly one SLPI')
(nodes[0] / 'coredump').write_text('enabled\n')
