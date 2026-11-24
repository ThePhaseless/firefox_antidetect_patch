"""A Mozilla file carried ahead of the tag, as the diff of one commit of Mozilla's own repository.

The category `backport` used to be only vendored code (third_party/rust, Cargo.lock). A
fix Mozilla has already landed in its own source (bug 2077661: fontconfig answers a
collection with another face than the one asked for) is the same thing: not ours, no budget,
and honest only while it is that commit's diff byte for byte. The folder's BACKPORT.json
names the commit and the sha256 of the diff, the diff is beside it, and a tag that already
holds the change fails the check. These tests build that folder from the real diff of the
commit (tools/tests/data) and break one thing at a time.

    python -m pytest tools/tests
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

FOLDER = "platform/backports/fontconfig-face-index"
PATH = "gfx/2d/ScaledFontFontconfig.cpp"
COMMIT = "53aca1462bf3b9965d1eae9a2bf3b74767e6c6da"
STORED = "upstream-53aca1462bf3.diff"
UPSTREAM_DIFF = (Path(__file__).parent / "data" / "mozilla-53aca1462bf3-ScaledFontFontconfig.diff").read_bytes()


def _sha(diff: bytes, path: str = PATH) -> str:
    """The sha256 BACKPORT.json declares: the hunks of the file's diff, each opened by a bare @@
    (written here on its own, so the test does not take its expectation from the code it tests)."""
    lines = diff.split(b"\n")
    start = next(i for i, l in enumerate(lines) if l.startswith(b"diff --git a/" + path.encode() + b" "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(b"diff --git ")), len(lines))
    hunks = [b"@@" if l.startswith(b"@@") else l
             for l in lines[start:end] if not l.startswith((b"diff ", b"index ", b"--- ", b"+++ "))]
    while hunks and hunks[-1] == b"":
        hunks.pop()
    return hashlib.sha256(b"\n".join(hunks) + b"\n").hexdigest()


def _ours(diff: bytes) -> bytes:
    """The same diff as made in our tree: another blob on the index line, another offset."""
    diff = re.sub(rb"^index [0-9a-f]+\.\.[0-9a-f]+", b"index " + b"0" * 40 + b".." + b"1" * 40, diff, flags=re.M)
    return re.sub(rb"^@@ -\d+,(\d+) \+\d+,(\d+) @@[^\n]*", rb"@@ -600,\1 +600,\2 @@", diff, flags=re.M)


def _record(diff=UPSTREAM_DIFF, path=PATH, **changes):
    record = {"upstream": "https://github.com/mozilla-firefox/firefox", "commit": COMMIT, "bug": 2077661,
              "date": "2026-10-13", "files": {path: {"diff": STORED, "sha256": _sha(diff, path)}},
              "drop_when": "the Mozilla tag has bug 2077661"}
    record.update(changes)
    return {k: v for k, v in record.items() if v is not None}


def _folder(tmp_path, monkeypatch, patch=None, record=None, stored=UPSTREAM_DIFF):
    d = tmp_path / FOLDER
    d.mkdir(parents=True)
    (d / "hooks.patch").write_bytes(_ours(UPSTREAM_DIFF) if patch is None else patch)
    if stored is not None:
        (d / STORED).write_bytes(stored)
    if record is not False:
        (d / engine.BACKPORT).write_text(json.dumps(_record() if record is None else record), encoding="utf-8")
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    return d


def _problems(tmp_path, monkeypatch, **kw):
    d = _folder(tmp_path, monkeypatch, **kw)
    return engine.backport_problems(FOLDER, {PATH}, d / "hooks.patch")


def test_the_commit_of_mozilla_as_its_own_diff_breaks_no_rule(tmp_path, monkeypatch):
    assert _problems(tmp_path, monkeypatch) == []


def test_a_diff_touched_by_one_line_is_refused(tmp_path, monkeypatch):
    touched = _ours(UPSTREAM_DIFF).replace(b"+    int index = 0;", b"+    int index = 1;", 1)
    assert touched != _ours(UPSTREAM_DIFF)
    found = _problems(tmp_path, monkeypatch, patch=touched)
    assert any("differently from commit 53aca1462bf3" in p for p in found), found


def test_a_context_line_touched_is_refused_too(tmp_path, monkeypatch):
    touched = _ours(UPSTREAM_DIFF).replace(b"   char* file = nullptr;", b"   char *file = nullptr;", 1)
    assert touched != _ours(UPSTREAM_DIFF)
    found = _problems(tmp_path, monkeypatch, patch=touched)
    assert any("differently from commit" in p for p in found), found


def test_the_stored_diff_must_be_the_one_the_record_declares(tmp_path, monkeypatch):
    stored = UPSTREAM_DIFF.replace(b"+    int index = 0;", b"+    int index = 1;", 1)
    found = _problems(tmp_path, monkeypatch, patch=_ours(stored), stored=stored)
    assert any("sha256 differs" in p for p in found), found


def test_the_stored_diff_must_be_in_the_folder(tmp_path, monkeypatch):
    found = _problems(tmp_path, monkeypatch, stored=None)
    assert any("is not in the folder" in p for p in found), found


def test_a_record_without_the_commit_is_refused(tmp_path, monkeypatch):
    found = _problems(tmp_path, monkeypatch, record=_record(commit=None))
    assert any("lacks commit" in p for p in found), found


def test_a_short_sha_is_not_the_commit(tmp_path, monkeypatch):
    found = _problems(tmp_path, monkeypatch, record=_record(commit="53aca1462bf3"))
    assert any("not a full sha" in p for p in found), found


def test_another_upstream_cannot_carry_a_file_outside_vendored_code(tmp_path, monkeypatch):
    found = _problems(tmp_path, monkeypatch, record=_record(upstream="https://github.com/gfx-rs/wgpu"))
    assert any("is not mozilla-firefox/firefox" in p for p in found), found
    assert any("outside vendored code" in p for p in found), found


def test_a_mozilla_file_as_a_backport_with_no_record_is_refused(tmp_path, monkeypatch):
    """Today's case: a file outside vendored code marked as a backport, in a folder that is not one."""
    found = _problems(tmp_path, monkeypatch, record=False)
    assert any("outside vendored code" in p for p in found), found
    assert any("no BACKPORT.json" in p for p in found), found


