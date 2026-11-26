"""The one sccache the candidates compile through, built from its pinned commit
and the patches in scripts/ci/sccache, never downloaded.

    python3 scripts/ci sccache-build --tag v0.18.0 --patches scripts/ci/sccache --out DIR

Prints the binary's path. A binary already in DIR (the workflow caches it by
tag, patches and this script) is used as it is.

The source is fetched by the 40-hex commit written below, never by the tag: a
tag is a name the repository's owner can move, a commit is its content (ci-03:
every third-party download is decided by a hash pinned in our repository). The
fetch names the commit and the checkout is refused unless HEAD is that commit,
and `cargo build --locked` then reads the crates the pinned Cargo.lock names, by
their checksums.

Why it is built: 0.18.0 names the file of a Rust `-C profile-use` among the
compile's OUTPUTS, so every cache hit wrote the 127 MB PGO profile back,
identical, with a new mtime. Cargo then found every crate that had read it
older than its input and the symbols step rebuilt gkrust and relinked xul
(input watch of run 40630019710: ~/pgo/merged.profdata moved two minutes into
the build, under sccache-served rustc). The patch makes the profile what it
is, an input; it reaches the cache key through rustc's dep-info as before.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

URL = "https://github.com/mozilla/sccache.git"
# The commit each tag names (v0.18.0 is an annotated tag: object e969b1c00e64..., which points at this commit). A tag not here is refused.
COMMITS = {"v0.18.0": "01c35e69b97f516c2ebfbdb418b5cd6277bde280"}


def binary_name(platform: str = sys.platform) -> str:
    return "sccache.exe" if platform == "win32" else "sccache"


def build(tag: str, patches: Path, out: Path, run=subprocess.run) -> Path:
    exe = out / binary_name()
    if exe.is_file():
        return exe
    commit = COMMITS.get(tag)
    if commit is None:
        raise ValueError("sccache %s has no commit pinned in scripts/ci/sccache_build.py: pin its 40-hex commit before building it" % tag)
    series = sorted(patches.glob("*.patch"))
    if not series:
        raise ValueError("no patches in %s: build the upstream release instead of this" % patches)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "sccache"
        # The patches are LF; a Windows runner's git converts a checkout to CRLF
        # unless told not to, and then none of them applies.
        src.mkdir()
        git = ["git", "-c", "core.autocrlf=false", "-C", str(src)]
        run(git + ["init", "--quiet"], check=True)
        run(git + ["fetch", "--quiet", "--depth", "1", URL, commit], check=True)
        run(git + ["checkout", "--quiet", "FETCH_HEAD"], check=True)
        head = run(git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        if head != commit:
            raise RuntimeError("sccache checkout is %s, not the pinned %s (%s)" % (head, commit, tag))
        for patch in series:
            # --check first: a patch that no longer applies is a refusal, never
            # a binary built without it.
            run(["git", "-C", str(src), "apply", "--check", str(patch.resolve())], check=True)
            run(["git", "-C", str(src), "apply", str(patch.resolve())], check=True)
        env = dict(os.environ, CARGO_TARGET_DIR=str(src / "target"))
        env.pop("RUSTC_WRAPPER", None)
        # The local disk cache is all the candidates use (SCCACHE_DIR).
        run(["cargo", "build", "--release", "--locked", "--no-default-features",
             "--manifest-path", str(src / "Cargo.toml")], check=True, env=env)
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "target" / "release" / binary_name(), exe)
    return exe
