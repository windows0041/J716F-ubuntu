#!/usr/bin/env python3
"""Compare Android sparse payloads to their regular raw filesystem source."""
import argparse
import errno
import importlib.util
import os
from pathlib import Path
import stat
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path)
    parser.add_argument('sparse', type=Path)
    args = parser.parse_args()
    if not all(stat.S_ISREG(p.stat().st_mode) for p in (args.raw, args.sparse)):
        parser.error('Regular local image files required')
    spec = importlib.util.spec_from_file_location('installer', Path(__file__).with_name('install-mainline-disk.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    info = module.inspect_sparse(args.sparse)
    if info['expanded_bytes'] != args.raw.stat().st_size:
        parser.error('Expanded capacity differs from raw image')
    checked, holes = 0, 0
    with args.raw.open('rb', buffering=0) as raw, args.sparse.open('rb') as sparse:
        _, _, _, fh, ch, block, _, chunks, _ = struct.unpack('<I4H4I', sparse.read(28))
        sparse.seek(fh)
        offset = 0
        for _ in range(chunks):
            kind, _, count, size = struct.unpack('<2H2I', sparse.read(ch)[:12])
            length = count * block
            if kind == 0xcac4:
                sparse.read(4)
                continue
            end = offset + length
            fill = sparse.read(4) if kind == 0xcac2 else None
            if kind in (0xcac1, 0xcac2):
                raw.seek(offset)
                left = length
                while left:
                    n = min(left, 1024 * 1024)
                    expected = sparse.read(n) if kind == 0xcac1 else fill * (n // 4)
                    if raw.read(n) != expected:
                        raise RuntimeError(f'Sparse payload differs at raw offset {end-left}')
                    checked += n
                    left -= n
            else:
                # Skip proven filesystem holes; compare any allocated data to zero.
                position = offset
                while position < end:
                    try:
                        data_start = os.lseek(raw.fileno(), position, os.SEEK_DATA)
                    except OSError as error:
                        if error.errno != errno.ENXIO:
                            raise
                        holes += end-position
                        break
                    if data_start >= end:
                        holes += end-position
                        break
                    holes += data_start-position
                    data_end = min(os.lseek(raw.fileno(), data_start, os.SEEK_HOLE), end)
                    raw.seek(data_start)
                    left = data_end-data_start
                    while left:
                        data = raw.read(min(left, 1024 * 1024))
                        if not data or data.strip(b'\0'):
                            raise RuntimeError('DONT_CARE omits nonzero raw data')
                        checked += len(data)
                        left -= len(data)
                    position = data_end
            offset = end
    if checked + holes != args.raw.stat().st_size:
        raise RuntimeError('Comparison coverage mismatch')
    print(f'Compared {checked} allocated bytes and verified {holes} hole bytes; full expanded filesystem matches.')


if __name__ == '__main__':
    main()
