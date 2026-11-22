"""The package manifest A/B (scripts/ci/ab_package.py) against the cases it exists for, on tiny archives made here: a tar.gz and a zip, each with a nested omni.ja.

    python -m pytest scripts/ci/test_ab_package.py

Run by scripts/ci/test_ci.py through cases(), like the other modules of this folder.
"""
import contextlib
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ab_package  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ELF = b"\x7fELF" + b"\x02\x01\x01" + b"\0" * 40
PE = b"MZ" + b"\x90\0\x03\0" + b"\0" * 40
JA_FILES = {"modules/juggler/Helper.js": b"helper v1\n", "modules/Other.sys.mjs": b"other v1\n", "chrome/a.css": b"a{}\n"}


def make_ja(members, optimized=False):
    """A zip of {name: bytes}; optimized=True is Mozilla's layout: the central directory first, offsets from the start of the file, the end record last."""
    names = list(members)
    cd_len = sum(46 + len(n.encode()) for n in names)
    locals_, cd, offset = b"", b"", cd_len if optimized else 0
    for name in names:
        packer = zlib.compressobj(6, zlib.DEFLATED, -15)
        body = packer.compress(members[name]) + packer.flush()
        nb = name.encode()
        crc = zlib.crc32(members[name])
        local = struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, 0, 8, 0, 0x21, crc, len(body), len(members[name]), len(nb), 0) + nb + body
        cd += struct.pack("<4s6H3L5H2L", b"PK\x01\x02", 20, 20, 0, 8, 0, 0x21, crc, len(body), len(members[name]), len(nb), 0, 0, 0, 0, 0, offset) + nb
        locals_ += local
        offset += len(local)
    if optimized:
        return cd + locals_ + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, len(names), len(names), len(cd), 0, 0)
    return locals_ + cd + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, len(names), len(names), len(cd), len(locals_), 0)


def make_tgz(path, files):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def make_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def package(ja=None, **changes):
    """The files of a tiny Linux package; a change is {name: bytes} to set, None to remove."""
    files = {
        "firefox": ELF + b"v1",
        "libxul.so": ELF + b"xul1",
        "application.ini": b"[App]\nBuildID=1\n",
        "defaults/pref/channel-prefs.js": b'pref("app.update.channel", "release");\n',
        "omni.ja": make_ja(JA_FILES, optimized=True),
    }
    if ja is not None:
        files["omni.ja"] = make_ja(ja, optimized=True)
    for name, data in changes.items():
        if data is None:
            del files[name]
        else:
            files[name] = data
    return files


def compare(old_files, new_files, sources=(), zipped=False):
    with tempfile.TemporaryDirectory() as tmp:
        ext = "zip" if zipped else "tar.gz"
        old, new = os.path.join(tmp, "old." + ext), os.path.join(tmp, "new." + ext)
        for path, files in ((old, old_files), (new, new_files)):
            (make_zip if zipped else make_tgz)(path, files)
        return ab_package.compare(ab_package.list_archive(old), ab_package.list_archive(new), sources)


def test_the_same_package_is_green_and_every_member_of_the_ja_is_listed():
    report = compare(package(), package())
    assert report["verdict"] == "green" and report["counts"]["unchanged"] == 8, report["counts"]
    with tempfile.TemporaryDirectory() as tmp:
        make_tgz(os.path.join(tmp, "a.tar.gz"), package())
        listed = {e["path"]: e for e in ab_package.list_archive(os.path.join(tmp, "a.tar.gz"))["entries"]}
    assert listed["firefox"]["kind"] == "elf" and listed["libxul.so"]["kind"] == "so" and listed["omni.ja"]["kind"] == "ja"
    assert listed["omni.ja!modules/juggler/Helper.js"]["sha256"] == hashlib.sha256(b"helper v1\n").hexdigest()
    assert listed["application.ini"]["kind"] == "text" and listed["omni.ja!modules/juggler/Helper.js"]["size"] == 10


def test_a_file_added_is_red():
    report = compare(package(), dict(package(), **{"new-file.txt": b"x"}))
    assert report["verdict"] == "red" and [r["path"] for r in report["added"]] == ["new-file.txt"]


def test_a_file_missing_is_red():
    report = compare(package(), package(**{"defaults/pref/channel-prefs.js": None}))
    assert report["verdict"] == "red" and [r["path"] for r in report["missing"]] == ["defaults/pref/channel-prefs.js"]


