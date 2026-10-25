#!/usr/bin/python3
"""Create the distributable ZIP, checking every member against SHA256SUMS."""
import hashlib
from pathlib import Path
import zipfile
from release_config import PACKAGE

package = PACKAGE
output = package.parent / (package.name + '.zip')
partial = output.with_name(output.name + '.partial')
assert not output.exists() and not partial.exists()
expected = dict((line[66:], line[:64]) for line in (package / 'SHA256SUMS').read_text().splitlines())
actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
assert set(expected) == actual
with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
    for path in sorted(p for p in package.rglob('*') if p.is_file()):
        assert not path.is_symlink()
        relative = path.relative_to(package).as_posix()
        print('Packing', relative, flush=True)
        entry = zipfile.ZipInfo.from_file(path, package.name + '/' + relative)
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry._compresslevel = 1
        digest = hashlib.sha256()
        with path.open('rb') as source, archive.open(entry, 'w', force_zip64=True) as target:
            for block in iter(lambda: source.read(4 * 1024 * 1024), b''):
                digest.update(block)
                target.write(block)
        if relative != 'SHA256SUMS':
            assert digest.hexdigest() == expected[relative], relative + ' changed during packaging'
with zipfile.ZipFile(partial) as archive:
    assert archive.testzip() is None
partial.rename(output)
digest = hashlib.sha256()
with output.open('rb') as stream:
    for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
        digest.update(block)
sidecar = output.with_name(output.name + '.sha256')
sidecar.write_text(digest.hexdigest() + '  ' + output.name + '\n')
print('Completed:', output, output.stat().st_size, 'bytes; SHA256', digest.hexdigest(), flush=True)
