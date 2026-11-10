#!/bin/bash
# Build the experimental upstream port. This never accesses the tablet.
set -euo pipefail
j716f_project=$(cd -- "$(dirname -- "$0")/../.." && pwd)
j716f_tree=${1:-"$j716f_project/build/mainline/linux-7.4-rc2"}
j716f_cross=${CROSS_COMPILE:-aarch64-linux-gnu-}
test -f "$j716f_tree/.config"
command -v "${j716f_cross}gcc" >/dev/null
export KBUILD_BUILD_USER=${KBUILD_BUILD_USER:-j716f}
export KBUILD_BUILD_HOST=${KBUILD_BUILD_HOST:-wsl-mainline}
export KBUILD_BUILD_VERSION=${KBUILD_BUILD_VERSION:-1}
make -C "$j716f_tree" ARCH=arm64 CROSS_COMPILE="$j716f_cross" olddefconfig
make -C "$j716f_tree" ARCH=arm64 CROSS_COMPILE="$j716f_cross" \
  -j"${JOBS:-6}" Image modules qcom/sm8250-lenovo-j716f.dtb
