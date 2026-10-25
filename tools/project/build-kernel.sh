#!/bin/bash
# Explicit developer action; repository organization does not invoke this.
set -euo pipefail
j716f_project=$(cd -- "$(dirname -- "$0")/../.." && pwd)
j716f_tree=${1:-"$j716f_project/build/kernel-6.15.11-source"}
j716f_cross=${CROSS_COMPILE:-aarch64-linux-gnu-}
test -f "$j716f_tree/.config"
command -v "${j716f_cross}gcc" >/dev/null
export KBUILD_BUILD_USER=${KBUILD_BUILD_USER:-j716f}
export KBUILD_BUILD_HOST=${KBUILD_BUILD_HOST:-builder}
export KBUILD_BUILD_VERSION=${KBUILD_BUILD_VERSION:-530}
make -C "$j716f_tree" ARCH=arm64 CROSS_COMPILE="$j716f_cross" olddefconfig
make -C "$j716f_tree" ARCH=arm64 CROSS_COMPILE="$j716f_cross" -j"${JOBS:-$(nproc)}" Image dtbs
