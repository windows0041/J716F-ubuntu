#!/usr/bin/env python3
"""Create experimental no-op overlays retaining stock bootloader selection metadata.

The stock Android fragments must not be applied to a mainline device tree.
Each generated overlay is checked with fdtoverlay against the built mainline DTB.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


def root_properties(blob):
    magic, total, structure, strings, reserve, version, last, cpu, string_size, structure_size = struct.unpack_from('>10I', blob)
    assert magic == 0xd00dfeed and total <= len(blob)
    assert structure + structure_size <= total and strings + string_size <= total
    names = blob[strings:strings + string_size]
    properties = []
    cursor, depth = structure, 0
    while cursor < structure + structure_size:
        token = struct.unpack_from('>I', blob, cursor)[0]
        cursor += 4
        if token == 1:
            end = blob.index(0, cursor)
            cursor = align(end + 1, 4)
            depth += 1
        elif token == 2:
            depth -= 1
        elif token == 3:
            length, name = struct.unpack_from('>II', blob, cursor)
            cursor += 8
            assert cursor + length <= structure + structure_size
            if depth == 1:
                end = names.index(0, name)
                properties.append((names[name:end], blob[cursor:cursor + length]))
            cursor = align(cursor + length, 4)
        elif token == 4:
            continue
        elif token == 9:
            assert depth == 0
            break
        else:
            raise ValueError('Unexpected FDT token')
    assert b'qcom,board-id' in dict(properties)
    return properties


def noop_overlay(properties):
    structure = bytearray(struct.pack('>I', 1) + bytes(4))
    strings = bytearray()
    for name, data in properties:
        offset = len(strings)
        strings += name + b'\0'
        structure += struct.pack('>III', 3, len(data), offset) + data
        structure += bytes(-len(structure) % 4)
    # Some vendor loaders require a fragment even for an otherwise empty overlay.
    structure += struct.pack('>I', 1) + b'fragment@0\0'
    structure += bytes(-len(structure) % 4)
    offset = len(strings)
    strings += b'target-path\0'
    structure += struct.pack('>III', 3, 2, offset) + b'/\0\0\0'
    structure += struct.pack('>I', 1) + b'__overlay__\0'
    structure += bytes(-len(structure) % 4)
    structure += struct.pack('>IIII', 2, 2, 2, 9)
    structure_offset = 56
    strings_offset = structure_offset + len(structure)
    total = strings_offset + len(strings)
    header = struct.pack('>10I', 0xd00dfeed, total, structure_offset, strings_offset,
                         40, 17, 16, 0, len(strings), len(structure))
    return header + bytes(16) + structure + strings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-dtbo', type=Path, required=True)
    parser.add_argument('--mainline-dtb', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    source = args.stock_dtbo.read_bytes()
    magic, total, hs, es, count, offset, page, version = struct.unpack_from('>8I', source)
    assert magic == 0xd7b7ab1e and hs == es == 32 and page == 4096 and version == 0
    assert total <= len(source) and 0 < count < 64 and offset + count * es <= total
    payload = bytearray(align(32 + count * 32, page))
    entries = []
    with tempfile.TemporaryDirectory(prefix='j716f-overlay-check-') as temporary:
        work = Path(temporary)
        for index in range(count):
            size, start, ident, revision, *custom = struct.unpack_from('>8I', source, offset + index * es)
            assert start + size <= total
            blob = noop_overlay(root_properties(source[start:start + size]))
            overlay, applied = work / 'noop.dtbo', work / 'applied.dtb'
            overlay.write_bytes(blob)
            subprocess.run(['fdtoverlay', '-i', str(args.mainline_dtb), '-o', str(applied), str(overlay)], check=True)
            assert applied.read_bytes() == args.mainline_dtb.read_bytes(), 'Overlay changed the mainline DTB'
            start = len(payload)
            payload += blob
            payload += bytes(-len(payload) % page)
            entries.append((len(blob), start, ident, revision, *custom))
    struct.pack_into('>8I', payload, 0, magic, len(payload), 32, 32, count, 32, page, version)
    for index, entry in enumerate(entries):
        struct.pack_into('>8I', payload, 32 + index * 32, *entry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(payload)
    info = {'source_sha256': hashlib.sha256(source).hexdigest(), 'entries': count,
            'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
            'all_overlays_leave_mainline_dtb_byte_identical': True,
            'explicit_noop_fragment': True,
            'hardware_boot_verified': False}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(info, indent=2) + '\n')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
