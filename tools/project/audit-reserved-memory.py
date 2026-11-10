#!/usr/bin/env python3
"""Inspect static firmware reservations in Android boot DTBs and DTBO entries."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def fdt_properties(blob):
    """Return path/property -> (data, byte offset), retaining exact wire bytes."""
    magic, total, structure, strings, _, _, _, _, names_size, size = struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or total > len(blob):
        raise ValueError('Invalid FDT header')
    if structure + size > total or strings + names_size > total:
        raise ValueError('Invalid FDT bounds')
    names = blob[strings:strings + names_size]
    result, stack, cursor = {}, [], structure
    while cursor < structure + size:
        token = struct.unpack_from('>I', blob, cursor)[0]
        cursor += 4
        if token == 1:
            end = blob.index(0, cursor, structure + size)
            stack.append(blob[cursor:end].decode())
            cursor = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, name = struct.unpack_from('>II', blob, cursor)
            cursor += 8
            if cursor + length > structure + size:
                raise ValueError('Invalid property bounds')
            prop = names[name:names.index(0, name)].decode()
            path = '/' + '/'.join(stack[1:])
            key = (path, prop)
            if key in result:
                raise ValueError('Duplicate property')
            result[key] = (blob[cursor:cursor + length], cursor)
            cursor = (cursor + length + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            if stack:
                raise ValueError('Unclosed FDT nodes')
            return result
        else:
            raise ValueError('Invalid FDT token')
    raise ValueError('Missing FDT end')


def describe(blob, source):
    props = fdt_properties(blob)
    regions = []
    for (path, name), (data, _) in props.items():
        if name != 'reg' or 'reserved-memory/' not in path:
            continue
        if len(data) != 16:
            continue
        start, size = struct.unpack('>QQ', data)
        regions.append({'node': path, 'start': hex(start), 'size': hex(size),
                        'end_exclusive': hex(start + size),
                        'no_map': (path, 'no-map') in props})
    root = {name: data.hex() for (path, name), (data, _) in props.items()
            if path == '/' and name in ('qcom,msm-id', 'qcom,board-id')}
    return {'source': source, 'sha256': hashlib.sha256(blob).hexdigest(),
            'selection': root, 'regions': regions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-boot', type=Path, required=True)
    parser.add_argument('--stock-dtbo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.stock_boot.read_bytes()
    if raw[:8] != b'ANDROID!':
        raise ValueError('Not an Android boot image')
    ks, _, rs, _, second, _, _, page, version, _ = struct.unpack_from('<10I', raw, 8)
    if version != 2 or second:
        raise ValueError('Expected header v2 without second stage')
    size = struct.unpack_from('<I', raw, 1648)[0]
    offset = page + ((ks + page - 1) // page + (rs + page - 1) // page) * page
    section = raw[offset:offset + size]
    entries, at = [], 0
    while at < len(section):
        if not any(section[at:]):
            break
        total = struct.unpack_from('>I', section, at + 4)[0]
        blob = section[at:at + total]
        entries.append(describe(blob, f'boot.dtb[{len(entries)}]'))
        at += total
    dtbo = args.stock_dtbo.read_bytes()
    magic, total, hs, es, count, table, _, version = struct.unpack_from('>8I', dtbo)
    if magic != 0xd7b7ab1e or hs != 32 or es != 32 or total > len(dtbo) or version != 0:
        raise ValueError('Invalid Android DTBO table')
    for index in range(count):
        size, offset = struct.unpack_from('>II', dtbo, table + index * es)
        if offset + size > total:
            raise ValueError('Invalid overlay bounds')
        entries.append(describe(dtbo[offset:offset + size], f'dtbo[{index}]'))
    result = {'stock_boot_sha256': hashlib.sha256(raw).hexdigest(),
              'stock_dtbo_sha256': hashlib.sha256(dtbo).hexdigest(),
              'trees': entries}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    for entry in entries:
        print(entry['source'], entry['selection'])
        for region in entry['regions']:
            if int(region['start'], 16) < 0x86200000 and int(region['end_exclusive'], 16) > 0x80b00000:
                print(json.dumps(region))


if __name__ == '__main__':
    main()
