#!/usr/bin/python3
"""Assemble the completed clean fastboot bundle; no device operations."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from release_config import ROOT, WORK, PACKAGE, RELEASE



def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def main():
    rootfs = json.loads((WORK / 'rootfs-manifest.json').read_text())
    audit = json.loads((WORK / 'image-audit.json').read_text())
    assert audit['status'].endswith('passed') and rootfs['sparse_roundtrip_identical']
    for name, expected in [('dtbo.img', 'b96ff6ba263897fa79634de420fa3019eb2599789f2349a3d7cfd75d88e29602'),
                           ('vbmeta.img', 'efe01355cf52527745917d2ce9a786302335e7a88841c302607872ab66492910')]:
        assert sha(WORK / name) == expected
        shutil.copyfile(WORK / name, PACKAGE / 'images' / name)
    for source, target in [('flash.py', 'flash.py'), ('刷机教程.md', '刷机教程.md')]:
        shutil.copyfile(ROOT / 'tools/release' / source, PACKAGE / target)
    (PACKAGE / 'flash-linux.sh').write_text('#!/bin/sh\nset -eu\ncd -- "$(dirname -- "$0")"\nexec python3 ./flash.py "$@"\n')
    (PACKAGE / 'flash-linux.sh').chmod(0o755)
    (PACKAGE / 'flash.py').chmod(0o755)
    (PACKAGE / 'flash-windows.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\npy -3 "%~dp0flash.py" %*\r\nif errorlevel 1 echo Please read the error above. Python 3 is required.\r\npause\r\n')
    (PACKAGE / 'README.txt').write_text('请先阅读 刷机教程.md。\n机型：TB-J716F 128GB；Bootloader 必须已解锁。\n原厂布局：清空 super 和 userdata，首次引导备份本机 GPT、合并分区并自动重启，再扩容 Ubuntu。\n已合并布局：清空并重装 userdata，不重复调整布局。\n两种布局均覆盖 A/B 两槽启动及配套镜像，不保留 Android 或个人数据。\n当前平板在制作过程中没有被擦除或重新刷写。\n初始登录 ubuntu / ubuntu，登录后运行 passwd。\n新安装包已完成离线校验，尚未进行实机全新刷写演练。\n', encoding='utf-8')
    images = {name: {'bytes': (PACKAGE / 'images' / name).stat().st_size,
                     'sha256': sha(PACKAGE / 'images' / name)}
              for name in ('boot.img', 'dtbo.img', 'vbmeta.img', 'userdata.img')}
    plan = {'boot_a': 'boot.img', 'boot_b': 'boot.img', 'recovery_a': 'boot.img', 'recovery_b': 'boot.img',
            'dtbo_a': 'dtbo.img', 'dtbo_b': 'dtbo.img', 'vbmeta_a': 'vbmeta.img', 'vbmeta_b': 'vbmeta.img'}
    manifest = {'release': RELEASE, 'device': 'TB-J716F-128GB',
                'kernel': '6.15.11 #530', 'distribution': 'Ubuntu 22.04 arm64',
                'images': images, 'partition_images': plan, 'rootfs_expanded_bytes': rootfs['expanded_bytes'],
                'rootfs_expanded_sha256': rootfs['expanded_sha256'], 'sparse_roundtrip_identical': True,
                'current_tablet_erased_or_flashed': False, 'actual_clean_install_tested': False,
                'initial_user': 'ubuntu', 'initial_password': 'ubuntu',
                'personal_profiles_included': False, 'filesystem_layout_changed_by_installer': True,
                'pulseaudio_enabled_for_fresh_accounts': True, 'speaker_test_app_included': False,
                'r1_install_reported_successful_by_user': True,
                'r2_live_audio_confirmed_by_user': True,
                'fingerprint_private_libraries_included': True,
                'live_fprintd_device_enumeration_confirmed': True,
                'r3_live_fingerprint_confirmed_by_user': True,
                'merge_super_userdata': True, 'rootfs_targets': {'stock': 'super', 'merged': 'userdata'},
                'stock_userdata_bytes': 116237611008, 'merged_userdata_bytes': 124827545600,
                'reclaimed_super_bytes': 8589934592,
                'gpt_strategy': 'derive from target GPT; remove entry 17 and change only entry 18 start, preserving GUIDs and unrelated bytes',
                'gpt_backup_on_target': '/var/lib/j716f-first-boot/gpt-before',
                'first_boot': ['stock layout only: save target GPT, offline merge, verify and reboot',
                               'grow ext4 within merged userdata', 'generate machine ID and SSH keys',
                               'empty fingerprint store', 'clear known legacy boot requests preserving misc remainder',
                               'mark current A/B slot successful after display manager starts']}
    (PACKAGE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    checks = PACKAGE / 'checks'
    checks.mkdir(exist_ok=True)
    sources = PACKAGE / 'sources'
    sources.mkdir(exist_ok=True)
    for name in ('merge-root.c', 'build-merge-helper.py', 'pack-clean-boot.py', 'first-boot.py',
                 'mark-boot-success.py', 'fix-audio-r2.py', 'fix-fingerprint-r3.py', 'release_config.py'):
        shutil.copyfile(ROOT / 'tools/release' / name, sources / name)
    for source, target in [(WORK / 'image-audit.json', 'image-audit.json'),
                           (WORK / 'rootfs-manifest.json', 'rootfs-manifest.json'),
                           (WORK / 'merge-audit.json', 'merge-audit.json'),
                           (PACKAGE / 'images/boot.manifest.json', 'boot-manifest.json')]:
        if source.exists():
            shutil.copyfile(source, checks / target)
        else:
            assert (checks / target).exists()
    (PACKAGE / 'images/boot.manifest.json').unlink(missing_ok=True)
    files = sorted(p for p in PACKAGE.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (PACKAGE / 'SHA256SUMS').write_text(''.join(sha(path) + '  ' + path.relative_to(PACKAGE).as_posix() + '\n' for path in files))
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
