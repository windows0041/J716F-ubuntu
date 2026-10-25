#!/bin/bash
# Build environment for the j716f Linux port.
#
# This host has no passwordless sudo and no distro-installed cross toolchain,
# so everything needed to build is vendored here as extracted .deb trees:
#
#   toolchain/cross-root/     aarch64-linux-gnu gcc 11.4 + binutils 2.38 + libgcc
#   toolchain/hosttools/root/ host flex 2.6.4, bison 3.8.2, m4 1.4.18,
#                             libssl-dev 3.0.2, libelf-dev 0.186, zlib1g-dev 1.2.11
#
# Versions matter: the newest pool packages need GLIBC_2.38 but this host has
# 2.35, so the glibc-2.34-compatible builds are pinned below.
#
# Usage:  source env.sh    (from this directory)

_j716f_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export J716F_CROSS="$_j716f_here/cross-root"
export J716F_HOSTTOOLS="$_j716f_here/hosttools/root"

export PATH="$J716F_CROSS/usr/bin:$J716F_HOSTTOOLS/usr/bin:$PATH"

# binutils (as/ld) needs its libopcodes/libbfd; hosttools need libsigsegv.
export LD_LIBRARY_PATH="$J716F_CROSS/usr/lib/x86_64-linux-gnu:$J716F_CROSS/usr/lib/gcc-cross/aarch64-linux-gnu/11:$J716F_HOSTTOOLS/usr/lib/x86_64-linux-gnu:$J716F_HOSTTOOLS/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# The vendored bison was built for /usr/share/bison, which does not exist here.
export BISON_PKGDATADIR="$J716F_HOSTTOOLS/usr/share/bison"
export BISON_PREFIX="$J716F_HOSTTOOLS/usr"
# bison shells out to m4; point it at the vendored one explicitly, because it
# does not always find it through PATH on this host.
export M4="$J716F_HOSTTOOLS/usr/bin/m4"

# Kernel builds look for headers via standard paths only when they are real
# system paths, so expose the vendored ones through the documented overrides.
# The multiarch subdir must come first: openssl's opensslconf.h lives in
# usr/include/x86_64-linux-gnu/openssl/ and is <openssl/opensslconf.h> when
# that directory is on the include path.
export HOSTCFLAGS="-I$J716F_HOSTTOOLS/usr/include/x86_64-linux-gnu -I$J716F_HOSTTOOLS/usr/include ${HOSTCFLAGS:-}"
export HOSTLDFLAGS="-L$J716F_HOSTTOOLS/usr/lib/x86_64-linux-gnu ${HOSTLDFLAGS:-}"
export CPATH="$J716F_HOSTTOOLS/usr/include/x86_64-linux-gnu:$J716F_HOSTTOOLS/usr/include${CPATH:+:$CPATH}"
export LIBRARY_PATH="$J716F_HOSTTOOLS/usr/lib/x86_64-linux-gnu${LIBRARY_PATH:+:$LIBRARY_PATH}"

j716f_check() {
	local ok=0
	for t in aarch64-linux-gnu-gcc aarch64-linux-gnu-ld flex bison m4; do
		if command -v "$t" >/dev/null 2>&1; then
			printf '  ok   %s\n' "$t"
		else
			printf '  FAIL %s\n' "$t"; ok=1
		fi
	done
	for h in "$J716F_HOSTTOOLS/usr/include/openssl/ssl.h" \
	         "$J716F_HOSTTOOLS/usr/include/libelf.h" \
	         "$J716F_HOSTTOOLS/usr/include/zlib.h"; do
		[ -f "$h" ] && printf '  ok   %s\n' "$(basename "$h")" || { printf '  FAIL %s\n' "$h"; ok=1; }
	done
	return $ok
}