def test_a_changed_binary_is_reported_and_green():
    report = compare(package(), package(**{"libxul.so": ELF + b"xul2", "firefox": ELF + b"v2"}))
    assert report["verdict"] == "green" and sorted(r["path"] for r in report["changed_binary"]) == ["firefox", "libxul.so"]


def test_a_changed_text_that_a_source_explains_is_green():
    new = package(**{"defaults/pref/channel-prefs.js": b'pref("app.update.channel", "esr");\n'})
    report = compare(package(), new, sources=["browser/app/profile/channel-prefs.js"])
    assert report["verdict"] == "green" and report["changed_non_binary"][0]["explained"] is True


def test_a_changed_text_that_no_source_explains_is_red():
    new = package(**{"defaults/pref/channel-prefs.js": b'pref("app.update.channel", "esr");\n'})
    for sources in ([], ["dom/base/nsFrameLoader.cpp", "juggler/Helper.js", "browser/app/other-file.js"]):
        report = compare(package(), new, sources=sources)
        assert report["verdict"] == "red" and report["red"] == {"changed_non_binary_unexplained": 1}, report["red"]


def test_a_cpp_source_does_not_explain_a_text_of_the_same_basename():
    new = package(**{"defaults/pref/channel-prefs.js": b"changed\n"})
    assert compare(package(), new, sources=["a/b/channel-prefs.cpp"])["verdict"] == "red"


def test_the_build_identity_is_reported_not_red():
    report = compare(package(), package(**{"application.ini": b"[App]\nBuildID=2\n"}))
    assert report["verdict"] == "green" and [r["path"] for r in report["changed_build_identity"]] == ["application.ini"]


def test_the_members_of_the_ja_are_reported_and_a_member_added_or_missing_is_red():
    report = compare(package(), package(ja=dict(JA_FILES, **{"modules/juggler/Helper.js": b"helper v2\n"})))
    assert report["verdict"] == "green", report["red"]
    assert [r["path"] for r in report["changed_ja_entry"]] == ["omni.ja!modules/juggler/Helper.js"]
    assert [r["path"] for r in report["changed_binary"]] == ["omni.ja"]
    report = compare(package(), package(ja=dict(JA_FILES, **{"chrome/b.css": b"b{}\n"})))
    assert report["verdict"] == "red" and [r["path"] for r in report["added"]] == ["omni.ja!chrome/b.css"]
    report = compare(package(), package(ja={k: v for k, v in JA_FILES.items() if k != "chrome/a.css"}))
    assert report["red"] == {"missing": 1}


def test_the_juggler_source_explains_its_file_by_path_in_either_layout():
    for path in ("omni.ja!modules/juggler/Helper.js", "modules/juggler/Helper.js"):
        assert ab_package._is_explained(path, ["juggler/Helper.js"])
    assert not ab_package._is_explained("modules/juggler/Other.js", ["juggler/Helper.js"])


def test_a_zip_with_both_layouts_of_ja_is_read_the_same():
    files = {"firefox.exe": PE + b"1", "xul.dll": PE + b"2", "omni.ja": make_ja({"modules/juggler/Helper.js": b"h\n"}), "browser/omni.ja": make_ja({"a/b.txt": b"t\n"}, optimized=True)}
    report = compare(files, dict(files, **{"xul.dll": PE + b"3"}), zipped=True)
    assert report["verdict"] == "green" and report["counts"]["unchanged"] == 5 and [r["path"] for r in report["changed_binary"]] == ["xul.dll"]
    assert compare(files, dict(files, **{"extra.txt": b"x"}), zipped=True)["verdict"] == "red"


def test_a_ja_that_cannot_be_read_is_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        make_tgz(os.path.join(tmp, "a.tar.gz"), {"omni.ja": b"not a zip at all"})
        try:
            ab_package.list_archive(os.path.join(tmp, "a.tar.gz"))
            raise AssertionError("an unreadable omni.ja was listed")
        except ab_package.Unreadable:
            pass
        with contextlib.redirect_stderr(io.StringIO()):
            assert ab_package.main(["list", os.path.join(tmp, "a.tar.gz")]) == 2


