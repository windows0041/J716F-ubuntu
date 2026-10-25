#!/bin/bash
# Requires the extracted toolchain/sysroot and Meson source already in build/.
set -euo pipefail
fp_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$fp_root"
source toolchain/env.sh
unset CPATH LIBRARY_PATH HOSTCFLAGS HOSTLDFLAGS
export PATH="$fp_root/build/fingerprint-userspace/native-bin:$fp_root/build/fingerprint-userspace/host-tools/usr/bin:$PATH"
python3 build/fingerprint-userspace/meson/meson.py setup \
  build/fingerprint-userspace/libfprint-build tools/libfprint-goodix-qsee \
  --cross-file build/fingerprint-userspace/cross-aarch64.ini \
  --prefix=/opt/j716f-fingerprint --libdir=lib/aarch64-linux-gnu \
  -Ddrivers=goodixj716f -Dintrospection=false -Ddoc=false \
  -Dinstalled-tests=false -Dudev_rules=disabled -Dudev_hwdb=disabled \
  -Dlibrary-only=true
ninja -C build/fingerprint-userspace/libfprint-build
# Historical one-device template adoption is not part of a clean build.
