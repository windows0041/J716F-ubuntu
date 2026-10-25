#!/usr/bin/python3
"""Keep #530's kernel/DTB; add guarded offline merge and clean up the initrd."""
import gzip
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from release_config import RELEASE

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('boot_helpers', ROOT / 'tools/add-boot-bluetooth-firmware.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def repack(entry, data):
    name = entry['name'].encode() + b'\0'
    fields = entry['fields'].copy()
    fields[6], fields[11] = len(data), len(name)
    blob = b'070701' + b''.join(f'{x:08x}'.encode() for x in fields) + name
    blob += b'\0' * (-len(blob) % 4)
    blob += data
    return blob + b'\0' * (-len(blob) % 4)


def main():
    output = Path(sys.argv[1])
    assert not output.exists()
    original = (ROOT / 'artifacts-v615/boot-j716f-stereo-530.img').read_bytes()
    assert helpers.sha(original) == '2ffb0e255d250e7ec038d51075da6eefa541faed87f01fd07059c1ef6da5ebaf'
    old = helpers.boot_image(original)
    entries = helpers.cpio_entries(gzip.decompress(old['ramdisk']))
    helper_data = (ROOT / 'build/clean-release/j716f-merge-root').read_bytes()
    assert helper_data[:4] == b'\x7fELF' and struct.unpack_from('<H', helper_data, 18)[0] == 183
    helper_entry = next(e.copy() for e in entries if e['name'].removeprefix('./') == 'init')
    helper_entry['name'] = 'bin/j716f-merge-root'
    helper_entry['fields'] = helper_entry['fields'].copy()
    helper_entry['fields'][:6] = [max(e['fields'][0] for e in entries) + 1, 0o100755, 0, 0, 1, 0]
    rebuilt, removed = [], []
    for entry in entries:
        name = entry['name'].removeprefix('./')
        if name == 'TRAILER!!!':
            rebuilt.append(repack(helper_entry, helper_data))
        if name in ('etc/wifi-auto.conf', 'bin/wifi-autoconnect') or name.startswith(('root/.ssh/', 'etc/ssh/ssh_host_')):
            removed.append(name)
            continue
        if name != 'init':
            rebuilt.append(entry['raw'])
            continue
        text = entry['data'].decode()
        text = text.replace('wpa_cli live there, and /bin/wifi (used by wifi-autoconnect) calls them.',
                            'Wi-Fi association is managed by NetworkManager after switch_root.')
        start = text.index('# telnetd is started')
        end = text.index('for r in /sys/class/usb_role', start)
        rescue = '''# Recovery shell is exposed only when normal root handoff fails.
mkdir -p /dev/pts 2>/dev/null
mount -t devpts none /dev/pts 2>/dev/null
rescue() {
    echo "Ubuntu root handoff failed. USB-only rescue: 172.16.30.1:23"
    if [ -n "$IFACE" ]; then
        telnetd -b 172.16.30.1:23 -l /bin/sh 2>/dev/null &
    fi
    exec /bin/sh
}

'''
        text = text[:start] + rescue + text[end:]
        start = text.index('# --- WiFi bring-up')
        end = text.index('if [ -e /dev/sda18 ]; then', start)
        text = text[:start] + '# NetworkManager configures Wi-Fi after root handoff.\n' + text[end:]
        root_start = text.index('if [ -e /dev/sda18 ]; then')
        text = text[:root_start] + text[root_start:].replace('exec /bin/sh', 'rescue')
        merge = '''# Install the clean 8 GiB filesystem at the former super start, then
# merge GPT entries while every partition on the target LUN is unmounted.
# A mandatory reboot ensures the kernel re-reads the new partition geometry.
/bin/j716f-merge-root --status
LAYOUT=$?
case "$LAYOUT" in
  0) echo ">> userdata already occupies the merged range" ;;
  10)
    mkdir -p /run /newroot || rescue
    /bin/j716f-merge-root --save /run/j716f-gpt-before
    [ "$?" -eq 10 ] || rescue
    mount -t ext4 -o rw,noatime /dev/sda17 /newroot || rescue
    if ! grep -q '^J716F_UBUNTU_CLEAN=2026.10.24-530$' /newroot/etc/j716f-release; then
        umount /newroot
        rescue
    fi
    BACKUP=/newroot/var/lib/j716f-first-boot/gpt-before
    if ! mkdir -p "$BACKUP" || ! cp /run/j716f-gpt-before/* "$BACKUP/"; then
        umount /newroot
        rescue
    fi
    sync
    umount /newroot || rescue
    /bin/j716f-merge-root --apply /run/j716f-gpt-before
    [ "$?" -eq 10 ] || rescue
    sync
    echo ">> super + userdata merged; rebooting before mounting the Ubuntu root"
    reboot -f
    rescue
    ;;
  *) echo "!! GPT/source verification failed; leaving the partition table unchanged"; rescue ;;
esac

'''
        text = text[:root_start] + merge + text[root_start:]
        check = '[ -e /newroot/lib/systemd/systemd ] && [ -f /newroot/etc/passwd ]'
        assert check in text
        text = text.replace(check, check + ' && [ -f /newroot/etc/j716f-release ]')
        assert 'wifi-auto' not in text and 'root:pmos' not in text
        rebuilt.append(repack(entry, text.encode()))
        (ROOT / 'build/clean-release/init.clean').write_text(text)
    assert 'etc/wifi-auto.conf' in removed
    archive = b''.join(rebuilt)
    archive += b'\0' * (-len(archive) % 512)
    ramdisk = gzip.compress(archive, compresslevel=9, mtime=0)
    assert not any(e['name'].removeprefix('./') == 'etc/wifi-auto.conf'
                   for e in helpers.cpio_entries(gzip.decompress(ramdisk)))
    with tempfile.TemporaryDirectory(prefix='j716f-clean-boot-') as tmp:
        work = Path(tmp)
        for name, data in [('Image', old['kernel']), ('ramdisk.gz', ramdisk), ('board.dtb', old['dtb'])]:
            (work / name).write_bytes(data)
        subprocess.run([sys.executable, str(ROOT / 'mkbootimg-aosp/mkbootimg.py'),
                        '--kernel', str(work / 'Image'), '--ramdisk', str(work / 'ramdisk.gz'),
                        '--dtb', str(work / 'board.dtb'), '--pagesize', str(old['page']),
                        '--base', '0', '--kernel_offset', str(old['kernel_addr']),
                        '--ramdisk_offset', str(old['ramdisk_addr']),
                        '--second_offset', str(old['second_addr']), '--tags_offset', str(old['tags_addr']),
                        '--dtb_offset', str(old['dtb_addr']), '--header_version', '2',
                        '--board', old['board'], '--cmdline', old['cmdline'], '-o', str(work / 'boot.img')], check=True)
        image = (work / 'boot.img').read_bytes()
    new = helpers.boot_image(image)
    assert new['kernel'] == old['kernel'] and new['dtb'] == old['dtb']
    assert new['cmdline'] == old['cmdline'] and new['ramdisk'] == ramdisk
    output.write_bytes(image)
    manifest = {'version': RELEASE, 'sha256': helpers.sha(image), 'bytes': len(image),
                'source_sha256': helpers.sha(original), 'kernel_unchanged': True, 'dtb_unchanged': True,
                'removed_ramdisk_entries': removed, 'wifi_credentials_included': False,
                'normal_boot_telnet': False, 'failed_boot_rescue': 'USB only 172.16.30.1:23',
                'stock_layout_merges_super_userdata': True,
                'merge_helper_sha256': helpers.sha(helper_data),
                'merge_before_root_mount': True, 'reboot_after_merge': True,
                'fresh_install_hardware_tested': False}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
