#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD
# The fork's overlay: arm64/patches/*.patch, in order, on a materialized tree. Commits nothing.
#   bash arm64/apply.sh <tree>
set -euo pipefail
tree="${1:?usage: apply.sh <materialized tree>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
shopt -s nullglob
for p in "$here"/patches/*.patch; do
  echo "apply.sh: $(basename "$p")"
  git -C "$tree" apply --whitespace=nowarn "$p"
done
git -C "$tree" diff --stat
