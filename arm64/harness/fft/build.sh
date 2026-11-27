#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD
# Builds the tree's ffvpx av_tx (media/ffvpx/libavutil) with Mozilla's config headers, as
# Firefox builds it on this machine's architecture, and runs fft_probe on it.
#   bash arm64/harness/fft/build.sh <materialized tree> <out dir> [--c-only]
#   bash arm64/harness/fft/build.sh --compare <x86_64 out dir> <aarch64 out dir>
# <out dir>/probe.txt: CPU flags and the transform trees. <out dir>/hashes.txt: sha256 of
# the output bits per variant, direction, length and signal. --c-only runs only the
# variant with every CPU flag forced off (av_force_cpu_flags(0)).
set -euo pipefail

# --compare: exit 1 unless the aarch64 build's outputs equal the x86 asm's, and unless the
# x86 result is the same for every codelet tier an AVX2+FMA3 CPU can select.
if [ "${1:-}" = --compare ]; then
  x86="${2:?usage: build.sh --compare <x86_64 out> <aarch64 out>}"; arm="${3:?}"
  pick() { sed -n "s#  \./$2/#  #p" "$1/hashes.txt"; }
  same() { # label, dir a, variant a, dir b, variant b -> prints the verdict, returns 1 if not equal
    local a b n
    a="$(pick "$2" "$3")"; b="$(pick "$4" "$5")"
    if [ -z "$a" ] || [ -z "$b" ]; then echo "MISSING  $1"; return 1; fi
    n="$(diff <(echo "$a") <(echo "$b") | grep -c '^<' || true)"
    if [ "$n" = 0 ]; then echo "equal    $1"; else echo "DIFFERS  $1: $n of $(echo "$a" | wc -l) outputs"; return 1; fi
  }
  fail=0
  same "aarch64 host vs x86_64 host" "$arm" host "$x86" host || fail=1
  same "x86_64 host vs x86_64 avx2 (fast gather)" "$x86" host "$x86" avx2 || fail=1
  same "x86_64 avx2 vs x86_64 avx2 with SLOW_GATHER" "$x86" avx2 "$x86" avx2-slow-gather || fail=1
  same "x86_64 avx2 vs x86_64 fma3 only" "$x86" avx2 "$x86" fma3 || fail=1
  echo "-- recorded, never failing:"
  same "x86_64 avx (no FMA) vs x86_64 avx2" "$x86" avx "$x86" avx2 || true
  same "x86_64 C only vs x86_64 host" "$x86" c "$x86" host || true
  same "aarch64 C only vs x86_64 C only" "$arm" c "$x86" c || true
  same "aarch64 C only vs x86_64 host" "$arm" c "$x86" host || true
  same "aarch64 C only vs aarch64 host" "$arm" c "$arm" host || true
  exit "$fail"
fi

tree="$(cd "${1:?usage: build.sh <tree> <out> [--c-only]}" && pwd)"
mkdir -p "${2:?usage: build.sh <tree> <out> [--c-only]}"
out="$(cd "$2" && pwd)"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ff="$tree/media/ffvpx"
av="$ff/libavutil"
CC="${CC:-$(command -v clang || command -v gcc)}"
obj="$(mktemp -d)"
trap 'rm -rf "$obj"' EXIT

# Mozilla compiles every C file with -ffp-contract=off (FP_CONTRACT in
# python/mozbuild/mozbuild/frontend/context.py, for every moz.build directory).
cflags=(-O2 -ffp-contract=off -ffunction-sections -fdata-sections -w -DHAVE_AV_CONFIG_H -DXP_UNIX
  -DHAVE_64BIT_BUILD -I"$ff" -include "$ff/libavutil_visibility.h")
srcs=("$av"/{tx,tx_float,tx_double,tx_int32,cpu,mem,bprint,mathematics}.c)
case "$(uname -m)" in
  x86_64)
    srcs+=("$av"/x86/{cpu,tx_float_init}.c)
    for a in cpuid tx_float; do
      nasm -D__x86_64__ -DPIC -DELF -Pconfig_unix64.asm -f elf64 -I"$ff/" -I"$av/x86/" \
        -o "$obj/$a.asm.o" "$av/x86/$a.asm"
    done ;;
  aarch64)
    # Whatever the tree's aarch64/moz.build compiles, so the harness tests what Firefox ships.
    while read -r s; do srcs+=("$av/aarch64/$s"); done \
      < <(grep -oE "'[A-Za-z0-9_]+\.(c|S)'" "$av/aarch64/moz.build" | tr -d "'") ;;
  *) echo "build.sh: unsupported machine $(uname -m)" >&2; exit 2 ;;
esac
i=0
for s in "${srcs[@]}"; do
  i=$((i + 1))
  case "$s" in
    *.S) "$CC" -DPIC -DHAVE_AV_CONFIG_H -DXP_UNIX -DHAVE_64BIT_BUILD -I"$ff" -c "$s" -o "$obj/$i.o" ;;
    *) "$CC" "${cflags[@]}" -DPIC -c "$s" -o "$obj/$i.o" ;;
  esac
done
"$CC" "${cflags[@]}" "$here/fft_probe.c" "$obj"/*.o -Wl,--gc-sections -lm -lpthread -o "$obj/fft_probe"

{ echo "machine $(uname -m)"; "$CC" --version | sed -n 1p; ldd --version | sed -n 1p; } > "$out/probe.txt"
variants=()
[ "${3:-}" = --c-only ] && variants=(c)
"$obj/fft_probe" "$out" "${variants[@]}" >> "$out/probe.txt"
(cd "$out" && find . -name '*.bin' | sort | xargs sha256sum) > "$out/hashes.txt"
echo "build.sh: $(wc -l < "$out/hashes.txt") outputs hashed in $out/hashes.txt"
