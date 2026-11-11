#!/usr/bin/env python3
"""Append cma=256M to a verified Android v2 image; never flash a device."""

import importlib.util
from pathlib import Path
import sys


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: set-boot-cma.py source-boot.img new-boot.img')
    source, output = map(Path, sys.argv[1:])
    if output.exists() or source.resolve() == output.resolve():
        raise SystemExit('Output must be a new file.')
    helper = Path(__file__).resolve().parents[1] / 'add-boot-bluetooth-firmware.py'
    spec = importlib.util.spec_from_file_location('boot_helpers', helper)
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)
    data = source.read_bytes()
    old = boot.boot_image(data)
    # The v2 image ID covers the payloads, which stay byte-for-byte identical.
    words = [word for word in old['cmdline'].split() if not word.startswith('cma=')]
    encoded = (' '.join(words) + ' cma=256M').encode('ascii')
    if len(encoded) > 1534:
        raise SystemExit('Command line is too long.')
    image = bytearray(data)
    image[64:576] = encoded[:511].ljust(512, b'\0')
    image[608:1632] = encoded[511:].ljust(1024, b'\0')
    new = boot.boot_image(image)
    if any(new[key] != old[key] for key in old if key != 'cmdline'):
        raise SystemExit('Unexpected payload or header change.')
    if new['cmdline'].encode() != encoded:
        raise SystemExit('Command line readback mismatch.')
    with output.open('xb') as stream:
        stream.write(image)
    print('Original SHA256:', boot.sha(data))
    print('Updated SHA256: ', boot.sha(image))
    print('Only command-line bytes changed; no device was accessed.')


if __name__ == '__main__':
    main()
