#!/usr/bin/env bash
# Prepare a node to run release.yml's build job, as root, on the image's Ubuntu 24.04,
# the same as GitHub's runners:
#
#     ssh ubuntu@node 'sudo -n bash -s' < scripts/ci/node_bootstrap.sh
#
# What a job on ubuntu-24.04 finds already installed, this installs: the apt packages
# from the closure resolved against THIS node's own image (scripts/ci/node_deps_resolve.sh
# on the GitHub runner, sent by latitude_node.py prepare into /opt/node-deps/debs before
# this runs), glslang and the rest by version and sha256, all checked by sha256. A user `runner` with
# home /home/runner, as on GitHub's runners, so the job's paths (HOME, ~/pgo,
# ~/.mozbuild) are the same; the runner itself in ~/actions-runner, jobs in ~/work,
# Python's in /opt/hostedtoolcache. Unlike GitHub's, this user has no sudo: what a job
# would install with it is installed here, and a job has no way to root.
#
# It registers nothing: scripts/ci/node_runner.sh starts the runner, with
# its configuration on stdin. It can run again on a prepared node.
#
# Everything it needs is checked at the end, as that user: a missing tool stops
# here, by name, not an hour into a build.
set -euo pipefail

# ONE bootstrap at a time on the node. A client that lost its ssh (exit 255) asks again while the first run, orphaned, still goes on: both would
# run apt and `ssh-keygen -A` under each other. The second waits for the first, then runs over a node that is prepared.
exec 9>/run/node_bootstrap.lock
flock -w 1500 9 || { echo "node_bootstrap: ERROR: another bootstrap on this node did not end in 1500 s" >&2; exit 1; }

# Every version in one place.
# GitHub's release files come through the API first, and the direct address second:
# on 2026-11-08 the direct one answered 504 for hours, and the API now and then; two
# candidates lost their node to it. The API's address of a file is never written
# here: it is derived at run time from the release's tag and the file's name
# (asset_api_url below), since an asset id is a number GitHub gives, not one to keep.
# glslang, Ubuntu 24.04's at a version of our own choosing (lavapipe's shaders need 12.2 or later): one fixed
# release asset of this repository, a tar of glslang-root/usr/local.
GLSLANG_VERSION=14.0.0
GLSLANG=glslang-14.0.0-5e10b724aba0
GLSLANG_SHA256=5e10b724aba0426efa763694675e1d4a39bab1fe4a99c9d1f2b17d0571712cbf
GLSLANG_WEB_URL="https://github.com/oss-invisible/firefox_antidetect_patch/releases/download/$GLSLANG/$GLSLANG.tar"
RUNNER_VERSION=2.338.2
RUNNER_FILE="actions-runner-linux-x64-$RUNNER_VERSION.tar.gz"
RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40
NODE_VERSION=22.23.4
NODE_SHA256=1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce
RUSTUP_VERSION=1.29.3
RUSTUP_SHA256=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55
# What apt installs, from the closure only (node_deps_resolve.sh reads this list).
PACKAGES=(
  # the job's steps; sudo is for this script's as_runner
  sudo git curl ca-certificates python3 python3-venv
  build-essential binutils util-linux make m4 pkg-config patch file
  tar gzip bzip2 xz-utils zstd zip unzip rsync procps psmisc
  # the win-x86_64 leg (extra_pkgs in scripts/ci/legs.py)
  # (libc6-i386: Mozilla's wine, which runs fxc.exe, opens /lib/ld-linux.so.2; the hosted image has it)
  msitools p7zip-full libc6-i386 lib32gcc-s1 lib32stdc++6
  # lavapipe (scripts/ci/lavapipe_build.py)
  cmake ninja-build bison flex patchelf
  # what the runner links against
  libicu74 libkrb5-3 liblttng-ust1t64 libssl3t64 zlib1g
  # what `mach package` starts: xpcshell loads a libxul linked against these
  libgtk-3-0t64 libasound2t64 libdbus-glib-1-2 libx11-xcb1 libxt6t64 libxtst6 libpci3
)

