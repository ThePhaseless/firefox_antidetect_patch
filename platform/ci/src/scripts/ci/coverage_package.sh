#!/usr/bin/env bash
# Package the coverage build of diagnostics.yml, on the node, after the build and the gtests' build:
#
#     bash scripts/ci/coverage_package.sh        # from the source tree; the series is checked out in ./.series
#
# Three archives in out/, named so that none can be taken for a release's asset (no version, no `stealth`, no `asset-` prefix, and a
# diagnostics run publishes nothing):
#   cov-linux-x86_64.tar.gz        the browser, as `make stage-package` stages it (dist/firefox), symlinks dereferenced, WebGPU's Vulkan driver
#                                  and WebGL's GL beside it as package_linux.sh puts them; no strip, no seal, no release gate
#   cov-gtest-linux-x86_64.tar.gz  dist/bin with the gtests' libxul, and _tests/gtest: what scripts/ci/gtest_run.py runs (release.yml's gtest-bin.tar)
#   cov-notes-linux-x86_64.tar.gz  what the map needs of the build (scripts/ci/gcov_export.py bundle): the .gcno of the objects that carry a file
#                                  of the series, those files' sources, the build's llvm-cov, the source directory
set -euo pipefail
OBJ=obj-rel
STAGING=staging-cov
SERIES="${SERIES_DIR:-.series}"

bash scripts/ci/stage_package.sh
[ -x "$OBJ/dist/firefox/firefox" ] || { echo "ERROR: stage-package did not produce $OBJ/dist/firefox/firefox"; exit 1; }
rm -rf "$STAGING" notes out
mkdir -p "$STAGING" out
cp -aL "$OBJ/dist/firefox/." "$STAGING/"
[ "$(find "$STAGING" -type l | wc -l)" -eq 0 ] || { echo "ERROR: symlinks remain after cp -aL"; exit 1; }
# The engine looks for its own Vulkan and GL next to libxul, and answers WebGPU null and WebGL no context without them, never with the host's.
[ -f "$OBJ/dist/bin/lavapipe/libvulkan_lvp.so" ] || { echo "ERROR: no lavapipe in $OBJ/dist/bin"; exit 1; }
mkdir -p "$STAGING/lavapipe" "$STAGING/llvmpipe"
cp -a "$OBJ/dist/bin/lavapipe/libvulkan_lvp.so" "$OBJ/dist/bin/lavapipe/VERSION.json" "$STAGING/lavapipe/"
for f in libEGL.so.1 libGLESv2.so.2; do
  [ -f "$OBJ/dist/bin/llvmpipe/$f" ] || { echo "ERROR: no llvmpipe/$f in $OBJ/dist/bin"; exit 1; }
done
cp -a "$OBJ/dist/bin/llvmpipe/." "$STAGING/llvmpipe/"
tar --owner=0 --group=0 --numeric-owner -czf out/cov-linux-x86_64.tar.gz -C "$STAGING" .

# The gtests' libxul sits in dist/bin/gtest; the directory mach runs them from is _tests/gtest.
[ -f "$OBJ/dist/bin/gtest/libxul.so" ] || { echo "ERROR: no gtest libxul in $OBJ/dist/bin/gtest: recurse_gtest did not build it"; exit 1; }
mkdir -p "$OBJ/_tests/gtest"
tar -chzf out/cov-gtest-linux-x86_64.tar.gz -C "$OBJ/dist" bin -C ../_tests gtest

RUST_TOOLS=()
if [ "${RUST_COVERAGE:-}" = true ]; then
  RUST_BIN="$(rustc --print sysroot)/lib/rustlib/x86_64-unknown-linux-gnu/bin"
  [ -x "$RUST_BIN/llvm-cov" ] && [ -x "$RUST_BIN/llvm-profdata" ] || { echo "ERROR: no llvm-tools of the rustc in $RUST_BIN"; exit 1; }
  RUST_TOOLS=(--rust-tools "$RUST_BIN")
fi
python3 scripts/ci/gcov_export.py bundle --series-root "$SERIES" --objdir "$OBJ" --topsrcdir "$PWD" --out notes ${RUST_TOOLS[@]+"${RUST_TOOLS[@]}"}
git rev-parse HEAD > notes/source-commit.txt
git -C "$SERIES" rev-parse HEAD > notes/series-commit.txt
tar -czf out/cov-notes-linux-x86_64.tar.gz -C notes .
ls -la out/
