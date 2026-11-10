#!/usr/bin/env python3
"""Build a RAM-only diagnostic using the user-verified R3 boot format and firmware.

The release init and partition merge executable are removed. Optional kernel/DTB
replacement supports controlled upstream migration without starting an installer.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def repack(entry, name, data, inode=None, mode=None):
    fields = entry['fields'].copy()
    if inode is not None:
        fields[0] = inode
    if mode is not None:
        fields[1] = mode
    fields[5], fields[6] = 0, len(data)
    encoded = name.encode() + b'\0'
    fields[11] = len(encoded)
    result = b'070701' + b''.join(f'{v:08x}'.encode() for v in fields) + encoded
    result += bytes(-len(result) % 4)
    result += data
    return result + bytes(-len(result) % 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verified-boot', type=Path, required=True)
    parser.add_argument('--kernel', type=Path)
    parser.add_argument('--dtb', type=Path)
    parser.add_argument('--firmware-dir', type=Path, help='Additional local firmware, installed under /lib/firmware')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    original = args.verified_boot.read_bytes()
    published = json.loads((ROOT / 'docs/releases/boot-manifest.json').read_text())
    assert sha(original) == published['sha256'], 'Not the pinned R3 boot image'
    spec = importlib.util.spec_from_file_location('boot_helpers', ROOT / 'tools/add-boot-bluetooth-firmware.py')
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    old = helpers.boot_image(original)
    kernel = args.kernel.read_bytes() if args.kernel else old['kernel']
    dtb = args.dtb.read_bytes() if args.dtb else old['dtb']
    entries = helpers.cpio_entries(gzip.decompress(old['ramdisk']))
    by_name = {e['name'].removeprefix('./'): e for e in entries}
    init = (ROOT / 'configs/initramfs/mainline-diag-init').read_bytes()
    collector = (ROOT / 'configs/initramfs/mainline-collect-status').read_bytes()
    ram_desktop = (ROOT / 'configs/initramfs/mainline-prepare-ram-desktop').read_bytes()
    inode = max(e['fields'][0] for e in entries) + 1
    extra_firmware = {}
    if args.firmware_dir:
        firmware_root = args.firmware_dir.resolve(strict=True)
        for path in sorted(firmware_root.rglob('*')):
            if path.is_symlink():
                parser.error('Additional firmware must not contain symlinks')
            if path.is_file():
                name = 'lib/firmware/' + path.relative_to(firmware_root).as_posix()
                extra_firmware[name] = path.read_bytes()
    rebuilt = []
    removed = []
    for entry in entries:
        name = entry['name'].removeprefix('./')
        if name in ['bin/j716f-merge-root', 'init', 'TRAILER!!!']:
            removed.append(name)
            continue
        if name not in extra_firmware:
            rebuilt.append(entry['raw'])
    # Add only missing parent directories; keep one CPIO entry per pathname.
    added_inode = inode + 4
    directories = set(by_name)
    for name, data in extra_firmware.items():
        for parent in reversed(Path(name).parents):
            parent_name = parent.as_posix()
            if parent_name != '.' and parent_name not in directories:
                rebuilt.append(repack(by_name['init'], parent_name, b'', inode=added_inode, mode=0o40755))
                added_inode += 1
                directories.add(parent_name)
        rebuilt.append(repack(by_name['init'], name, data, inode=added_inode, mode=0o100644))
        added_inode += 1
    rebuilt.append(repack(by_name['init'], 'init', init, inode=inode, mode=0o100755))
    rebuilt.append(repack(by_name['init'], 'bin/collect-status', collector, inode=inode + 1, mode=0o100755))
    # The verified BusyBox has cttyhack, although the release archive may omit its link.
    if 'bin/cttyhack' not in by_name:
        rebuilt.append(repack(by_name['bin/sh'], 'bin/cttyhack', b'busybox', inode=inode + 2, mode=0o120777))
    rebuilt.append(repack(by_name['init'], 'bin/mainline-prepare-ram-desktop', ram_desktop, inode=inode + 3, mode=0o100755))
    rebuilt.append(by_name['TRAILER!!!']['raw'])
    archive = b''.join(rebuilt)
    archive += bytes(-len(archive) % 512)
    ramdisk = gzip.compress(archive, compresslevel=9, mtime=0)
    checked = helpers.cpio_entries(gzip.decompress(ramdisk))
    names = {e['name'].removeprefix('./') for e in checked}
    assert not any('merge-root' in p for p in names)
    assert next(e['data'] for e in checked if e['name'] == 'init') == init
    with tempfile.TemporaryDirectory(prefix='j716f-verified-diag-', dir=ROOT / 'build/mainline') as temporary:
        work = Path(temporary)
        for name, data in [('Image', kernel), ('board.dtb', dtb), ('ramdisk.gz', ramdisk)]:
            (work / name).write_bytes(data)
        image = work / 'boot.img'
        subprocess.run([sys.executable, str(ROOT / 'mkbootimg-aosp/mkbootimg.py'),
                        '--kernel', str(work / 'Image'), '--ramdisk', str(work / 'ramdisk.gz'),
                        '--dtb', str(work / 'board.dtb'), '--pagesize', str(old['page']), '--base', '0',
                        '--kernel_offset', str(old['kernel_addr']), '--ramdisk_offset', str(old['ramdisk_addr']),
                        '--second_offset', str(old['second_addr']), '--tags_offset', str(old['tags_addr']),
                        '--dtb_offset', str(old['dtb_addr']), '--header_version', '2', '--board', old['board'],
                        '--cmdline', old['cmdline'], '-o', str(image)], check=True)
        contents = bytearray(image.read_bytes())
        struct.pack_into('<I', contents, 44, old['os_version'])
    parsed = helpers.boot_image(contents)
    assert parsed['kernel'] == kernel and parsed['dtb'] == dtb and parsed['ramdisk'] == ramdisk
    assert parsed['cmdline'] == old['cmdline'] and len(contents) <= 100663296
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(contents)
    manifest = {'source_verified_boot_sha256': sha(original), 'bytes': len(contents),
                'sha256': sha(contents), 'kernel_sha256': sha(kernel), 'dtb_sha256': sha(dtb),
                'ramdisk_sha256': sha(ramdisk), 'cmdline': old['cmdline'],
                'original_kernel': args.kernel is None, 'original_dtb': args.dtb is None,
                'release_init_replaced': True, 'partition_merge_executable_removed': True,
                'diagnostic_init_sha256': sha(init), 'ram_desktop_helper_sha256': sha(ram_desktop),
                'internal_storage_auto_mounted': False, 'hardware_boot_verified': False,
                'extra_firmware': {n: {'bytes': len(d), 'sha256': sha(d)} for n, d in extra_firmware.items()},
                'ram_desktop_requires_explicit_run_marker': True}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
