#!/usr/bin/env python3
"""Record upstream pins and local changes without adding nested Git repositories."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ('libfprint-goodix-qsee', 'tools/libfprint-goodix-qsee', 'COPYING'),
    ('qsee-supplicant', 'tools/qsee-supplicant', 'LICENSE'),
    ('goodix-fp-spi-linux', 'tools/goodix-fp-spi-linux', 'LICENSE'),
]


def git(folder, *args):
    return subprocess.check_output(['git', '-C', str(folder), *args])


def main():
    output = ROOT / 'patches/userspace'
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for name, local, license_file in SOURCES:
        folder = ROOT / local
        url = git(folder, 'config', '--get', 'remote.origin.url').decode().strip()
        parsed = urlsplit(url)
        assert parsed.scheme == 'https' and parsed.hostname == 'github.com'
        url = urlunsplit(('https', 'github.com', parsed.path, '', ''))
        commit = git(folder, 'rev-parse', 'HEAD').decode().strip()
        patch = git(folder, 'diff', '--no-ext-diff', '--binary', 'HEAD', '--')
        additions = git(folder, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
        names = []
        for raw in additions:
            if not raw:
                continue
            relative = raw.decode()
            assert Path(relative).suffix in ('.c', '.h', '.md', '.rst', '.build', '.txt'), relative
            result = subprocess.run(['git', 'diff', '--no-index', '--', '/dev/null', relative],
                                    cwd=folder, capture_output=True)
            assert result.returncode in (0, 1), result.stderr.decode()
            patch += result.stdout
            names.append(relative)
        record = {'name': name, 'url': url, 'commit': commit, 'source_directory': local,
                  'new_source_files': names, 'license_copy': 'LICENSES/' + name + '.txt'}
        if patch:
            path = output / (name + '.patch')
            path.write_bytes(patch)
            record.update(patch=path.relative_to(ROOT).as_posix(), patch_sha256=hashlib.sha256(patch).hexdigest())
        shutil.copyfile(folder / license_file, ROOT / record['license_copy'])
        records.append(record)
    (ROOT / 'docs/UPSTREAMS.json').write_text(json.dumps(records, indent=2) + '\n')
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    main()