die() { echo "node_bootstrap: ERROR: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run it as root"
. /etc/os-release
[ "${VERSION_CODENAME:-}" = noble ] || die "written for Ubuntu 24.04 (noble), this is ${PRETTY_NAME:-unknown}"

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a LANG=C.UTF-8

# The API's address of one file of a release, from the release's tag and the file's name: one unauthenticated call (the node has no token), asked again by curl
# on a timeout or a 5xx. Nothing when the API does not answer or the release has no such file: fetch() then goes on with its second address.
asset_api_url() { # owner/repo release-tag file-name
  curl -fsSL --retry 5 --retry-delay 5 --connect-timeout 30 --max-time 120 -H "Accept: application/vnd.github+json" \
       "https://api.github.com/repos/$1/releases/tags/$2" 2>/dev/null \
    | python3 -c 'import json, sys
for asset in json.load(sys.stdin).get("assets", []):
    if asset.get("name") == sys.argv[1] and asset.get("url", "").startswith("https://api.github.com/repos/"):
        print(asset["url"])
        break' "$3" 2>/dev/null || true
}

fetch() { # url sha256 file [second-url]; an empty url is skipped (the API gave none)
  [ -f "$3" ] && echo "$2  $3" | sha256sum -c --quiet - 2>/dev/null && return 0
  # Both of GitHub's addresses gave 504 for minutes on 2026-11-08, never both for
  # long: three rounds over the API's address, then the direct one. The API answers a
  # release asset with its bytes only when asked for them. The sha256 decides.
  local round url
  for round in 1 2 3; do
    for url in ${1:+"$1"} ${4:+"$4"}; do
      if curl -fsSL --retry 5 --retry-delay 5 --connect-timeout 30 --max-time 900 \
           -H "Accept: application/octet-stream" -o "$3" "$url" \
         && echo "$2  $3" | sha256sum -c --quiet -; then
        return 0
      fi
      echo "node_bootstrap: $url failed or did not match its sha256 (round $round)" >&2
    done
    sleep "${FETCH_PAUSE:-30}"
  done
  die "${1:-$4} does not match its sha256, from any address, in 3 rounds"
}

# apt from the closure, silent while it works and whole when it does not. Its last line alone ("E: Unable to correct problems, you have
# held broken packages", runs 44137637832 and 44139666991) names no package and no version. On a failure: apt's whole answer, the
# solver's own account of the same request, and for every package apt named the version installed on the node against the one the
# closure holds; then what apt did on this node before this script, and apt's exit code, with its E: lines last.
apt_install() {
  local log rc=0 names
  log="$(mktemp)"
  apt-get install -y -q --no-install-recommends "$@" > "$log" 2>&1 || rc=$?
  if [ "$rc" = 0 ]; then
    rm -f "$log"
    return 0
  fi
  set +e +o pipefail
  {
    echo "node_bootstrap: apt-get install exited $rc; its whole answer:"
    cat "$log"
    echo "node_bootstrap: the solver on the same request (apt-get -s, Debug::pkgProblemResolver):"
    apt-get install -s -q --no-install-recommends -o Debug::pkgProblemResolver=yes "$@" 2>&1 | tail -n 200
    names="$( { grep -oE '^ +[a-z0-9][a-z0-9.+:-]* :' "$log" | sed -E 's/^ +//; s/ :$//'
                grep -oE '(Pre-?Depends|Depends|Breaks|Conflicts): [a-z0-9][a-z0-9.+:-]*' "$log" | sed -E 's/^[^:]+: //'; } | sort -u | tr '\n' ' ')"
    echo "node_bootstrap: the packages apt named, installed on the node (dpkg) and in the closure (apt-cache policy): ${names:-none}"
    if [ -n "$names" ]; then
      # shellcheck disable=SC2086 # one word per package
      dpkg-query -W -f='${binary:Package} ${Version} ${db:Status-Abbrev}\n' $names 2>&1
      # shellcheck disable=SC2086
      apt-cache policy $names 2>&1
    fi
    echo "node_bootstrap: held: $(apt-mark showhold 2>&1 | tr '\n' ' ')"
    echo "node_bootstrap: the image: ${PRETTY_NAME:-?}, kernel $(uname -r), $(cat /etc/cloud/build.info 2>/dev/null | tr '\n' ' ')"
    echo "node_bootstrap: apt on this node before this script (unattended-upgrades $(systemctl is-active unattended-upgrades.service 2>&1)," \
         "apt-daily-upgrade $(systemctl is-active apt-daily-upgrade.service 2>&1)), the end of /var/log/apt/history.log:"
    tail -n 40 /var/log/apt/history.log 2>&1
    echo "node_bootstrap: ERROR: apt-get install exited $rc:"
    grep -E '^(E|W): ' "$log"
  } >&2
  exit "$rc"
}

