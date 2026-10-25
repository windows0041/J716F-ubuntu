#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
task_sysroot="$repo/build/fingerprint-userspace/sysroot"
task_pkgconfig="$repo/build/fingerprint-userspace/host-tools/usr/bin/pkg-config"
task_cc="$repo/toolchain/cross-root/usr/bin/aarch64-linux-gnu-gcc"
export PKG_CONFIG_SYSROOT_DIR="$task_sysroot"
export PKG_CONFIG_LIBDIR="$task_sysroot/usr/lib/aarch64-linux-gnu/pkgconfig:$task_sysroot/usr/share/pkgconfig"
read -ra task_cflags <<< "$("$task_pkgconfig" --cflags gio-2.0)"
read -ra task_libs <<< "$("$task_pkgconfig" --libs gio-2.0)"
mkdir -p "$repo/build/display-scaling"
"$task_cc" --sysroot="$task_sysroot" -shared -fPIC -O2 \
  -Wall -Wextra -Werror -Wl,-z,relro,-z,now \
  -Wl,-rpath-link,"$task_sysroot/usr/lib/aarch64-linux-gnu" \
  -Wl,-rpath-link,"$task_sysroot/lib/aarch64-linux-gnu" \
  "${task_cflags[@]}" "$repo/tools/display-scaling/limited-scales.c" \
  "${task_libs[@]}" -ldl -lm -o "$repo/build/display-scaling/limited-scales.so"
