"""`engine.build_stack` (and `verify`) put the files a folder adds into the index with a
fixed number of git processes per folder, whatever the file count.

It was one `hash-object` and one `update-index` per file: 775 files over 79 folders are
1550 processes and 775 rewrites of a 300,000-entry index, and on GitHub's Windows runner
`materialize` spent 261-388 s in "apply" (24 runs). Batched per folder: 253 s -> 27 s for
the added files, the same 79 layer trees.

Shown on a small repository instead of Firefox. Known-bad: the old per-file code gives the
same trees but its process count grows with the files (red on the count, not on the trees);
CRLF and binary bytes are stored verbatim, as `--stdin` did.

    python -m pytest tools/tests
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

GIT_ENV = {**engine.IDENTITY, "PATH": os.environ["PATH"]}
# one commit-tree, one write-tree, one apply, one hash-object, one update-index, and a spare
GIT_PER_FOLDER = 6
# rev-parse x2, log, read-tree before the folders
GIT_FIXED = 4


def run(cwd, *args, input_bytes=None):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=GIT_ENV,
                          input=input_bytes).stdout.decode().strip()


def content(folder: str, i: int) -> bytes:
    """Text, CRLF text, binary with NULs and a lone CR, and an empty file, in turn."""
    return [b"text %s %d\n" % (folder.encode(), i),
            b"crlf %d\r\nline\r\n" % i,
            b"\x00\x01\xff\r%d\x00" % i,
            b""][i % 4]


def make_world(tmp_path, per_folder: int):
    src = tmp_path / "firefox"
    src.mkdir()
    run(src, "init", "-q")
    run(src, "config", "core.autocrlf", "false")
    (src / "mozilla.txt").write_bytes(b"one\ntwo\n")
    run(src, "add", ".")
    run(src, "commit", "-qm", "upstream")
    run(src, "tag", "TAG")
    (src / "mozilla.txt").write_bytes(b"one\nhook();\ntwo\n")
    patch = subprocess.run(["git", "-C", str(src), "diff", "--binary", "--full-index"],
                           check=True, capture_output=True).stdout
    run(src, "checkout", "-q", "--", "mozilla.txt")

    series = tmp_path / "engine"
    folders = ["fingerprint/a", "network/b", "platform/c"]
    for n, folder in enumerate(folders):
        base = series / folder
        added = {}
        for i in range(per_folder):
            path = "dir%d/sub/Stealth%d.%s" % (n, i, "py" if i % 2 else "cpp")
            (base / "src" / Path(path).parent).mkdir(parents=True, exist_ok=True)
            (base / "src" / path).write_bytes(content(folder, i))
            added[path] = "100755" if i % 3 == 0 else "100644"
        if n == 0:  # the patch only in the first; the others have no hooks.patch
            (base / "hooks.patch").write_bytes(patch)
        (base / "MANIFEST.json").write_text(json.dumps({"modified": ["mozilla.txt"] if n == 0 else [],
                                                        "added": added}))
    (series / "SERIES").write_text("".join(f + "\n" for f in folders))
    return src, series, folders


def reference_trees(src: Path, series: Path, folders: list) -> list:
    """The layer trees by the former method: one hash-object --stdin and one
    update-index --cacheinfo per file."""
    import tempfile
    trees = []
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(GIT_ENV, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        subprocess.run(["git", "-C", str(src), "read-tree", "TAG"], check=True, env=env)
        for folder in folders:
            patch = series / folder / "hooks.patch"
            if patch.exists():
                subprocess.run(["git", "-C", str(src), "apply", "--cached", "--whitespace=nowarn", str(patch)],
                               check=True, env=env)
            manifest = json.loads((series / folder / "MANIFEST.json").read_text())
            for path, mode in manifest["added"].items():
                data = (series / folder / "src" / path).read_bytes()
                sha = subprocess.run(["git", "-C", str(src), "hash-object", "-w", "--stdin"], input=data,
                                     check=True, capture_output=True, env=env).stdout.decode().strip()
                subprocess.run(["git", "-C", str(src), "update-index", "--add", "--cacheinfo",
                                "%s,%s,%s" % (mode, sha, path)], check=True, env=env)
            trees.append(subprocess.run(["git", "-C", str(src), "write-tree"], check=True, capture_output=True,
                                        env=env).stdout.decode().strip())
    return trees


@pytest.fixture
def count_git(monkeypatch):
    calls = []
    real = subprocess.run

    def counting(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "git":
            calls.append(list(cmd))
        return real(cmd, *a, **kw)
    monkeypatch.setattr(subprocess, "run", counting)
    return calls


def test_the_layer_trees_are_those_of_the_per_file_method(tmp_path, monkeypatch):
    src, series, folders = make_world(tmp_path, per_folder=9)
    monkeypatch.setattr(engine, "ROOT", series)
    expected = reference_trees(src, series, folders)
    layers = engine.build_stack(src, "TAG")
    assert [t for _, _, t in layers[1:]] == expected
    # bytes verbatim, CRLF and NUL included
    last = layers[-1][1]
    for n, folder in enumerate(folders):
        for i in range(9):
            path = "dir%d/sub/Stealth%d.%s" % (n, i, "py" if i % 2 else "cpp")
            got = subprocess.run(["git", "-C", str(src), "show", "%s:%s" % (last, path)], check=True,
                                 capture_output=True).stdout
            assert got == content(folder, i), path
    assert "100755" in run(src, "ls-tree", last, "dir0/sub/Stealth0.cpp")


def test_the_git_processes_per_folder_do_not_grow_with_the_files(tmp_path, monkeypatch, count_git):
    counts = {}
    for n_files in (2, 40):
        world = tmp_path / ("w%d" % n_files)
        world.mkdir()
        src, series, folders = make_world(world, per_folder=n_files)
        monkeypatch.setattr(engine, "ROOT", series)
        count_git.clear()
        engine.build_stack(src, "TAG")
        counts[n_files] = len(count_git)
        assert len(count_git) <= GIT_FIXED + GIT_PER_FOLDER * len(folders), \
            "%d files: %d git processes" % (n_files, len(count_git))
    assert counts[2] == counts[40], counts


def test_verify_batches_the_same_way_and_accepts_the_stack(tmp_path, monkeypatch, count_git, capsys):
    src, series, folders = make_world(tmp_path, per_folder=30)
    monkeypatch.setattr(engine, "ROOT", series)
    layers = engine.build_stack(src, "TAG")
    run(src, "update-ref", "refs/heads/work", layers[-1][1])
    count_git.clear()
    assert engine.verify(src, "TAG", "work") == 0
    assert len(count_git) <= GIT_FIXED + GIT_PER_FOLDER * len(folders), len(count_git)
