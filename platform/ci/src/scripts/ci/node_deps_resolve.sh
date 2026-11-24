#!/usr/bin/env bash
# Resolve the node's apt packages against the node's OWN image, on the GitHub runner, with nothing installed:
#
#     bash scripts/ci/node_deps_resolve.sh DPKG_STATUS OUT_DIR
#
# DPKG_STATUS is the node's /var/lib/dpkg/status as `latitude_node.py up` read it at the node's start; OUT_DIR gets every .deb apt would
# have to install on that image for node_bootstrap.sh's PACKAGES, an index apt reads from disk (Packages) and a MANIFEST. release.yml's node
# job keeps OUT_DIR in the cache under a key made of the same status, the same list and this script, and `latitude_node.py prepare` sends
# it to the node, which installs from it and from nothing else.
#
# Why: a closure resolved once, as if nothing were installed, holds the versions of its day: libpam-systemd asks for systemd (= 8.18)
# exactly, the provider's newer image has systemd 8.19 installed, and apt could not install the chain libgtk-3-0t64 -> libgtk-3-common ->
# dconf-gsettings-backend -> dconf-service -> dbus-user-session -> libpam-systemd. Resolved against the image's own database, every exact-version
# edge (that one, python3.12-venv on python3.12, perl on perl-base, lib32gcc-s1 on gcc-14-base, libc6-dev and libc6-i386 on libc6) meets the
# versions the image has or the ones that upgrade them, from one archive at one moment.
#
# apt runs as whoever runs this, on private directories: its own sources (Ubuntu's archive: noble, noble-updates, noble-security), its own
# lists and cache, the node's status file as the installed state, no lock. Nothing in /etc or /var is read or written, so no root.
#
# The list is read from node_bootstrap.sh: one place for every package. Environment, for a test or another mirror:
#   NODE_DEPS_ARCHIVE         the archive (default http://archive.ubuntu.com/ubuntu; a file: URL works)
#   NODE_DEPS_SOURCE_OPTIONS  the options of each source line (default signed-by=<Ubuntu's keyring>)
#   NODE_DEPS_BOOT            the file with the PACKAGES=( ... ) array (default node_bootstrap.sh next to this script)
#   NODE_DEPS_TRIES           tries of `apt-get update` (default 5, a pause of 20 s between them)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT="${NODE_DEPS_BOOT:-$HERE/node_bootstrap.sh}"
ARCHIVE="${NODE_DEPS_ARCHIVE:-http://archive.ubuntu.com/ubuntu}"
SOURCE_OPTIONS="${NODE_DEPS_SOURCE_OPTIONS:-signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg}"
TRIES="${NODE_DEPS_TRIES:-5}"

die() { echo "node_deps_resolve: ERROR: $*" >&2; exit 1; }
[ "$#" = 2 ] || die "usage: node_deps_resolve.sh DPKG_STATUS OUT_DIR"
STATUS="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT="$2"
[ -s "$STATUS" ] || die "no package state of the node in $1"
[ -f "$BOOT" ] || die "no $BOOT"
case "$SOURCE_OPTIONS" in
  signed-by=*) [ -f "${SOURCE_OPTIONS#signed-by=}" ] || die "no keyring ${SOURCE_OPTIONS#signed-by=}: Ubuntu's archive cannot be checked" ;;
esac

# The PACKAGES=( ... ) array, comments dropped.
mapfile -t PACKAGES < <(sed -n '/^PACKAGES=(/,/^)/p' "$BOOT" | sed '1d;$d' | sed 's/#.*//' | tr -s ' \t' '\n' | sed '/^$/d')
[ "${#PACKAGES[@]}" -gt 0 ] || die "could not read the package list from $BOOT"
echo "== ${#PACKAGES[@]} packages from $ARCHIVE, against the node's $(grep -c '^Package: ' "$STATUS") installed packages"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Absolute: apt reads a relative cache folder against its own Dir::Cache.
mkdir -p "$OUT"
DEBS="$(cd "$OUT" && pwd)"
mkdir -p "$DEBS/partial" "$WORK/lists" "$WORK/cache" "$WORK/sources.list.d" "$WORK/preferences.d"
: > "$WORK/preferences"
for pocket in noble noble-updates noble-security; do
  echo "deb [$SOURCE_OPTIONS] $ARCHIVE $pocket main restricted universe multiverse"
done > "$WORK/sources.list"

export LANG=C.UTF-8
APT=(apt-get -q
  -o Debug::NoLocking=1
  -o Dir::State::status="$STATUS" -o Dir::State::lists="$WORK/lists" -o Dir::State::extended_states="$WORK/extended_states"
  -o Dir::Cache="$WORK/cache" -o Dir::Cache::archives="$DEBS" -o Dir::Cache::pkgcache= -o Dir::Cache::srcpkgcache=
  -o Dir::Etc::sourcelist="$WORK/sources.list" -o Dir::Etc::sourceparts="$WORK/sources.list.d"
  -o Dir::Etc::preferences="$WORK/preferences" -o Dir::Etc::preferencesparts="$WORK/preferences.d"
  -o APT::Sandbox::User=root -o Acquire::Languages=none -o Acquire::Retries=5
  -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60)

for try in $(seq "$TRIES"); do
  "${APT[@]}" -o APT::Update::Error-Mode=any update && break
  [ "$try" != "$TRIES" ] || die "the indexes of $ARCHIVE did not download in $TRIES tries"
  echo "   the indexes of $ARCHIVE failed (try $try), again in 20 s"; sleep 20
done

echo "== every .deb the list needs on the node's image"
START="$(date +%s)"
# apt's account of a refusal (the packages with unmet dependencies) is on its stdout: the log is shown whole when it fails.
"${APT[@]}" install -y --download-only --no-install-recommends "${PACKAGES[@]}" > "$WORK/install.log" 2>&1 \
  || { cat "$WORK/install.log" >&2; die "apt could not resolve the list against the node's image"; }
rm -rf "$DEBS/partial" "$DEBS/lock"
shopt -s nullglob
FILES=("$DEBS"/*.deb)
echo "   ${#FILES[@]} files, $(du -sm "$DEBS" | cut -f1) MB, downloaded in $(( $(date +%s) - START )) s"

echo "== the index apt reads from disk"
if [ "${#FILES[@]}" = 0 ]; then
  : > "$DEBS/Packages"
elif command -v dpkg-scanpackages >/dev/null; then
  (cd "$DEBS" && dpkg-scanpackages --multiversion . /dev/null > Packages)
elif command -v apt-ftparchive >/dev/null; then
  (cd "$DEBS" && apt-ftparchive packages . > Packages)
else
  die "neither dpkg-scanpackages nor apt-ftparchive is here to index the .debs"
fi
[ "${#FILES[@]}" = 0 ] || [ -s "$DEBS/Packages" ] || die "the index of the .debs came out empty"
echo "   entries: $(grep -c '^Package: ' "$DEBS/Packages" || true)"

{ echo "resolved $(date -u +%FT%TZ)"; echo "archive $ARCHIVE"; echo "status $(sha256sum "$STATUS" | cut -d' ' -f1)"
  echo "packages ${PACKAGES[*]}"; echo "debs:"
  sed -n 's/^Package: //p; s/^Version: //p' "$DEBS/Packages" | paste -d' ' - - ; } > "$DEBS/MANIFEST"
echo "node_deps_resolve: $DEBS, ${#FILES[@]} files"