# The closure latitude_node.py prepare sent: the .debs this node's own image needs for PACKAGES, resolved on the GitHub runner against this
# node's dpkg database at its start (scripts/ci/node_deps_resolve.sh), with their index. Every exact-version edge (libpam-systemd on systemd,
# python3.12-venv on python3.12, libc6-dev on libc6) is met by the versions of that same moment, so nothing is pinned and nothing goes down.
# A fixed archive resolved as if nothing were installed failed on the provider's newer image, which held systemd 255.4-1ubuntu8.19 while
# the archive's libpam-systemd asked for 8.18 exactly.
DEPS=/opt/node-deps
echo "== apt, from the closure resolved against this node's own image"
# apt has no network timeout of its own (run 41248997155 waited 5h40 on a mirror).
# A machine just installed may be running its own daily apt: wait for its lock.
printf '%s\n' 'Acquire::http::Timeout "60";' 'Acquire::https::Timeout "60";' 'Acquire::Retries "5";' 'DPkg::Lock::Timeout "600";' \
  > /etc/apt/apt.conf.d/80-ci-network
[ -f "$DEPS/debs/Packages" ] || die "no closure of packages in $DEPS/debs: latitude_node.py prepare sends it before this script"
# The closure's index and nothing else: no source on the network, so no mirror can be
# down, slow or a day ahead. trusted=yes because the closure comes from this job's own resolver, over ssh.
echo "deb [trusted=yes] file:$DEPS/debs ./" > /etc/apt/sources.list
rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources
apt-get update -qq -o APT::Update::Error-Mode=any
apt_install "${PACKAGES[@]}"

echo "== the user"
id runner >/dev/null 2>&1 || useradd --create-home --home-dir /home/runner --uid 1001 --shell /bin/bash runner
rm -f /etc/sudoers.d/runner
# sudo looks the machine's name up on every call, and warns when it cannot.
grep -q "[[:space:]]$(hostname)\$" /etc/hosts || echo "127.0.0.1 $(hostname)" >> /etc/hosts
install -d -o runner -g runner /home/runner/work /opt/hostedtoolcache

as_runner() { sudo -n -u runner -H env -i HOME=/home/runner PATH=/home/runner/.cargo/bin:/opt/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 "$@"; }

echo "== Node.js $NODE_VERSION"
if [ "$(/opt/node/bin/node --version 2>/dev/null)" != "v$NODE_VERSION" ]; then
  fetch "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz" "$NODE_SHA256" /tmp/node.tar.xz
  rm -rf /opt/node && mkdir -p /opt/node
  tar -xJf /tmp/node.tar.xz --strip-components=1 -C /opt/node
  rm -f /tmp/node.tar.xz
fi

echo "== rustup $RUSTUP_VERSION (the job installs the retail's Rust with it)"
if [ "$(as_runner rustup --version 2>/dev/null | awk 'NR==1{print $2}')" != "$RUSTUP_VERSION" ]; then
  fetch "https://static.rust-lang.org/rustup/archive/$RUSTUP_VERSION/x86_64-unknown-linux-gnu/rustup-init" \
    "$RUSTUP_SHA256" /tmp/rustup-init
  chmod 755 /tmp/rustup-init
  as_runner /tmp/rustup-init -y --no-modify-path --default-toolchain none --profile minimal >/dev/null
  rm -f /tmp/rustup-init
fi