def test_a_mozilla_commit_outside_platform_backports_is_refused(tmp_path, monkeypatch):
    """The same commit, the same record, in a folder of our own logic: refused, it has its own folder."""
    elsewhere = "fingerprint/fonts/font-list"
    d = tmp_path / elsewhere
    d.mkdir(parents=True)
    (d / "hooks.patch").write_bytes(_ours(UPSTREAM_DIFF))
    (d / STORED).write_bytes(UPSTREAM_DIFF)
    (d / engine.BACKPORT).write_text(json.dumps(_record()), encoding="utf-8")
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    found = engine.backport_problems(elsewhere, {PATH}, d / "hooks.patch")
    assert any("outside platform/backports/" in p for p in found), found


def test_the_vendored_backport_of_wgpu_still_passes():
    folder = "fingerprint/webgpu/external-texture-vulkan"
    manifest = json.loads((engine.ROOT / folder / "MANIFEST.json").read_text(encoding="utf-8"))
    files = {r["file"] for r in manifest["inventory"] if r["category"] == "backport"}
    assert files and all(f.startswith(engine.VENDORED) for f in files)
    assert engine.backport_problems(folder, files, engine.ROOT / folder / "hooks.patch") == []


def test_a_file_section_ends_at_the_next_file_and_drops_the_mail_trailer():
    two = b"diff --git a/a b/a\n@@ -1 +1 @@\n-x\n+y\ndiff --git a/b b/b\n@@ -1 +1 @@\n-p\n+q\n-- \n2.50.0\n"
    assert engine.file_section(two, "a") == b"diff --git a/a b/a\n@@ -1 +1 @@\n-x\n+y\n"
    assert engine.file_section(two, "b") == b"diff --git a/b b/b\n@@ -1 +1 @@\n-p\n+q\n"
    assert engine.file_section(two, "c") == b""


# The tag that already holds the commit. A synthetic file and its diff, made by git, so the
# test needs no Firefox: the backport applies backwards on exactly that tag.
SYNTH = "gfx/2d/Synthetic.cpp"
BEFORE = b"int f() {\n  int a = 1;\n  return a;\n}\n"
AFTER = b"int f() {\n  int a = 2;\n  return a;\n}\n"


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false",
                           "-C", str(cwd), *args], check=True, capture_output=True).stdout


def _tree(tmp_path, name, content):
    repo = tmp_path / name
    (repo / SYNTH).parent.mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / SYNTH).write_bytes(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tag")
    _git(repo, "tag", "T")
    return repo


def _synthetic_folder(tmp_path, monkeypatch):
    base = _tree(tmp_path, "base", BEFORE)
    (base / SYNTH).write_bytes(AFTER)
    diff = _git(base, "diff", "--full-index")
    (base / SYNTH).write_bytes(BEFORE)
    d = tmp_path / "series" / FOLDER
    d.mkdir(parents=True)
    (d / "hooks.patch").write_bytes(diff)
    (d / STORED).write_bytes(diff)
    (d / "MANIFEST.json").write_text("{}", encoding="utf-8")
    (d / engine.BACKPORT).write_text(json.dumps(_record(diff=diff, path=SYNTH)), encoding="utf-8")
    monkeypatch.setattr(engine, "ROOT", tmp_path / "series")
    return diff


def test_a_tag_without_the_commit_is_fine(tmp_path, monkeypatch):
    _synthetic_folder(tmp_path, monkeypatch)
    assert engine.backport_problems(FOLDER, {SYNTH}, tmp_path / "series" / FOLDER / "hooks.patch") == []
    assert engine.backport_in_tag_problems(tmp_path / "base", "T") == []


def test_a_tag_that_already_holds_the_commit_fails(tmp_path, monkeypatch):
    _synthetic_folder(tmp_path, monkeypatch)
    newer = _tree(tmp_path, "newer", AFTER)
    found = engine.backport_in_tag_problems(newer, "T")
    assert len(found) == 1 and "already contains the backport" in found[0] and SYNTH in found[0], found


def test_check_against_a_tag_that_holds_the_commit_is_red(tmp_path, monkeypatch, capsys):
    _synthetic_folder(tmp_path, monkeypatch)
    newer = _tree(tmp_path, "newer", AFTER)
    monkeypatch.setattr(engine, "problems", lambda: [])
    monkeypatch.setattr(engine, "series_folders", lambda: [])
    monkeypatch.setattr(engine, "contract_problems", lambda against_main=False: ([], 0, 0))     # this test's root is no series
    assert engine.check(newer, "T") == 1
    assert "already contains the backport" in capsys.readouterr().out
    assert engine.check(tmp_path / "base", "T") == 0
