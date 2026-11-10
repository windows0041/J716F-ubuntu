#!/usr/bin/env python3
"""Extract vendor_a from this tablet's split QPST super image, without mounting it.

The LP structures and checksums follow AOSP fs_mgr/liblp/metadata_format.h.
Input files remain unchanged. No device or partition is accessed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    stock = args.stock.resolve(strict=True)
    output = args.output.resolve()
    assert not output.exists(), 'Output must be new'
    original = ET.parse(stock / 'rawprogram0.xml')
    super_entries = [e for e in original.iter('program') if e.get('label') == 'super']
    assert len(super_entries) == 1
    entry = super_entries[0]
    assert entry.get('SECTOR_SIZE_IN_BYTES') == '4096'
    start = int(entry.get('start_sector'))
    size = int(entry.get('num_partition_sectors')) * 4096
    assert start == 217896 and size == 8589934592, 'Not the expected J716F layout'
    segments = []
    for e in ET.parse(stock / 'rawprogram_unsparse0.xml').iter('program'):
        name = e.get('filename', '')
        if e.get('label') != 'super':
            continue
        assert re.fullmatch(r'super_[1-6]\.img', name)
        assert e.get('SECTOR_SIZE_IN_BYTES') == '4096'
        assert e.get('file_sector_offset') == '0'
        path = (stock / name).resolve(strict=True)
        assert path.parent == stock and not (stock / name).is_symlink()
        length = int(e.get('num_partition_sectors')) * 4096
        offset = (int(e.get('start_sector')) - start) * 4096
        assert path.stat().st_size == length and 0 <= offset < offset + length <= size
        segments.append((offset, offset + length, path))
    segments.sort()
    assert len(segments) == 6
    assert all(a[1] <= b[0] for a, b in zip(segments, segments[1:]))

    def read(offset, length):
        assert 0 <= offset <= offset + length <= size
        result = bytearray(length)
        for first, last, path in segments:
            begin, end = max(first, offset), min(last, offset + length)
            if begin < end:
                with path.open('rb') as stream:
                    stream.seek(begin - first)
                    data = stream.read(end - begin)
                assert len(data) == end - begin
                result[begin - offset:end - offset] = data
        return bytes(result)

    geometry = read(4096, 4096)
    assert struct.unpack_from('<II', geometry) == (0x616c4467, 52)
    assert read(8192, 52) == geometry[:52], 'Geometry copies disagree'
    assert hashlib.sha256(geometry[:8] + bytes(32) + geometry[40:52]).digest() == geometry[8:40]
    maximum, slots, block = struct.unpack_from('<III', geometry, 40)
    assert 128 <= maximum <= 1024 * 1024 and 1 <= slots <= 3 and block == 4096
    data = read(12288, maximum)
    magic, major, minor, header_size = struct.unpack_from('<IHHI', data)
    assert magic == 0x414c5030 and major == 10 and minor <= 2
    assert header_size in (128, 256)
    assert hashlib.sha256(data[:12] + bytes(32) + data[44:header_size]).digest() == data[12:44]
    table_size = struct.unpack_from('<I', data, 44)[0]
    assert header_size + table_size <= len(data)
    tables = data[header_size:header_size + table_size]
    assert hashlib.sha256(tables).digest() == data[48:80]

    def table(at, expected_entry_size):
        offset, count, length = struct.unpack_from('<III', data, at)
        assert length == expected_entry_size and offset + count * length <= table_size
        return [tables[offset + i * length:offset + (i + 1) * length] for i in range(count)]

    partitions = table(80, 52)
    extents = table(92, 24)
    devices = table(116, 64)
    assert len(devices) == 1
    listing = []
    selected = None
    for p in partitions:
        name = p[:36].rstrip(b'\0').decode('ascii')
        assert re.fullmatch(r'[a-zA-Z0-9_]+', name)
        attributes, first, count, group = struct.unpack_from('<IIII', p, 36)
        assert first + count <= len(extents)
        parts = [struct.unpack('<QIQI', e) for e in extents[first:first + count]]
        listing.append({'name': name, 'bytes': sum(e[0] * 512 for e in parts)})
        if name == 'vendor_a':
            assert selected is None
            selected = parts
    assert selected, 'Missing vendor_a'
    total = sum(e[0] * 512 for e in selected)
    assert 0 < total < 2 * 1024 ** 3
    digest = hashlib.sha256()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as out:
        for sectors, kind, physical, device in selected:
            assert kind in (0, 1) and device == 0
            remaining, offset = sectors * 512, physical * 512
            assert kind != 0 or offset + remaining <= size
            while remaining:
                length = min(remaining, 4 * 1024 * 1024)
                chunk = read(offset, length) if kind == 0 else bytes(length)
                out.write(chunk)
                digest.update(chunk)
                remaining -= length
                offset += length
    assert output.stat().st_size == total
    manifest = {'partition': 'vendor_a', 'bytes': total, 'sha256': digest.hexdigest(),
                'logical_partitions': listing, 'lp_checksums_verified': True,
                'device_accessed': False}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
