#!/usr/bin/env python3
"""Save source changes against the exact upstream tarball; never edit the build tree."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, default=ROOT / 'kernel/dl/linux-6.15.11.tar.xz')
    p.add_argument('--tree', type=Path, default=ROOT / 'build/fingerprint-port/linux-6.15.11')
    a = p.parse_args()
    target = ROOT / 'patches/kernel'
    target.mkdir(parents=True, exist_ok=True)
    output = target / 'linux-6.15.11-j716f-530.patch'
    baseline, changed, added, deleted = set(), [], [], []
    chunks = []

    def difference(name, before, after):
        if before == after:
            return False
        assert b'\0' not in before + after, 'Changed binary source requires manual review: ' + name
        old = before.decode('utf-8', errors='surrogateescape').splitlines(keepends=True)
        new = after.decode('utf-8', errors='surrogateescape').splitlines(keepends=True)
        # Linux sources normally end in newline; refuse an ambiguous patch.
        assert all(not x or x[-1].endswith('\n') for x in (old, new)), name
        chunks.append(f'diff --git a/{name} b/{name}\n')
        chunks.extend(difflib.unified_diff(old, new, 'a/' + name if before else '/dev/null',
                                          'b/' + name if after else '/dev/null'))
        return True

    with tarfile.open(a.archive, 'r|xz') as tar:
        for member in tar:
            pieces = Path(member.name).parts
            if len(pieces) < 2:
                continue
            name = Path(*pieces[1:]).as_posix()
            baseline.add(name)
            if not member.isfile():
                continue
            old = tar.extractfile(member).read()
            file = a.tree / name
            new = file.read_bytes() if file.is_file() else b''
            if difference(name, old, new):
                (changed if new else deleted).append(name)
    allowed = {'.c', '.h', '.S', '.dts', '.dtsi', '.yaml', '.yml', '.rst', '.lds', '.lds.S'}
    candidates = []
    for base, dirs, files in os.walk(a.tree):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and
                         str((Path(base) / d).relative_to(a.tree)) not in
                         ('include/generated', 'arch/arm64/include/generated'))
        for filename in sorted(files):
            f = Path(base) / filename
            name = f.relative_to(a.tree).as_posix()
            if name in baseline or f.is_symlink() or filename.startswith('.'):
                continue
            if f.suffix not in allowed and filename not in ('Makefile', 'Kconfig'):
                continue
            if filename.endswith(('.mod.c', '.tab.c', '.tab.h', '-tab.c', '-tab.h', '.lex.c', '-lex.c')):
                continue
            candidates.append(name)
    # Kbuild's own ignore files distinguish generated C/header/assembler files
    # from new handwritten drivers. Use temporary Git metadata, never the source
    # tree's index or the project's future index.
    with tempfile.TemporaryDirectory(prefix='j716f-kernel-ignore-') as temp:
        subprocess.run(['git', 'init', '--bare', '--quiet', temp], check=True)
        result = subprocess.run(['git', '--git-dir=' + temp, '--work-tree=' + str(a.tree.resolve()),
                                 'check-ignore', '--no-index', '--stdin', '-z'],
                                input=b''.join(x.encode() + b'\0' for x in candidates), capture_output=True,
                                cwd=a.tree)
        assert result.returncode in (0, 1), result.stderr.decode()
        ignored = {x.decode() for x in result.stdout.split(b'\0') if x}
    for name in candidates:
        if name not in ignored and difference(name, b'', (a.tree / name).read_bytes()):
            added.append(name)
    output.write_text(''.join(chunks), encoding='utf-8', errors='surrogateescape')
    config = ROOT / 'configs/kernel/j716f-6.15.11.config'
    config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(a.tree / '.config', config)
    report = {'upstream_version': '6.15.11', 'upstream_archive_sha256': digest(a.archive),
              'working_kernel': '#530', 'patch': output.relative_to(ROOT).as_posix(),
              'patch_sha256': digest(output), 'config_sha256': digest(config),
              'changed_source_files': changed, 'added_source_files': added, 'deleted_source_files': deleted,
              'excluded_generated_sources': sorted(ignored),
              'compiled_objects_included': False}
    (target / 'snapshot.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