echo "== glslang $GLSLANG_VERSION, in /usr/local/bin"
GLSLANG_URL="${GLSLANG_URL:-$(asset_api_url oss-invisible/firefox_antidetect_patch "$GLSLANG" "$GLSLANG.tar")}"
fetch "$GLSLANG_URL" "$GLSLANG_SHA256" /tmp/glslang.tar "$GLSLANG_WEB_URL"
rm -rf "$DEPS/glslang" && mkdir -p "$DEPS/glslang"
tar -xf /tmp/glslang.tar -C "$DEPS/glslang"
rm -f /tmp/glslang.tar
cp -a "$DEPS/glslang/glslang-root/usr/local/." /usr/local/

echo "== actions-runner $RUNNER_VERSION"
R=/home/runner/actions-runner
if [ "$(as_runner "$R/bin/Runner.Listener" --version 2>/dev/null)" != "$RUNNER_VERSION" ]; then
  fetch "$(asset_api_url actions/runner "v$RUNNER_VERSION" "$RUNNER_FILE")" \
    "$RUNNER_SHA256" /tmp/actions-runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/$RUNNER_FILE"
  rm -rf "$R" && install -d -o runner -g runner "$R"
  as_runner tar -xzf /tmp/actions-runner.tar.gz -C "$R"
  rm -f /tmp/actions-runner.tar.gz
fi
# What config.sh would write, and a JIT runner never runs config.sh: the
# environment every job starts from, and where setup-python keeps its Python.
as_runner sh -c "cat > $R/.env" <<'EOF'
LANG=C.UTF-8
AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache
RUNNER_TOOL_CACHE=/opt/hostedtoolcache
EOF
as_runner sh -c "echo /home/runner/.cargo/bin:/opt/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin > $R/.path"

echo "== everything the job counts on, as the user that runs it"
missing=()
for tool in git curl python3 gcc g++ make strip tar xz zstd zip unzip 7z msiextract cmake ninja \
            glslangValidator bison flex patchelf node rustup; do
  as_runner sh -c "command -v $tool" >/dev/null || missing+=("$tool")
done
! as_runner sudo -n true 2>/dev/null || missing+=("a user without sudo")
[ "$(as_runner sh -c 'echo $HOME')" = /home/runner ] || missing+=("HOME=/home/runner")
[ -w /home/runner/work ] && as_runner test -w /home/runner/work || missing+=("a writable /home/runner/work")
as_runner test -w /opt/hostedtoolcache || missing+=("a writable tool cache")
[ "$(as_runner "$R/bin/Runner.Listener" --version 2>/dev/null)" = "$RUNNER_VERSION" ] \
  || missing+=("a runner that starts ($(as_runner "$R/bin/Runner.Listener" --version 2>&1 | head -1))")
[ "$(as_runner node --version)" = "v$NODE_VERSION" ] || missing+=("Node.js $NODE_VERSION")
/usr/local/bin/glslangValidator --version | grep -q ":$GLSLANG_VERSION\$" || missing+=("glslang $GLSLANG_VERSION")
# What node_runner.sh runs each leg in, as root.
for tool in systemd-run unshare mount runuser useradd; do
  command -v "$tool" >/dev/null || missing+=("$tool")
done
[ -d /sys/fs/cgroup ] && grep -qw memory /sys/fs/cgroup/cgroup.controllers || missing+=("cgroup v2 with memory")
[ "${#missing[@]}" = 0 ] || die "missing: ${missing[*]}"

echo "== a host key of this node's own"
# latitude_node.py pins this one, read from this session, for every later connection.
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A >/dev/null
kill -HUP "$(pgrep -o -x sshd)"
host_key="$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
served=""
for _ in $(seq 30); do
  # awk, not cut: ssh-keyscan's "# host banner" line goes to stdout in newer OpenSSH.
  served="$(ssh-keyscan -T 2 -t ed25519 127.0.0.1 2>/dev/null | awk '$1 !~ /^#/ {print $2, $3}' || true)"
  [ "$served" != "$host_key" ] || break
  sleep 1
done
[ "$served" = "$host_key" ] || die "sshd does not serve the host key just made"
echo "node_bootstrap: host key: $host_key"
echo "node_bootstrap: ready (runner $RUNNER_VERSION, node $NODE_VERSION, rustup $RUSTUP_VERSION, glslang $GLSLANG_VERSION, apt from the closure)"
