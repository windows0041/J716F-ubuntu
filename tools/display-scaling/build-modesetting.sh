#!/bin/bash
# Build only the seven-file DDX module against the exact installed Xorg SDK.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
task_sysroot="$repo/build/display-scaling/xorg-sysroot"
task_source=${1:-"$repo/build/display-scaling/modesetting-linear-src"}
task_build=${2:-"$repo/build/display-scaling/modesetting-build"}
task_pkgconfig="$repo/build/fingerprint-userspace/host-tools/usr/bin/pkg-config"
task_cc="$repo/toolchain/cross-root/usr/bin/aarch64-linux-gnu-gcc"
export PKG_CONFIG_SYSROOT_DIR="$task_sysroot"
export PKG_CONFIG_LIBDIR="$task_sysroot/usr/lib/aarch64-linux-gnu/pkgconfig:$task_sysroot/usr/share/pkgconfig"
read -ra task_cflags <<< "$("$task_pkgconfig" --cflags xorg-server libdrm gbm libudev pixman-1)"
read -ra task_libs <<< "$("$task_pkgconfig" --libs libdrm gbm libudev pixman-1)"
mkdir -p "$task_build"
cat > "$task_build/dix-config.h" <<'EOF'
/* Linux poll is the only internal configure feature used by this DDX. */
#ifndef _DIX_CONFIG_H_
#define _DIX_CONFIG_H_
#include <xorg-server.h>
#define HAVE_POLL 1
#define HAVE_ASPRINTF 1
#define HAVE_VASPRINTF 1
#endif
EOF
cat > "$task_build/xorg-config.h" <<'EOF'
/* DDX-only build; public feature/ABI definitions come from the exact SDK. */
#include <xorg-server.h>
#define WITH_LIBDRM 1
#define CONFIG_UDEV_KMS 1
EOF
task_objects=()
for part in dri2 driver drmmode_display dumb_bo pageflip present vblank; do
  "$task_cc" --sysroot="$task_sysroot" -fPIC -O2 -g -Wall \
    -D_FORTIFY_SOURCE=2 -fstack-protector-strong \
    -Werror=implicit-function-declaration -Werror=incompatible-pointer-types \
    -DHAVE_DIX_CONFIG_H -include "$task_build/dix-config.h" \
    -D_GNU_SOURCE -DGLAMOR_HAS_GBM -DGLAMOR_HAS_GBM_LINEAR \
    -DGBM_BO_WITH_MODIFIERS -DCONFIG_UDEV_KMS \
    -include "$task_sysroot/usr/include/xorg/xorg-server.h" \
    -I"$task_build" -I"$task_source" "${task_cflags[@]}" \
    -c "$task_source/$part.c" -o "$task_build/$part.o"
  task_objects+=("$task_build/$part.o")
done
"$task_cc" --sysroot="$task_sysroot" -shared -Wl,-z,relro,-z,now \
  -Wl,-rpath-link,"$task_sysroot/usr/lib/aarch64-linux-gnu" \
  -Wl,-rpath-link,"$task_sysroot/lib/aarch64-linux-gnu" \
  "${task_objects[@]}" "${task_libs[@]}" \
  -o "$task_build/modesetting_drv.so"