def test_the_exit_code_is_one_when_red_and_the_report_is_written():
    with tempfile.TemporaryDirectory() as tmp:
        for name, files in (("old", package()), ("new", dict(package(), **{"new-file.txt": b"x"})), ("same", package())):
            make_tgz(os.path.join(tmp, name + ".tar.gz"), files)
        args = ["compare", os.path.join(tmp, "old.tar.gz"), os.path.join(tmp, "new.tar.gz"), "--report", os.path.join(tmp, "r.json"), "--summary", os.path.join(tmp, "s.md")]
        with contextlib.redirect_stdout(io.StringIO()):
            assert ab_package.main(args) == 1
            assert ab_package.main(["compare", os.path.join(tmp, "old.tar.gz"), os.path.join(tmp, "same.tar.gz")]) == 0
        assert json.loads(Path(tmp, "r.json").read_text())["verdict"] == "red" and "RED" in Path(tmp, "s.md").read_text()


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def test_explain_names_the_sources_and_the_mozilla_files_of_a_changed_hooks_patch_section():
    with tempfile.TemporaryDirectory() as repo:
        _git(repo, "init", "-q")

        def write(rel, text):
            path = Path(repo, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

        patch = "diff --git a/dom/a.cpp b/dom/a.cpp\nindex 1..2 100644\n--- a/dom/a.cpp\n+++ b/dom/a.cpp\n@@ -1 +1 @@\n-x\n+y\n"
        patch += "diff --git a/browser/app/profile/firefox.js b/browser/app/profile/firefox.js\nindex 1..2 100644\n@@ -1 +1 @@\n-p\n+q\n"
        write("automation/juggler/src/juggler/Helper.js", "1\n")
        write("automation/juggler/src/juggler/Other.js", "1\n")
        write("automation/juggler/hooks.patch", patch)
        write("automation/juggler/FEATURE.md", "doc\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "one")
        old = _git(repo, "rev-parse", "HEAD")
        write("automation/juggler/src/juggler/Helper.js", "2\n")
        write("automation/juggler/FEATURE.md", "doc2\n")
        write("automation/juggler/hooks.patch", patch.replace("+q", "+r").replace("index 1..2", "index 3..4", 1))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "two")
        result = ab_package.explain(repo, old, _git(repo, "rev-parse", "HEAD"))
        assert result["sources"] == ["browser/app/profile/firefox.js", "juggler/Helper.js"], result
        assert result["changed_files_of_the_series"] == 3
        try:
            ab_package.explain(repo, "deadbeef" * 5, old)
            raise AssertionError("an unknown commit was accepted")
        except ab_package.Unreadable:
            pass


def test_the_seal_check_refuses_a_sha_that_the_seal_or_checksums_do_not_say():
    with tempfile.TemporaryDirectory() as tmp:
        data = b"archive bytes"
        sha = hashlib.sha256(data).hexdigest()
        Path(tmp, "a.zip").write_bytes(data)
        seal = {"tag": "firefox-1", "series_commit": "s" * 40, "source_commit": "c" * 40, "assets": {"a.zip": {"sha256": sha, "size": len(data)}}}
        Path(tmp, "seal.json").write_text(json.dumps(seal))
        Path(tmp, "checksums.txt").write_text("%s  a.zip\n" % sha)
        assert ab_package.seal_check(tmp)["problems"] == []
        Path(tmp, "checksums.txt").write_text("%s  a.zip\n" % ("0" * 64))
        assert len(ab_package.seal_check(tmp)["problems"]) == 1
        Path(tmp, "checksums.txt").write_text("%s  a.zip\n" % sha)
        Path(tmp, "a.zip").write_bytes(data + b"x")
        assert len(ab_package.seal_check(tmp)["problems"]) == 2


def test_the_gate_calls_package_ab_yml_with_the_published_tag_as_an_input():
    gate = (ROOT / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
    assert gate.count("\n  package-ab:\n") == 1 and gate.count("uses: ./.github/workflows/package-ab.yml") == 1
    assert "      published_tag:\n        description:" in gate and "        default: firefox-68\n" in gate
    job = (ROOT / ".github" / "workflows" / "package-ab.yml").read_text(encoding="utf-8")
    assert "    runs-on: ubuntu-24.04\n" in job and "    timeout-minutes: 15\n" in job
    for needle in ("gh release download", "sha256sum -c checksums.txt", "ab_package.py", "seal-check", "name: package-ab", "GITHUB_STEP_SUMMARY", "asset-linux-x86_64", "asset-win-x86_64"):
        assert needle in job, needle


def cases() -> list:
    """The tests above as (name, ok) pairs, for scripts/ci/test_ci.py, which the plan job runs (a test that no job runs is deleted)."""
    found = []
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                ok = True
            except AssertionError:
                ok = False
            found.append(("package A/B: " + name[len("test_"):].replace("_", " "), ok))
    return found


if __name__ == "__main__":
    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
