#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD
# Runs lvp_probe (math.comp and the scene) on a lavapipe library and hashes what it wrote.
#   bash arm64/harness/lavapipe/run.sh <libvulkan_lvp.so> <out dir>
#   bash arm64/harness/lavapipe/run.sh --compare <x86_64 out dir> <aarch64 out dir>
# Needs cc, glslangValidator and the Vulkan headers. <out dir>/probe.txt: the machine, the
# library and the shaders' sha256. <out dir>/hashes.txt: sha256 of each output.
set -euo pipefail

# --compare: exit 1 unless both ran the same SPIR-V and every output byte is equal, but for
# float results that are each architecture's default NaN (x86 0xffc00000, AArch64 0x7fc00000):
# those are counted and printed, never failing. Prints how many 32-bit words differ, per
# result column for compute.bin.
if [ "${1:-}" = --compare ]; then
  x86="${2:?usage: run.sh --compare <x86_64 out> <aarch64 out>}"; arm="${3:?}"
  fail=0
  if ! diff <(grep '\.spv$' "$x86/probe.txt") <(grep '\.spv$' "$arm/probe.txt") >/dev/null; then
    echo "DIFFERS  the SPIR-V the two legs ran"; fail=1
  fi
  for f in compute.bin scene-f32.bin scene-u8.bin scene-u32.bin; do
    if cmp -s "$x86/$f" "$arm/$f"; then echo "equal    $f ($(wc -c < "$x86/$f") bytes)"; continue; fi
    python3 -I - "$x86/$f" "$arm/$f" <<'PY' || fail=1
import struct, sys
a, b = (open(p, "rb").read() for p in sys.argv[1:3])
name = sys.argv[1].rsplit("/", 1)[-1]
if len(a) != len(b):
    sys.exit(print("DIFFERS  %s: %d bytes vs %d" % (name, len(a), len(b))))
wa, wb = (struct.unpack("<%dI" % (len(x) // 4), x) for x in (a, b))
# math.comp's columns that hold integers, not float bits.
INT_COLUMNS = {38, 39, 40, 45, 46, 48}
def is_float(i):
    return name == "scene-f32.bin" or (name == "compute.bin" and i % 64 not in INT_COLUMNS)
diff = [i for i, (x, y) in enumerate(zip(wa, wb)) if x != y]
nans = [i for i in diff if is_float(i) and (wa[i], wb[i]) == (0xffc00000, 0x7fc00000)]
bad = [i for i in diff if i not in set(nans)]
def columns(words):
    cols = {}
    for i in words:
        cols[i % 64] = cols.get(i % 64, 0) + 1
    return ", ".join("%d: %d" % kv for kv in sorted(cols.items()))
if nans:
    print("NaN bits %s: %d words are x86's default NaN ffc00000 and AArch64's 7fc00000%s"
          % (name, len(nans), " (columns %s)" % columns(nans) if name == "compute.bin" else ""))
    for i in nans[:2]:
        print("         word %d: x86 %08x aarch64 %08x" % (i, wa[i], wb[i]))
if not bad:
    sys.exit(print("equal    %s (%d bytes) but for those NaN bits" % (name, len(a))))
print("DIFFERS  %s: %d of %d words" % (name, len(bad), len(wa)))
if name == "compute.bin":
    print("         by result column (math.comp order): %s" % columns(bad))
for i in bad[:5]:
    print("         word %d: x86 %08x aarch64 %08x" % (i, wa[i], wb[i]))
sys.exit(1)
PY
  done
  exit "$fail"
fi

lib="$(cd "$(dirname "${1:?usage: run.sh <libvulkan_lvp.so> <out>}")" && pwd)/$(basename "$1")"
mkdir -p "${2:?usage: run.sh <libvulkan_lvp.so> <out>}"
out="$(cd "$2" && pwd)"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
obj="$(mktemp -d)"
trap 'rm -rf "$obj"' EXIT
for s in math.comp scene.vert scene.frag; do
  glslangValidator -V --quiet -o "$obj/$s.spv" "$here/$s"
done
cc -O1 -o "$obj/lvp_probe" "$here/lvp_probe.c" -ldl
"$obj/lvp_probe" "$lib" "$obj" "$out" | tee "$obj/run.txt"
{
  echo "machine $(uname -m)"
  glslangValidator --version | sed -n 1p
  echo "library $(sha256sum "$lib" | cut -d' ' -f1)"
  cat "$obj/run.txt"
  (cd "$obj" && sha256sum -- *.spv)
} > "$out/probe.txt"
(cd "$out" && sha256sum -- *.bin) > "$out/hashes.txt"
cat "$out/hashes.txt"
