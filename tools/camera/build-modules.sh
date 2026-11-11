#!/bin/sh
# Build add-on sensors against the exact configured and built J716F kernel.
set -eu
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 /absolute/kernel-build-tree /absolute/new-output-dir [kernel-source-tree]" >&2
    exit 2
fi
kernel=$(realpath "$1")
output=$(realpath -m "$2")
srctree=$(realpath "${3:-$kernel}")
source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -f "$kernel/Module.symvers"
test -f "$kernel/arch/arm64/boot/Image"
if [ -e "$output" ]; then
    echo "Use a new output directory; existing files will not be overwritten." >&2
    exit 2
fi
if grep -q '^CONFIG_V4L2_CCI_I2C=' "$kernel/.config"; then
    echo "This add-on build expects the base kernel without V4L2_CCI_I2C." >&2
    exit 2
fi
printf '%s  %s\n' \
    bb47cdfa4200e59c6247d95531484ec43832bb056e144e33c8fd107df5b7dee3 "$srctree/drivers/media/i2c/ov13b10.c" \
    eec4bcf6b4706132d101076b913399e3efb9ae597864769aee028abb86826622 "$srctree/drivers/media/v4l2-core/v4l2-cci.c" | sha256sum -c -
mkdir -p "$output"
cp "$source"/modules/*.c "$source/modules/Makefile" "$output/"
cp "$srctree/drivers/media/i2c/ov13b10.c" "$output/"
cp "$srctree/drivers/media/v4l2-core/v4l2-cci.c" "$output/"
patch --batch -d "$output" -p1 < "$source/ov13b10-of.patch"
case $(uname -m) in
    aarch64) cross=${CROSS_COMPILE-} ;;
    *) cross=${CROSS_COMPILE-aarch64-linux-gnu-} ;;
esac
make -C "$kernel" M="$output" ARCH=arm64 CROSS_COMPILE="$cross" -j"${JOBS:-4}" modules
python3 - "$kernel" "$output" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys

kernel, output = map(Path, sys.argv[1:])
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
manifest = {
    'kernel_image_sha256': digest(kernel / 'arch/arm64/boot/Image'),
    'kernel_release': (kernel / 'include/config/kernel.release').read_text().strip(),
    'modules': {},
}
for name in ('v4l2-cci', 'gc5035', 's5k4h7', 'ov13b10'):
    module = output / (name + '.ko')
    manifest['modules'][module.name] = digest(module)
    assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).split()[0] == manifest['kernel_release']
(output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
PY
