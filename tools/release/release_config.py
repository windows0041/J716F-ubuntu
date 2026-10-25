"""Current clean installer output paths; older published bundles stay intact."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/clean-release'
PACKAGE = ROOT / 'releases/j716f-ubuntu-22.04-clean-530-r3'
RELEASE = '2026.10.24-clean-530-r3'
