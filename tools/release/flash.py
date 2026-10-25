#!/usr/bin/env python3
"""Install the clean J716F image using bootloader fastboot. No third-party Python modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

BASE = Path(__file__).resolve().parent
EXPECTED = {
    'boot_a': 'boot.img', 'boot_b': 'boot.img',
    'recovery_a': 'boot.img', 'recovery_b': 'boot.img',
    'dtbo_a': 'dtbo.img', 'dtbo_b': 'dtbo.img',
    'vbmeta_a': 'vbmeta.img', 'vbmeta_b': 'vbmeta.img',
}
FIXED_SIZES = {'boot_a': 100663296, 'boot_b': 100663296,
               'recovery_a': 104857600, 'recovery_b': 104857600,
               'dtbo_a': 25165824, 'dtbo_b': 25165824,
               'vbmeta_a': 65536, 'vbmeta_b': 65536}
ROOTFS_IMAGE = 'userdata.img'
LAYOUTS = {'stock': {'userdata': 116237611008, 'super': 8589934592, 'target': 'super'},
           'merged': {'userdata': 124827545600, 'super': 0, 'target': 'userdata'}}


def commands(layout, no_reboot=False):
    yield ['erase', 'userdata']
    if layout == 'stock':
        yield ['erase', 'super']
    yield ['-S', '64M', 'flash', LAYOUTS[layout]['target'], 'images/' + ROOTFS_IMAGE]
    for partition, image in EXPECTED.items():
        yield ['-S', '64M', 'flash', partition, 'images/' + image]
    yield ['set_active', 'a']
    if not no_reboot:
        yield ['reboot']


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def verify_package():
    manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
    require(manifest['device'] == 'TB-J716F-128GB' and manifest['kernel'] == '6.15.11 #530', 'Wrong package')
    require(manifest['partition_images'] == EXPECTED, 'Unexpected partition write plan')
    require(manifest['rootfs_targets'] == {'stock': 'super', 'merged': 'userdata'} and
            manifest['merge_super_userdata'] is True, 'Missing required super/userdata merge')
    require(manifest['pulseaudio_enabled_for_fresh_accounts'] is True and
            manifest['speaker_test_app_included'] is False and
            manifest['fingerprint_private_libraries_included'] is True, 'Not the corrected R3 runtime package')
    for name in sorted(set(EXPECTED.values()) | {ROOTFS_IMAGE}):
        path = BASE / 'images' / name
        info = manifest['images'][name]
        print('验证镜像 / Verifying:', name, flush=True)
        require(path.is_file() and not path.is_symlink(), 'Missing or symlinked image: ' + name)
        require(path.stat().st_size == info['bytes'] and sha(path) == info['sha256'], 'Image checksum mismatch: ' + name)
    with (BASE / 'images/userdata.img').open('rb') as stream:
        magic, major, minor, header_size, chunk_size, block, blocks, chunks, checksum = struct.unpack('<I4H4I', stream.read(28))
    require(magic == 0xed26ff3a and major == 1 and block == 4096, 'Invalid Android sparse image')
    require(block * blocks == manifest['rootfs_expanded_bytes'], 'Sparse expanded size mismatch')
    require(block * blocks == LAYOUTS['stock']['super'], 'Rootfs must fit exactly in stock super')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fastboot', help='Path to the SDK platform-tools fastboot binary')
    parser.add_argument('--serial', help='Select exactly this fastboot device')
    parser.add_argument('--plan', action='store_true', help='Verify package and print plan without accessing USB')
    parser.add_argument('--dry-run', action='store_true', help='Read-only device checks; do not flash or reboot')
    parser.add_argument('--no-reboot', action='store_true', help='Flash and select A, then remain in fastboot')
    args = parser.parse_args()
    manifest = verify_package()
    print('\n设备：Lenovo TB-J716F 128GB；Ubuntu 22.04 ARM64 / kernel #530')
    print('原厂布局：擦除 super 和 userdata；首次引导自动合并后扩容 Ubuntu。')
    print('已合并布局：直接重装 userdata。A/B 两槽的 boot、recovery、dtbo、vbmeta 都会覆盖。')
    print('Android/Ubuntu 系统与个人文件会被清除，不能通过切槽恢复 Android。\n')
    if args.plan:
        print('OFFLINE PLAN ONLY — no USB commands have been executed')
        for layout in LAYOUTS:
            print('\nLayout:', layout)
            for command in commands(layout, args.no_reboot):
                print('fastboot', *command)
            if layout == 'stock':
                print('First initramfs: back up target GPT -> merge super + userdata -> reboot -> grow ext4')
        return
    executable = 'fastboot.exe' if os.name == 'nt' else 'fastboot'
    candidates = [args.fastboot, str(BASE / 'platform-tools' / executable), shutil.which(executable)]
    fastboot = next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)
    require(fastboot, '未找到 fastboot。请将官方 platform-tools 文件夹放在本目录，或使用 --fastboot 指定路径。')

    def read(command, allow_failure=False):
        p = subprocess.run([fastboot] + command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, errors='replace', timeout=20)
        if not allow_failure:
            require(p.returncode == 0, p.stdout)
        return p.stdout

    devices = [line.split()[0] for line in read(['devices']).splitlines()
               if line.strip().endswith('fastboot') and len(line.split()) == 2]
    serial = args.serial or (devices[0] if len(devices) == 1 else None)
    require(serial and serial in devices, '请只连接一台已进入 bootloader fastboot 的平板，或使用 --serial。')
    prefix = ['-s', serial]

    def getvar(key, optional=False):
        text = read(prefix + ['getvar', key], allow_failure=optional)
        match = re.search(r'(?m)^(?:\(bootloader\)\s*)?' + re.escape(key) + r':\s*(\S.*?)\s*$', text)
        if optional:
            return match[1] if match else None
        require(match, 'Unable to read ' + key + ': ' + text)
        return match[1]

    require(getvar('is-userspace', optional=True) != 'yes', '请使用 bootloader fastboot；不是 Android fastbootd。')
    product = getvar('product')
    normalized = re.sub(r'[^a-z0-9]', '', product.lower())
    require('j716f' in normalized or normalized in ('kona', 'sm8250'), 'Unexpected fastboot product: ' + product)
    unlocked = getvar('unlocked', optional=True)
    if unlocked is None:
        info = read(prefix + ['oem', 'device-info'], allow_failure=True)
        unlocked = 'yes' if re.search(r'Device unlocked:\s*true', info, re.I) else None
    require(unlocked is not None and unlocked.lower() in ('yes', 'true', '1'), 'Bootloader 未确认解锁；停止，不执行刷写。')
    for partition in EXPECTED:
        text = getvar('partition-size:' + partition)
        size = int(text, 16)
        require(size == FIXED_SIZES[partition], 'Unexpected partition size: ' + partition)
        print(partition, size)
    userdata_size = int(getvar('partition-size:userdata'), 16)
    super_text = getvar('partition-size:super', optional=True)
    super_size = int(super_text, 16) if super_text is not None else 0
    layout = next((name for name, info in LAYOUTS.items()
                   if userdata_size == info['userdata'] and super_size == info['super']), None)
    require(layout, 'super/userdata 不是已审核的原厂或已合并布局；停止刷写。')
    print('userdata:', userdata_size, '; super:', super_size, '; layout:', layout)
    print('Rootfs flash target:', LAYOUTS[layout]['target'])
    print('\n已完成只读预检。fastboot product:', product, '; serial:', serial)
    print('product 可能只报告通用 SoC，请同时确认平板实物型号是 TB-J716F 128GB。')
    if args.dry_run:
        print('DRY RUN complete: no erase, flash, slot change or reboot performed.')
        return
    print('\n下一步会清除 userdata' + (' 和 super，随后自动合并' if layout == 'stock' else '') + '。请先备份全部个人文件。')
    require(input('确认型号、备份完成后，输入 FLASH TB-J716F 继续：').strip() == 'FLASH TB-J716F', 'Cancelled')

    def write(command):
        print('\n>', ' '.join([executable] + prefix + command), flush=True)
        subprocess.run([fastboot] + prefix + command, check=True)

    for command in commands(layout, args.no_reboot):
        command = [str(BASE / part) if part.startswith('images/') else part for part in command]
        write(command)
    print('\n刷写完成。首次启动等待约 2–5 分钟；原厂布局合并后会自动多重启一次，请勿断电。')
    print('用户名 ubuntu，初始密码 ubuntu；登录后运行 passwd。')
    print('不要再执行 fastboot -w 或 format userdata，否则会删除刚安装的 Ubuntu。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print('\n停止 / STOP:', error, file=sys.stderr)
        print('未自动重启。若已开始刷写，请保留 fastboot 界面，处理错误后重新完成刷写。', file=sys.stderr)
        sys.exit(1)
