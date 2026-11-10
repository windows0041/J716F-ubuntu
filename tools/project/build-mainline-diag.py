#!/usr/bin/env python3
"""Build a RAM-only Android v2 diagnostic boot image. Never accesses a device."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-boot', required=True, type=Path)
    parser.add_argument('--minimal', action='store_true',
                        help='Keep only BusyBox and diagnostics to isolate early boot loading')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'out/mainline-7.4-rc2/boot-diag.img')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be new')
    work = ROOT / 'build/mainline'
    tree = work / 'linux-7.4-rc2'
    kernel = tree / 'arch/arm64/boot/Image'
    dtb = tree / 'arch/arm64/boot/dts/qcom/sm8250-lenovo-j716f.dtb'
    busybox = work / 'ubuntu-26.10-rootfs/usr/bin/busybox-static'
    original = args.stock_boot.read_bytes()
    assert original[:8] == b'ANDROID!'
    fields = struct.unpack_from('<10I', original, 8)
    ks, ka, rs, ra, second, sa, tags, page, version, osv = fields
    recovery, recovery_offset, header_size, ds, da = struct.unpack_from('<IQIIQ', original, 1632)
    assert version == 2 and page == 4096 and not second
    assert recovery == recovery_offset == 0 and header_size == 1660
    assert kernel.read_bytes()[56:60] == b'ARMd'
    assert dtb.read_bytes()[:4] == b'\xd0\x0d\xfe\xed'
    applets = subprocess.check_output(['qemu-aarch64-static', str(busybox), '--list'],
                                     text=True).splitlines()
    required = {'sh', 'mount', 'ip', 'telnetd', 'cttyhack', 'setsid', 'dmesg', 'reboot'}
    assert required.issubset(applets)
    command_line = ('console=tty0 rdinit=/init clk_ignore_unused pd_ignore_unused '
                    'cma=256M loglevel=7 panic=0')
    with tempfile.TemporaryDirectory(prefix='j716f-diag-', dir=work) as temporary:
        root = Path(temporary) / 'root'
        root.mkdir()
        for name in ['bin', 'sbin', 'usr/bin', 'usr/sbin', 'dev', 'proc', 'sys', 'run', 'etc']:
            (root / name).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(busybox, root / 'bin/busybox')
        (root / 'bin/busybox').chmod(0o755)
        for name in applets:
            if '/' not in name and name != 'busybox':
                (root / 'bin' / name).symlink_to('busybox')
        for source, name in [('mainline-diag-init', 'init'),
                             ('mainline-collect-status', 'bin/collect-status'),
                             ('mainline-prepare-ram-desktop', 'bin/mainline-prepare-ram-desktop')]:
            dest = root / name
            shutil.copyfile(ROOT / 'configs/initramfs' / source, dest)
            dest.chmod(0o755)
            subprocess.run(['sh', '-n', str(dest)], check=True)
        if not args.minimal:
            shutil.copytree(work / 'firmware-root', root / 'lib/firmware')
            shutil.copytree(work / 'kernel-stage/lib/modules', root / 'lib/modules', symlinks=True)
            for path in (root / 'lib/modules').glob('*/build'):
                assert path.is_symlink()
                path.unlink()
            for path in (root / 'lib/modules').glob('*/source'):
                assert path.is_symlink()
                path.unlink()
        names = ['.'] + sorted(str(p.relative_to(root)) for p in root.rglob('*'))
        for name in names:
            os.utime(root / name, (0, 0), follow_symlinks=False)
        archive = subprocess.run(['cpio', '--null', '-o', '--format=newc', '--owner=0:0', '--reproducible'],
                                 cwd=root, input='\0'.join(names).encode() + b'\0',
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        ramdisk = Path(temporary) / 'ramdisk.gz'
        ramdisk.write_bytes(gzip.compress(archive, compresslevel=9, mtime=0))
        image = Path(temporary) / 'boot.img'
        subprocess.run([sys.executable, str(ROOT / 'mkbootimg-aosp/mkbootimg.py'),
                        '--kernel', str(kernel), '--ramdisk', str(ramdisk), '--dtb', str(dtb),
                        '--base', '0', '--kernel_offset', str(ka), '--ramdisk_offset', str(ra),
                        '--second_offset', str(sa), '--tags_offset', str(tags),
                        '--dtb_offset', str(da), '--pagesize', str(page), '--header_version', '2',
                        '--board', original[48:64].rstrip(b'\0').decode('ascii'),
                        '--cmdline', command_line, '-o', str(image)], check=True)
        contents = bytearray(image.read_bytes())
        # Retain the stock OS-version/patch-level word for vendor loader compatibility.
        struct.pack_into('<I', contents, 44, osv)
        assert len(contents) < 100663296, 'Image exceeds the known boot partition capacity'
        spec = importlib.util.spec_from_file_location('boot_helpers', ROOT / 'tools/add-boot-bluetooth-firmware.py')
        helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helpers)
        parsed = helpers.boot_image(contents)
        assert parsed['os_version'] == osv
        assert parsed['kernel'] == kernel.read_bytes() and parsed['dtb'] == dtb.read_bytes()
        assert parsed['ramdisk'] == ramdisk.read_bytes() and parsed['cmdline'] == command_line
        entries = helpers.cpio_entries(gzip.decompress(parsed['ramdisk']))
        paths = {e['name'].removeprefix('./') for e in entries}
        assert {'init', 'bin/busybox', 'bin/collect-status'}.issubset(paths)
        assert not any('merge-root' in p for p in paths)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('xb') as out:
            out.write(contents)
        manifest = {'purpose': 'RAM-only TB-J716F mainline hardware diagnostic',
                    'kernel_release': (tree / 'include/config/kernel.release').read_text().strip(),
                    'bytes': len(contents), 'sha256': sha(contents), 'kernel_sha256': sha(parsed['kernel']),
                    'dtb_sha256': sha(parsed['dtb']), 'ramdisk_sha256': sha(parsed['ramdisk']),
                    'cmdline': command_line, 'internal_storage_auto_mounted': False,
                    'minimal_ramdisk': args.minimal,
                    'stock_os_version_word_preserved': osv,
                    'partition_merge_helper_included': False, 'hardware_boot_verified': False,
                    'usb_diagnostic_shell': '172.16.30.1:23', 'device_accessed_during_build': False}
        args.output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
