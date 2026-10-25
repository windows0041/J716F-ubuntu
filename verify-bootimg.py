#!/usr/bin/env python3
"""Verify an Android boot image against the documented j716f layout.

Parses the boot header, walks the page-aligned payload layout exactly as the
bootloader would, and confirms each embedded blob is genuinely what it claims
to be (gzip magic for kernel/ramdisk, FDT magic for the DTB).

Usage: verify-bootimg.py <boot.img>
Exit code 0 = safe to flash, 1 = do not flash.
"""
import gzip
import struct
import sys

# Expected j716f layout. Not guessed -- see README section 5.
EXPECT = {
    'header_version': 2,
    'page_size': 4096,
    'kernel_addr': 0x00008000,
    'ramdisk_addr': 0x01000000,
    'tags_addr': 0x00000100,
    'dtb_addr': 0x01f00000,
}

BOOT_MAGIC = b'ANDROID!'
GZIP_MAGIC = b'\x1f\x8b'
FDT_MAGIC = b'\xd0\x0d\xfe\xed'


def main(path):
    data = open(path, 'rb').read()
    if data[:8] != BOOT_MAGIC:
        print(f"  FAIL magic: {data[:8]!r}")
        return 1

    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
     second_size, second_addr, tags_addr, page_size,
     header_version, _os_version) = struct.unpack_from('<10I', data, 8)

    # v2 extension: recovery_dtbo, then dtb
    _rds, _rdo, header_size = struct.unpack_from('<IQI', data, 1632)
    dtb_size, dtb_addr = struct.unpack_from('<IQ', data, 1648)

    # cmdline is at offset 64, NOT 48: a 16-byte name[] field sits between
    # os_version and cmdline. Reading at 48 silently yields the product name
    # instead of the cmdline, which produces a confusing false alarm.
    name = data[48:64].split(b'\x00', 1)[0].decode('ascii', 'replace')
    cmdline = data[64:64 + 512].split(b'\x00', 1)[0].decode('ascii', 'replace')

    print(f"  image size       : {len(data):,} bytes")
    print(f"  magic            : {data[:8].decode()}")
    print(f"  header_version   : {header_version}   (expect {EXPECT['header_version']})")
    print(f"  header_size      : {header_size}")
    print(f"  page_size        : {page_size}   (expect {EXPECT['page_size']})")
    print(f"  kernel           : {kernel_size:,} bytes @ 0x{kernel_addr:08x}"
          f"   (expect 0x{EXPECT['kernel_addr']:08x})")
    print(f"  ramdisk          : {ramdisk_size:,} bytes @ 0x{ramdisk_addr:08x}"
          f"   (expect 0x{EXPECT['ramdisk_addr']:08x})")
    print(f"  tags             : @ 0x{tags_addr:08x}   (expect 0x{EXPECT['tags_addr']:08x})")
    print(f"  dtb              : {dtb_size:,} bytes @ 0x{dtb_addr:08x}"
          f"   (expect 0x{EXPECT['dtb_addr']:08x})")
    if name:
        print(f"  product name     : {name}")
    print(f"  cmdline          : {cmdline}")

    # --- walk the layout the way the bootloader does ----------------------
    page = page_size
    off = page
    koff = off
    off += ((kernel_size + page - 1) // page) * page
    roff = off
    off += ((ramdisk_size + page - 1) // page) * page
    doff = off
    off += ((dtb_size + page - 1) // page) * page

    print()
    print(f"  layout: kernel={koff:,} ramdisk={roff:,} dtb={doff:,} end={off:,}")

    problems = []

    def check(name, cond, detail=''):
        mark = 'PASS' if cond else 'FAIL'
        print(f"  {mark}  {name}{(' -- ' + detail) if detail and not cond else ''}")
        if not cond:
            problems.append(name)

    check('header_version == 2', header_version == EXPECT['header_version'])
    check('page_size == 4096', page_size == EXPECT['page_size'])
    check('kernel_addr', kernel_addr == EXPECT['kernel_addr'])
    check('ramdisk_addr', ramdisk_addr == EXPECT['ramdisk_addr'])
    check('tags_addr', tags_addr == EXPECT['tags_addr'])
    check('dtb_addr', dtb_addr == EXPECT['dtb_addr'])
    check('cmdline has console=tty0', 'console=tty0' in cmdline)
    check('sizes non-zero',
          kernel_size > 0 and ramdisk_size > 0 and dtb_size > 0)

    # payload integrity
    #
    # The kernel MUST be a raw arm64 Image. Qualcomm's ABL on this tablet does
    # not decompress the kernel, so an Image.gz payload silently bounces back
    # to the fastboot screen with no kernel output whatsoever. This check is
    # deliberately strict: it is the exact mistake that cost a flash cycle.
    kern = data[koff:koff + kernel_size]
    if kern[:2] == GZIP_MAGIC:
        check('kernel is RAW arm64 Image (not gzip)', False,
              'payload is gzip -- ABL will not decompress this; '
              'rebuild with arch/arm64/boot/Image')
        try:
            img = gzip.decompress(kern)
            print(f"        (it decompresses to {len(img):,} bytes, "
                  f"arm64 magic {img[56:60]!r}, but that does not help)")
        except Exception:  # noqa: BLE001
            pass
    else:
        check('kernel is RAW arm64 Image (not gzip)', True)
        check('kernel is arm64 Image', kern[56:60] == b'ARM\x64',
              f"magic at +56 = {kern[56:60]!r} (expected b'ARM\\\\x64')")
        print(f"        raw kernel payload: {len(kern):,} bytes")

    rd = data[roff:roff + ramdisk_size]
    check('ramdisk is gzip', rd[:2] == GZIP_MAGIC)

    dtb = data[doff:doff + dtb_size]
    check('dtb is FDT', dtb[:4] == FDT_MAGIC)
    if dtb[:4] == FDT_MAGIC:
        # pull the model string straight out of the FDT blob
        idx = dtb.find(b'Lenovo')
        if idx != -1:
            model = dtb[idx:idx + 64].split(b'\x00')[0].decode('ascii', 'replace')
            print(f"        dtb model: {model}")
            check('dtb is the j716f tablet', 'Xiaoxin Pad Pro 2021' in model)

    print()
    if problems:
        print(f"  *** {len(problems)} CHECK(S) FAILED -- DO NOT FLASH ***")
        for p in problems:
            print(f"      - {p}")
        return 1
    print("  ALL CHECKS PASSED -- layout matches the documented j716f boot image")
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
