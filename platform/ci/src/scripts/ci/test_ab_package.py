"""The package manifest A/B (scripts/ci/ab_package.py) against the cases it exists for, on tiny archives made here: a tar.gz and a zip, each with a nested omni.ja.

    python -m pytest scripts/ci/test_ab_package.py

Run by scripts/ci/test_ci.py through cases(), like the other modules of this folder.
"""
import contextlib
import hashlib
import io
import json
import os
import re
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
import published_release  # noqa: E402

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


def compare(old_files, new_files, sources=(), zipped=False, **options):
    with tempfile.TemporaryDirectory() as tmp:
        ext = "zip" if zipped else "tar.gz"
        old, new = os.path.join(tmp, "old." + ext), os.path.join(tmp, "new." + ext)
        for path, files in ((old, old_files), (new, new_files)):
            (make_zip if zipped else make_tgz)(path, files)
        return ab_package.compare(ab_package.list_archive(old), ab_package.list_archive(new), sources, old, new, **options)


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


def test_the_build_identity_is_proved_by_the_content_and_reported_not_red():
    report = compare(package(), package(**{"application.ini": b"[App]\nBuildID=2\n"}))  # 1 -> 2 is not a BuildID: its value is not 14 digits
    assert report["verdict"] == "red" and report["red"] == {"changed_non_binary_unexplained": 1}
    old = b"[App]\nBuildID=20261118120000\nSourceStamp=" + b"a" * 40 + b"\nServerURL=https://x/submit?id=1&buildid=20261118120000&v=2\n"
    new = old.replace(b"20261118120000", b"20261121090000").replace(b"a" * 40, b"b" * 40)
    report = compare(package(**{"application.ini": old}), package(**{"application.ini": new}))
    assert report["verdict"] == "green" and [r["path"] for r in report["changed_build_identity"]] == ["application.ini"], report["red"]
    assert report["changed_build_identity"][0]["build_identity"] == ["MOZ_BUILDID", "MOZ_SOURCE_STAMP"]
    assert any(l.startswith("-BuildID=20261118120000") for l in report["changed_build_identity"][0]["diff"]), "the diff is the proof, in the report"
    # by content, not by name: the same lines in a file of any name are build identity, and another line next to them is not
    report = compare(package(**{"defaults/other.txt": old}), package(**{"defaults/other.txt": new}))
    assert report["verdict"] == "green" and report["counts"]["changed_build_identity"] == 1
    report = compare(package(**{"application.ini": old}), package(**{"application.ini": new + b"Extra=1\n"}))
    assert report["verdict"] == "red" and report["red"] == {"changed_non_binary_unexplained": 1}
    report = compare(package(**{"application.ini": old}), package(**{"application.ini": new.replace(b"&v=2", b"&v=3")}))
    assert report["verdict"] == "red", "a line that is not a token differs next to the tokens"


APP_CONSTANTS = (b"export var AppConstants = Object.freeze({\n  MOZ_APP_VERSION: \"68.0\",\n  MOZ_BUILDID: \"20261118120000\",\n"
                 b"  MOZ_BING_API_KEY: \"@KEY@\",\n  SOURCE_REVISION_URL: \"\",\n});\n")


def with_app_constants(content):
    return {"ja": dict(JA_FILES, **{"modules/AppConstants.sys.mjs": content})}


def test_the_members_of_the_ja_follow_the_rule_of_explained_sources_and_build_identity():
    helper = dict(JA_FILES, **{"modules/juggler/Helper.js": b"helper v2\n"})
    report = compare(package(), package(ja=helper), sources=["juggler/Helper.js"])
    assert report["verdict"] == "green", report["red"]
    assert [r["path"] for r in report["changed_ja_entry"]] == ["omni.ja!modules/juggler/Helper.js"] and report["changed_ja_entry"][0]["explained"] is True
    assert [r["path"] for r in report["changed_binary"]] == ["omni.ja"]
    report = compare(package(), package(ja=helper))  # no source of ours explains it
    assert report["verdict"] == "red" and report["red"] == {"changed_ja_entry_unexplained": 1}
    assert report["changed_ja_entry"][0]["diff"][2:] == ["@@ -1 +1 @@", "-helper v1", "+helper v2"]
    report = compare(package(), package(ja=dict(JA_FILES, **{"chrome/b.css": b"b{}\n"})))
    assert report["verdict"] == "red" and [r["path"] for r in report["added"]] == ["omni.ja!chrome/b.css"]
    report = compare(package(), package(ja={k: v for k, v in JA_FILES.items() if k != "chrome/a.css"}))
    assert report["red"] == {"missing": 1}


def test_appconstants_with_only_a_buildid_line_changed_is_build_identity_and_green():
    old = package(**with_app_constants(APP_CONSTANTS))
    new = package(**with_app_constants(APP_CONSTANTS.replace(b"20261118120000", b"20261121090000")))
    report = compare(old, new)
    assert report["verdict"] == "green", report["red"]
    row = report["changed_ja_entry"][0]
    assert row["path"] == "omni.ja!modules/AppConstants.sys.mjs" and row["build_identity"] == ["MOZ_BUILDID"] and row["explained"] is False
    assert '-  MOZ_BUILDID: "20261118120000",' in row["diff"] and '+  MOZ_BUILDID: "20261121090000",' in row["diff"]
    assert "(build identity: MOZ_BUILDID)" in ab_package.summary(report) and '| -  MOZ_BUILDID: "20261118120000",' in ab_package.summary(report)
    # the source url is a token too, with a commit in it; a repository that is not a url of a revision is not
    url = APP_CONSTANTS.replace(b'SOURCE_REVISION_URL: ""', b'SOURCE_REVISION_URL: "https://github.com/x/y/commit/' + b"c" * 40 + b'"')
    assert compare(old, package(**with_app_constants(url)))["verdict"] == "green"
    assert compare(old, package(**with_app_constants(APP_CONSTANTS.replace(b'SOURCE_REVISION_URL: ""', b'SOURCE_REVISION_URL: "http://evil/x"'))))["verdict"] == "red"


def test_appconstants_with_another_constant_or_a_changed_key_is_red():
    old = package(**with_app_constants(APP_CONSTANTS))
    for wrong in (APP_CONSTANTS.replace(b"@KEY@", b"a-real-key"),
                  APP_CONSTANTS.replace(b'"68.0"', b'"69.0"'),
                  APP_CONSTANTS.replace(b"20261118120000", b"20261121090000").replace(b"@KEY@", b"a-real-key"),  # the build id changed too: still red
                  APP_CONSTANTS.replace(b'MOZ_BUILDID: "20261118120000"', b'MOZ_BUILDID: "x"')):
        report = compare(old, package(**with_app_constants(wrong)))
        assert report["verdict"] == "red" and report["red"] == {"changed_ja_entry_unexplained": 1}, report["red"]
        assert report["changed_ja_entry"][0]["build_identity"] == [] and report["changed_ja_entry"][0]["diff"]
    # explained by a source of ours: green (the same file changed on purpose)
    assert compare(old, package(**with_app_constants(APP_CONSTANTS.replace(b"@KEY@", b"k"))), sources=["toolkit/modules/AppConstants.sys.mjs"])["verdict"] == "green"


def test_stealthpingsender_changed_and_explained_is_green_unexplained_is_red():
    old = package(ja=dict(JA_FILES, **{"modules/StealthPingsender.sys.mjs": b"export const a = 1;\n"}))
    new = package(ja=dict(JA_FILES, **{"modules/StealthPingsender.sys.mjs": b"export const a = 2;\n"}))
    report = compare(old, new, sources=["toolkit/components/telemetry/pings/StealthPingsender.sys.mjs"])
    assert report["verdict"] == "green" and report["changed_ja_entry"][0]["explained"] is True
    report = compare(old, new, sources=["toolkit/modules/AppConstants.sys.mjs"])
    assert report["verdict"] == "red" and report["red"] == {"changed_ja_entry_unexplained": 1}


def test_a_changed_text_without_the_archives_is_not_proved_build_identity():
    with tempfile.TemporaryDirectory() as tmp:
        for name, files in (("a", package(**with_app_constants(APP_CONSTANTS))), ("b", package(**with_app_constants(APP_CONSTANTS.replace(b"20261118120000", b"20261121090000"))))):
            make_tgz(os.path.join(tmp, name + ".tar.gz"), files)
        a, b = (ab_package.list_archive(os.path.join(tmp, n + ".tar.gz")) for n in "ab")
        assert ab_package.compare(a, b, [])["verdict"] == "red"  # lists only: no content, no proof
        assert ab_package.compare(a, b, [], os.path.join(tmp, "a.tar.gz"), os.path.join(tmp, "b.tar.gz"))["verdict"] == "green"


def test_the_diff_is_capped_and_says_how_many_lines_are_more():
    old, new = b"".join(b"line %d\n" % i for i in range(100)), b"".join(b"changed %d\n" % i for i in range(100))
    lines = ab_package.unified_diff(old, new)
    assert len(lines) == ab_package.DIFF_LINES + 1 and lines[-1].endswith("more lines") and ab_package.unified_diff(b"a\n", b"a\n") == []


def test_the_a_a_expects_nothing_changed_in_any_class():
    assert compare(package(), package(), expect_identical=True)["verdict"] == "green"
    for changed in (package(**{"libxul.so": ELF + b"xul2"}), package(**{"application.ini": b"[App]\nBuildID=20261118120000\n"}),
                    package(ja=dict(JA_FILES, **{"modules/juggler/Helper.js": b"helper v2\n"}))):
        report = compare(package(**{"application.ini": b"[App]\nBuildID=20261121090000\n"}) if "application.ini" in changed else package(), changed, expect_identical=True,
                         sources=["juggler/Helper.js"])
        assert report["verdict"] == "red" and "not_identical" in report["red"], report["red"]


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
    import yaml
    doc = yaml.safe_load(gate)
    default = (doc.get(True) or doc["on"])["workflow_call"]["inputs"]["published_tag"]
    assert default["default"] == "" and "latest published firefox-<N>" in default["description"], default
    job = (ROOT / ".github" / "workflows" / "package-ab.yml").read_text(encoding="utf-8")
    assert "    runs-on: ubuntu-24.04\n" in job and "    timeout-minutes: 15\n" in job
    for needle in ("gh release download", "sha256sum -c checksums.txt", "ab_package.py", "seal-check", "name: package-ab", "GITHUB_STEP_SUMMARY", "asset-linux-x86_64", "asset-win-x86_64"):
        assert needle in job, needle


# ---------------------------------------------------------------- the engine published before is resolved, never written in a workflow

WORKFLOWS = ROOT / ".github" / "workflows"
def _release(tag, draft=False, prerelease=False):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease}


def test_the_resolver_returns_the_latest_published_firefox_release():
    releases = [_release("firefox-68"), _release("firefox-70", draft=True), _release("firefox-71", prerelease=True), _release("firefox-69"),
                _release("firefox-69-candidate"), _release("firefox-100-candidate"), _release("v2.0"), _release("firefox-9"), {"name": "no tag"}]
    assert published_release.latest_published(releases) == "firefox-69"
    assert published_release.latest_published(list(reversed(releases))) == "firefox-69"
    # the highest NUMBER, not the highest string: firefox-9 is lower than firefox-68, and firefox-100 is higher than both
    assert published_release.latest_published([_release("firefox-9"), _release("firefox-100"), _release("firefox-68")]) == "firefox-100"


def test_the_resolver_fails_clearly_when_no_release_qualifies():
    nothing = [[], None, [_release("firefox-70", draft=True)], [_release("firefox-71", prerelease=True)], [_release("firefox-69-candidate"), _release("v1"), _release("firefox-")]]
    for releases in nothing:
        try:
            published_release.latest_published(releases)
            raise AssertionError("a list with no published firefox-<N> was accepted: %r" % (releases,))
        except published_release.NoPublishedRelease as error:
            assert "no published release named firefox-<N>" in str(error)


def test_the_resolver_cli_reads_paginated_output_and_writes_the_tag():
    pages = json.dumps([_release("firefox-68")]) + "\n" + json.dumps([_release("firefox-69"), _release("firefox-70", draft=True)])
    assert [r["tag_name"] for r in published_release.parse_pages(pages)] == ["firefox-68", "firefox-69", "firefox-70"]
    real_run = subprocess.run
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, FAKE["code"], FAKE["out"], FAKE["err"])

    FAKE = {"code": 0, "out": pages, "err": ""}
    published_release.subprocess.run = fake_run
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out, env = os.path.join(tmp, "out"), os.path.join(tmp, "env")
            with contextlib.redirect_stdout(io.StringIO()) as said:
                code = published_release.main(["--repo", "o/r", "--github-output", out, "--github-env", env, "--name", "TAG"])
            assert code == 0 and said.getvalue().strip() == "firefox-69", said.getvalue()
            assert calls == [["gh", "api", "repos/o/r/releases", "--paginate"]]
            assert Path(out).read_text() == "TAG=firefox-69\n" and Path(env).read_text() == "TAG=firefox-69\n"
            FAKE.update(out=json.dumps([_release("firefox-70", draft=True)]))
            with contextlib.redirect_stderr(io.StringIO()) as err:
                assert published_release.main(["--repo", "o/r", "--github-env", env, "--name", "TAG"]) == 1
            assert "no published release named firefox-<N>" in err.getvalue() and Path(env).read_text() == "TAG=firefox-69\n"
            FAKE.update(code=1, out="", err="HTTP 401")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                assert published_release.main(["--repo", "o/r"]) == 1
            assert "HTTP 401" in err.getvalue()
    finally:
        published_release.subprocess.run = real_run


def _workflow(name):
    import yaml
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_an_explicit_published_tag_wins_and_the_resolver_runs_only_when_it_is_empty():
    # package-ab.yml: the input is what TAG is (the resolver writes it only when the input is empty), and the candidate of the A/A takes its own input first
    pab = _workflow("package-ab.yml")["jobs"]["package-ab"]
    assert pab["env"]["TAG"] == "${{ inputs.published_tag }}"
    assert pab["env"]["CAND_TAG"].index("inputs.candidate_tag") < pab["env"]["CAND_TAG"].index("inputs.published_tag")
    steps = [s for s in pab["steps"] if "published_release.py" in str(s.get("run", ""))]
    assert len(steps) == 1 and steps[0]["if"] == "inputs.published_tag == ''" and 'echo "TAG=$BASE" >> "$GITHUB_ENV"' in steps[0]["run"]
    # xpcshell.yml: the input is what PUBLISHED_TAG is, the resolver runs only with an empty input on this workflow's own event, and the prefs baseline is always resolved
    xp = _workflow("xpcshell.yml")["jobs"]
    assert xp["xpcshell"]["env"]["PUBLISHED_TAG"] == "${{ inputs.published_tag }}"
    steps = [s for s in xp["xpcshell"]["steps"] if "published_release.py" in str(s.get("run", ""))]
    assert len(steps) == 1 and steps[0]["if"].startswith("inputs.published_tag == '' &&") and "--name PUBLISHED_TAG" in steps[0]["run"]
    steps = [s for s in xp["prefs"]["steps"] if "published_release.py" in str(s.get("run", ""))]
    assert len(steps) == 1 and "if" not in steps[0] and 'echo "PREFS_BASE_TAG=$LATEST" >> "$GITHUB_ENV"' in steps[0]["run"] and xp["prefs"]["env"]["PREFS_BASE_TAG"] == ""
    # gate.yml: the input goes to the called workflow as it came, and its default is empty
    gate = _workflow("gate.yml")
    assert gate["jobs"]["package-ab"]["with"]["published_tag"] == "${{ inputs.published_tag }}"
    assert (gate.get(True) or gate["on"])["workflow_call"]["inputs"]["published_tag"]["default"] == ""
    # every call of the resolver has the token and the checkout that holds the script
    # (xpcshell.yml's main job takes it from engine-ci, the pushed commit's CI code, because its engine-series is the series at the binary's commit)
    for name in ("package-ab.yml", "xpcshell.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert text.count("engine-series/platform/ci/src/scripts/ci/published_release.py") + text.count("engine-ci/platform/ci/src/scripts/ci/published_release.py") == text.count("published_release.py --repo")
    assert (WORKFLOWS / "xpcshell.yml").read_text(encoding="utf-8").count("/platform/ci/src/scripts/ci/published_release.py\n") == 2


# ---------------------------------------------------------------- RULE (decision ci-02, "derived, never written"), over every workflow and every CI script
#
# A reference to something that changes (a release of the engine, a build run, a release asset, a version of the core or the wrapper) is resolved at run time from its
# source of truth: the latest published release (scripts/ci/published_release.py), its seal, the version the wrapper pins, a branch head. A workflow input may name one
# explicitly, and then it wins. Three detectors, one rule test (test_no_workflow_or_script_writes_a_reference_that_changes):
#   a) a release tag `firefox-<N>`, as a whole token, in a value (a path component such as `ff-build/firefox-150` is not a tag);
#   b) a run id or an asset id: eight digits or more as a whole token, where a reference is written (see names_a_reference and scan_workflow);
#   c) a version `X.Y.Z` of the core or the wrapper, on a line (or under a key) that names `core`, `wrapper` or `invisible`.
# Prose is not checked: the `description` of a workflow input, a shell comment, a Python comment, a docstring and the `help=`/`description=` of argparse.
SCRIPTS = ROOT / "scripts"
RELEASE_TAG = re.compile(r"(?<![\w.-])firefox-\d+(?![\w.-])")
BIG_NUMBER = re.compile(r"(?<![\w.-])\d{8,}(?![\w.-])")
VERSION = re.compile(r"(?<![\w.])\d+\.\d+\.\d+(?!\w|\.\d)")
CORE_NAMES = re.compile(r"(?i)(?<![a-z])(?:invisible|core|wrapper)(?![a-z])")
# The words that say a number is a reference, split at _ - . (so RUN_ID, build-run-id and NODE_DEPS_ASSET count; SOURCE_DATE_EPOCH, GIT_AUTHOR_EMAIL, PREFS and runner do not).
ID_WORDS = {"run", "runs", "ref", "refs", "asset", "assets", "id", "runid"}


def release_tags(text) -> list:
    """The `firefox-<N>` of `text` that are tags: `.../firefox-150` is a path component, unless it follows `/tags/` or `/download/`."""
    found = []
    for m in RELEASE_TAG.finditer(text):
        before = text[:m.start()]
        if before.endswith("/") and not before.endswith(("/tags/", "/download/")):
            continue
        found.append(m.group(0))
    return found


def names_a_reference(prefix) -> bool:
    """True when one of the two words just before a number (the name it is assigned to, or the word before it) says run, ref, asset or id."""
    words = re.findall(r"[A-Za-z0-9_.-]+", prefix[-80:])[-2:]
    return any(part in ID_WORDS for word in words for part in re.split(r"[_.-]+", word.lower()))


def strip_shell_comment(line) -> str:
    """`line` without its comment: a `#` at the start or after a blank, outside quotes. A `$#` or a `${#a[@]}` is not a comment."""
    quote = ""
    for i, char in enumerate(line):
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def segment_hits(segment, physical, column, kinds, where) -> list:
    """The hits of one piece of text `segment` that starts at `column` of the physical line `physical` (its comment already out): (place, kind, token)."""
    found = []
    if "tag" in kinds:
        found += [(where, "release tag", tag) for tag in release_tags(segment)]
    if "id" in kinds:
        found += [(where, "run or asset id", m.group(0)) for m in BIG_NUMBER.finditer(segment) if names_a_reference(physical[:column + m.start()])]
    if "version" in kinds and CORE_NAMES.search(physical):
        found += [(where, "core or wrapper version", m.group(0)) for m in VERSION.finditer(segment)]
    return found


def scan_shell(text, kinds=("tag", "id", "version")) -> list:
    found = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = strip_shell_comment(raw)
        found += segment_hits(line, line, 0, kinds, "line %d" % number)
    return found


def scan_python(text) -> list:
    """The string literals (the docstrings and the help=/description=/epilog= of a call left out) and the numbers of a Python source, by tokenize. A comment is not checked."""
    import ast
    import tokenize
    lines = text.splitlines()
    skip = []  # (start, end) of the text that is prose, as (row, column in characters)

    def chars(row, byte_column):
        return len(lines[row - 1].encode("utf-8")[:byte_column].decode("utf-8", "ignore"))

    def prose(node):
        skip.append(((node.lineno, chars(node.lineno, node.col_offset)), (node.end_lineno, chars(node.end_lineno, node.end_col_offset))))

    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                prose(first.value)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in ("help", "description", "epilog"):
                    prose(keyword.value)
    strings = {tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", tokenize.STRING)}
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type in strings and not any(start <= tok.start < end for start, end in skip):
            for i, segment in enumerate(tok.string.split("\n")):
                row = tok.start[0] + i
                found += segment_hits(segment, strip_shell_comment(lines[row - 1]), tok.start[1] if i == 0 else 0, ("tag", "id", "version"), "line %d" % row)
        elif tok.type == tokenize.NUMBER and "." not in tok.string and "x" not in tok.string.lower():
            found += segment_hits(tok.string.replace("_", ""), lines[tok.start[0] - 1], tok.start[1], ("id",), "line %d" % tok.start[0])
    return found


def scan_workflow(text) -> list:
    """Every string of a parsed workflow (the keys too, for a tag) without the `description` of an input and without shell comments. A run or asset id is looked
    for where a reference is written: under `with:` or `env:`, a `ref`, a `run-id`, the `default` of an input, inside an expression `${{ }}`, and in a `run:` script by
    the shell rule. A version of the core or the wrapper: on a line that names them, or under a key that does."""
    import yaml
    found = []

    def visit(value, where, key, written):
        if isinstance(value, dict):
            inputs = "inputs" in where.split("/")
            for k, v in value.items():
                if k == "description":
                    continue
                found.extend((where + "/" + str(k), "release tag", tag) for tag in release_tags(str(k)))
                visit(v, where + "/" + str(k), str(k), written or k in ("with", "env", "ref", "run-id") or (k == "default" and inputs))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                visit(v, "%s[%d]" % (where, i), key, written)
        elif isinstance(value, bool) or value is None:
            return
        elif isinstance(value, int):
            if written and len(str(abs(value))) >= 8:
                found.append((where, "run or asset id", str(value)))
        elif isinstance(value, str):
            lines = [strip_shell_comment(line) for line in value.splitlines()]
            body = "\n".join(lines)
            found.extend((where, "release tag", tag) for tag in release_tags(body))
            if written:
                found.extend((where, "run or asset id", m.group(0)) for m in BIG_NUMBER.finditer(body))
            else:
                for expression in re.findall(r"\$\{\{(.*?)\}\}", body, re.S):
                    found.extend((where, "run or asset id (in an expression)", m.group(0)) for m in BIG_NUMBER.finditer(expression))
            if key == "run":
                found.extend((where + "/" + place, kind, token) for place, kind, token in scan_shell(body, ("id",)))
            for line in lines:
                if CORE_NAMES.search(line) or CORE_NAMES.search(key):
                    found.extend((where, "core or wrapper version", m.group(0)) for m in VERSION.finditer(line))

    visit(yaml.safe_load(text), "", "", False)
    return found


def rule_files() -> list:
    """Every workflow, and every script of scripts/ (Python and shell) except a test file and the folder of the browser smoke tests: (path, scanner)."""
    files = [(path, scan_workflow) for path in sorted(WORKFLOWS.glob("*.y*ml"))]
    for pattern, scanner in (("*.py", scan_python), ("*.sh", scan_shell)):
        for path in sorted(SCRIPTS.rglob(pattern)):
            parts = path.relative_to(SCRIPTS).parts
            if path.name.startswith("test_") or "tests" in parts or "__pycache__" in parts:
                continue
            files.append((path, scanner))
    return files


def written_references(read=lambda path: path.read_text(encoding="utf-8")) -> dict:
    """{file: hits} for every file of rule_files(), read through `read` (the tree of an older commit is read through git by whoever asks for it)."""
    bad = {}
    for path, scanner in rule_files():
        try:
            text = read(path)
        except FileNotFoundError:
            continue
        hits = scanner(text)
        if hits:
            bad[path.relative_to(ROOT).as_posix()] = hits
    return bad


def test_the_rule_detector_on_a_workflow_finds_what_is_written_and_lets_prose_and_other_numbers_through():
    bad = scan_workflow("a:\n  default: firefox-68\n  env: { TAG: \"${{ inputs.published_tag || 'firefox-68' }}\", RUN: '44921963200', N: 12345678 }\n"
                        "  inputs: { build_run_id: { default: '44921963200' } }\n  ref: 44921963200\n  x: \"${{ inputs.run || '44921963200' }}\"\n"
                        "  run: |\n    gh release download firefox-9 --repo x\n    gh run download 44921963200 --name x\n    RUN_ID=44921963200\n"
                        "    pip install invisible-core==69.82.0 invisible_playwright==0.57.0\n  CORE_VERSION: 69.82.0\n  with: { run-id: 44921963200 }\n")
    kinds = sorted({(kind, token) for _, kind, token in bad})
    assert kinds == [("core or wrapper version", "0.57.0"), ("core or wrapper version", "69.82.0"), ("release tag", "firefox-68"), ("release tag", "firefox-9"),
                     ("run or asset id", "12345678"), ("run or asset id", "44921963200"), ("run or asset id (in an expression)", "44921963200")], kinds
    assert sum(1 for _, kind, token in bad if token == "firefox-68") == 2 and any(where.endswith("/CORE_VERSION") for where, _, _ in bad), bad
    assert [where for where, kind, token in bad if kind == "run or asset id" and "/run/" in where] == ["/a/run/line 2", "/a/run/line 3"], bad
    fine = scan_workflow("a:\n  description: 'a tag (e.g. firefox-11) of a run 27346856197, core 69.82.0'\n  gate: 'a candidate: firefox-NN-candidate or firefox-69-candidate'\n"
                         "  path: ff-build/firefox-150/x\n  inputs: { published_tag: { default: '' } }\n  timeout-minutes: 15\n  small: 12345678\n  flag: true\n"
                         "  uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1  # v3.2.0\n  pin: 34e114876b0b11c390a56381ad16ebd13914f8d5\n"
                         "  env: { RUN: \"${{ github.run_id }}\", SOURCE_DATE_EPOCH: 'x', V: '${{ inputs.v }}' }\n  tool: pip install pytest==8.3.4 fonttools==4.55.3 cryptography==44.0.0\n"
                         "  run: |\n    # firefox-47 moved the juggler, run 44921963200, core 69.82.0\n    set -- art/firefox-*-stealth-linux.*\n    ls firefox-159.0-stealth-win.zip\n"
                         "    SOURCE_DATE_EPOCH=1700000000 sccache 0.8.1 node 22.23.4 # firefox-68\n    echo \"$GITHUB_RUN_ID\" \"${#a[@]}\" $#\n")
    assert [(kind, token) for _, kind, token in fine] == [], fine


def test_the_rule_detector_on_a_python_script_checks_strings_and_numbers_but_not_prose():
    bad = scan_python('TAG = "firefox-68"\nSEAL = {"run": 44921963200, "asset": "709796661"}\nASSET_ID = 678460500\nCORE = "invisible_core==69.82.0"\n'
                      'def f(): return "release firefox-9 of run 44921963200"\nCMD = f"gh run view 44921963200 {SEAL}"\nREF = "firefox-9"\n')
    assert sorted((kind, token) for _, kind, token in bad) == sorted([
        ("release tag", "firefox-68"), ("run or asset id", "44921963200"), ("run or asset id", "709796661"), ("run or asset id", "678460500"),
        ("core or wrapper version", "69.82.0"), ("release tag", "firefox-9"), ("run or asset id", "44921963200"), ("run or asset id", "44921963200"),
        ("release tag", "firefox-9")]), bad
    fine = scan_python('"""Module prose: firefox-68, run 44921963200, core 69.82.0."""\nimport argparse\nSOURCE_DATE_EPOCH = 1700000000\nEMAIL = "GIT_AUTHOR_EMAIL=12345678"\n'
                       'P = "ff-build/firefox-150"\nOLD = "firefox-69-candidate"\nVER = "sccache 0.8.1 fonttools==4.55.3"\n'
                       'def f():\n    """Prose: firefox-68 and run 44921963200."""\n    # firefox-68 in a comment, run 44921963200, core 69.82.0\n    return 12345678 + 1.5\n'
                       'p = argparse.ArgumentParser(description="e.g. firefox-4 of core 69.82.0")\np.add_argument("--tag", help="a tag such as firefox-68, run 44921963200")\n')
    assert fine == [], fine


def test_the_rule_detector_on_a_shell_script_checks_what_runs_and_not_the_comments():
    bad = scan_shell('NODE_DEPS_ASSET=709796661\nRUNNER_ASSET="678460500"\ngh release download firefox-68 --repo x\ncurl https://x/releases/assets/709796661\n'
                     'gh run download 44921963200 --name x\npip install invisible_core==69.82.0\nCORE_VERSION=69.82.0\n')
    assert sorted(bad) == sorted([
        ("line 1", "run or asset id", "709796661"), ("line 2", "run or asset id", "678460500"), ("line 3", "release tag", "firefox-68"),
        ("line 4", "run or asset id", "709796661"), ("line 5", "run or asset id", "44921963200"), ("line 6", "core or wrapper version", "69.82.0"),
        ("line 7", "core or wrapper version", "69.82.0")]), bad
    fine = scan_shell('# firefox-68, run 44921963200, core 69.82.0\nSOURCE_DATE_EPOCH=1700000000\nexport GIT_AUTHOR_EMAIL=12345678@x\nNODE_VERSION=22.23.4 # core 1.2.3\n'
                      'echo "${#a[@]} $# firefox-*-stealth-linux.tar" "ff-build/firefox-150"\nRUNNER_VERSION=2.338.2\n'
                      'curl -o x "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/x.tar.gz"\nsccache_version=0.8.1\n')
    assert fine == [], fine


def test_the_rule_reads_every_workflow_and_every_script_but_the_tests():
    names = [path.relative_to(ROOT).as_posix() for path, _ in rule_files()]
    assert len([n for n in names if n.startswith(".github/workflows/")]) >= 12 and len(names) >= 50, names
    assert ".github/workflows/package-ab.yml" in names and "scripts/ci/node_bootstrap.sh" in names and "scripts/stock_parity.py" in names
    assert "scripts/ci/published_release.py" in names and "scripts/make_release.sh" in names
    assert not any("/test_" in n or "/tests/" in n or "__pycache__" in n for n in names), names


def test_no_workflow_or_script_writes_a_reference_that_changes():
    """RULE (ci-02, derived and never written): a release of the engine, a build run, a release asset, a version of the core or the wrapper is resolved at run time
    from its source of truth (the latest published release, scripts/ci/published_release.py; its seal; the version the wrapper pins; a branch head) or given as an
    input, which wins. A value written in a workflow or a script is stale the day the next release is published (firefox-68 stayed in the gate after firefox-69)
    and a run's archives expire. Prose (a comment, an input's description, a docstring, an argparse help) is free to name them."""
    bad = written_references()
    assert not bad, bad


def test_the_resolver_rank_picks_the_release_before_the_latest():
    releases = [_release("firefox-67"), _release("firefox-69"), _release("firefox-68"), _release("firefox-70", draft=True), _release("firefox-71", prerelease=True),
                _release("firefox-69-candidate"), _release("firefox-100", prerelease=True), _release("firefox-69")]
    assert published_release.latest_published(releases) == published_release.latest_published(releases, 1) == "firefox-69"
    assert published_release.latest_published(releases, 2) == "firefox-68" and published_release.latest_published(releases, 3) == "firefox-67"
    # the same tag twice is one release; a rank beyond the releases there are is an error that says how many there are, and 0 is not a rank
    for given, rank, message in ((releases, 4, "only 3 published release(s)"), ([], 1, "no published release")):
        try:
            published_release.latest_published(given, rank)
            raise AssertionError("rank %d was accepted" % rank)
        except published_release.NoPublishedRelease as error:
            assert message in str(error), str(error)
    try:
        published_release.latest_published(releases, 0)
        raise AssertionError("rank 0 was accepted")
    except ValueError:
        pass
    pages = json.dumps([_release("firefox-67"), _release("firefox-68"), _release("firefox-69")])
    real_run = subprocess.run
    published_release.subprocess.run = lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, pages, "")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            env = os.path.join(tmp, "env")
            with contextlib.redirect_stdout(io.StringIO()) as said:
                assert published_release.main(["--repo", "o/r", "--rank", "2", "--github-env", env, "--name", "TAG"]) == 0
            assert said.getvalue().strip() == "firefox-68" and Path(env).read_text() == "TAG=firefox-68\n"
            with contextlib.redirect_stderr(io.StringIO()) as err:
                assert published_release.main(["--repo", "o/r", "--rank", "4"]) == 1
            assert "only 3 published release(s)" in err.getvalue()
    finally:
        published_release.subprocess.run = real_run


def _steps_with(steps, needle):
    return [s for s in steps if needle in str(s.get("run", "")) or needle in str(s.get("uses", "")) or needle in str(s.get("name", ""))]


def test_an_explicit_build_run_id_wins_and_a_call_without_one_reads_its_own_run():
    """A call (the gate's) names its run and that run's artifacts are read as before; a call that names none reads this run's own (github.run_id), never a literal."""
    pab = _workflow("package-ab.yml")["jobs"]["package-ab"]
    assert pab["env"]["BUILD_RUN_ID"] == "${{ inputs.build_run_id || github.run_id }}"
    # the candidate's artifacts (the wheelhouse of the job's py-deps call is this run's own, with no run-id)
    down = [s for s in pab["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact") and "run-id" in s["with"]]
    assert len(down) == 3 and all(s["with"]["run-id"] == "${{ env.BUILD_RUN_ID }}" and "github.run_id" in s["with"]["github-token"] for s in down)
    xp = _workflow("xpcshell.yml")
    on = xp.get(True) or xp["on"]
    assert on["workflow_dispatch"]["inputs"]["build_run_id"]["default"] == ""
    main_dl = [s for s in xp["jobs"]["xpcshell"]["steps"] if str(s.get("name", "")).startswith("Download asset (the run's)")]
    cand_dl = [s for s in xp["jobs"]["prefs"]["steps"] if str(s.get("name", "")).startswith("Download the candidate (the run's asset)")]
    assert len(main_dl) == 1 and len(cand_dl) == 1
    for step in main_dl + cand_dl:
        assert step["with"]["run-id"] == "${{ inputs.build_run_id || github.run_id }}", step["with"]
        assert step["with"]["github-token"] == "${{ (inputs.build_run_id || github.run_id) != github.run_id && github.token || '' }}", step["with"]
    # the main job: a given published tag or a given run is never replaced by the latest release (the resolver needs both empty), and the run's artifacts are
    # downloaded only when no release is the engine
    resolver = _steps_with(xp["jobs"]["xpcshell"]["steps"], "published_release.py")
    assert len(resolver) == 1 and "inputs.published_tag == ''" in resolver[0]["if"] and "inputs.build_run_id == ''" in resolver[0]["if"]
    assert main_dl[0]["if"] == "env.PUBLISHED_TAG == ''"
    # the prefs job: the candidate is the run's asset unless the step that resolves the release found no run named (a call names its run, whatever its event)
    pref = _steps_with(xp["jobs"]["prefs"]["steps"], "published_release.py")
    assert len(pref) == 1 and "inputs.build_run_id == ''" in pref[0]["env"]["OWN_RUN"] and "github.workflow == 'xpcshell'" in pref[0]["env"]["OWN_RUN"]
    assert cand_dl[0]["if"] == "env.PREFS_CAND_TAG == ''"


def test_a_push_or_a_dispatch_with_no_run_takes_the_archives_of_the_latest_published_release():
    pab = _workflow("package-ab.yml")["jobs"]["package-ab"]
    steps = pab["steps"]
    resolver = _steps_with(steps, "published_release.py")
    assert len(resolver) == 1 and resolver[0]["if"] == "inputs.published_tag == ''"
    run = resolver[0]["run"]
    own = resolver[0]["env"]["OWN_PUSH"]
    # the own push of package-ab only (the caller's name is github.workflow in a call): the A/B leg is the latest against the one before it
    assert "github.event_name == 'push'" in own and "github.workflow == 'package-ab'" in own and "inputs.build_run_id == ''" in own
    assert '[ "$MODE" = ab ] && [ -n "$OWN_PUSH" ]' in run and "--rank 2" in run and 'echo "CAND_TAG=$LATEST" >> "$GITHUB_ENV"' in run and 'echo "TAG=$BASE" >> "$GITHUB_ENV"' in run
    # ... which is the path of a release as the candidate, checked against its seal and checksums.txt, the run's artifacts skipped
    rel = [s for s in steps if s.get("id") == "candidate_release"]
    assert len(rel) == 1 and rel[0]["if"] == "env.CAND_TAG != ''" and "sha256sum -c checksums.txt" in rel[0]["run"] and "seal-check candidate-release" in rel[0]["run"]
    assert all(s["if"] == "env.CAND_TAG == ''" for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact") and "run-id" in s["with"])
    assert steps.index(resolver[0]) < steps.index(rel[0])
    # the A/A of a push's tag leg is the latest with itself, and only a push or the gate's call without candidate_tag gets it
    assert '[ "$MODE" = tag ] && [ -z "$CANDIDATE_TAG" ]' in run
    # xpcshell.yml, the main job: the same release, and its archives verified against the seal before they are extracted
    xp = _workflow("xpcshell.yml")["jobs"]
    legs = xp["xpcshell"]["steps"]
    latest = _steps_with(legs, "published_release.py")
    assert len(latest) == 1 and latest[0]["if"] == "inputs.published_tag == '' && inputs.build_run_id == '' && github.workflow == 'xpcshell'"
    pub = [s for s in legs if str(s.get("name", "")).startswith("Download asset (the published")]
    assert len(pub) == 1 and pub[0]["if"] == "env.PUBLISHED_TAG != ''" and "verify-asset" in pub[0]["run"] and legs.index(latest[0]) < legs.index(pub[0])
    # xpcshell.yml, the prefs job: the candidate release and the base are both released archives checked against their seals, the candidate's download first
    ps = xp["prefs"]["steps"]
    assert xp["prefs"]["env"]["PREFS_CAND_TAG"] == "" and xp["prefs"]["env"]["PREFS_BASE_TAG"] == ""
    resolver = _steps_with(ps, "published_release.py")
    cand_rel = [s for s in ps if str(s.get("name", "")).startswith("Download the candidate (the latest published")]
    base_rel = [s for s in ps if str(s.get("name", "")).startswith("Download the published engine")]
    assert len(resolver) == 1 and len(cand_rel) == 1 and len(base_rel) == 1
    assert 'echo "PREFS_CAND_TAG=$LATEST" >> "$GITHUB_ENV"' in resolver[0]["run"] and 'echo "PREFS_BASE_TAG=$LATEST" >> "$GITHUB_ENV"' in resolver[0]["run"]
    assert cand_rel[0]["if"] == "env.PREFS_CAND_TAG != ''" and "art-cand" in cand_rel[0]["run"] and "verify-asset --dir art-cand" in cand_rel[0]["run"]
    assert "verify-asset --dir art-pub" in base_rel[0]["run"] and "if" not in base_rel[0]
    assert ps.index(resolver[0]) < ps.index(cand_rel[0]) and ps.index(resolver[0]) < ps.index(base_rel[0])


# ---------------------------------------------------------------- RULE (decision ci-09, "tests and binary come from the same commit"), over every workflow
#
# A job that takes an engine binary it did not build in this run (the archives of a release; the asset-* artifacts, or the dist/bin of a gtest build, of a run whose
# id is given: another run's build, which the gate and the republish reuse) and runs tests of the engine's behaviour from the series must take those tests at the
# series commit the binary was built from: the seal's series_commit of a release, the series-commit.txt its build recorded (else the head_sha of its run) of a run,
# never the branch head that was pushed. It says so in one of two ways: a checkout of the series whose `ref` is the `series_commit` output of an earlier step that
# resolves it from the binary (scripts/ci/binary_series.py), or a step that compares the binary's series commit with github.sha and fails on a difference. A job
# that runs no test of the series on the binary is declared below, with its reason; the declaration is checked too (the job exists and still takes such a binary).
COMMIT_RULE_DECLARED = {
    "package-ab.yml::package-ab": "comparator: two binaries compared by scripts/ci/ab_package.py (CI code of the pushed commit); the series is only the diff of sources that explains a change",
    "xpcshell.yml::prefs": "comparator: the preferences of two binaries dumped and compared by CI code (xpcshell_run.py prefs, prefs_dump.js); no test of the series runs",
    "gate.yml::wrapper-e2e": "the tests are the wrapper's, from its own repository at wrapper_ref (the pairing of a binary with a wrapper ref is the caller's: the refs are today's, the bytes are that run's)",
    "verify-assets.yml::drive": "the test is the wrapper's drive gate, from its own repository, on a release's archive; no test of the series runs",
    "publish.yml::publish": "publisher: it seals and uploads the build's archives with the build's own series-commit.txt and runs no test on the binary",
}
BINARY_ARTIFACT = re.compile(r"(?<![\w-])(?:asset|gtest-bin)-")
BINARY_ARCHIVE = re.compile(r"stealth|\*\.tar\.gz|\*\.zip")
SERIES_REF = re.compile(r"\$\{\{\s*steps\.([\w-]+)\.outputs\.series_commit\s*\}\}")


def takes_a_binary_it_did_not_build(job) -> bool:
    """True when a step downloads an engine binary of a release or of a run named by id (a download-artifact with a run-id on an asset-* or gtest-bin-* artifact,
    `gh release download` of the archives, or the API of a run's artifacts for asset-*). A release's seal or series-commit.txt alone is not a binary."""
    for step in job.get("steps") or []:
        uses, with_, run = str(step.get("uses", "")), step.get("with") or {}, str(step.get("run", ""))
        if uses.startswith("actions/download-artifact") and "run-id" in with_ and BINARY_ARTIFACT.search(str(with_.get("name") or with_.get("pattern") or "")):
            return True
        if "gh release download" in run and BINARY_ARCHIVE.search(run):
            return True
        if "actions/runs/" in run and "artifacts?name=asset-" in run:
            return True
    return False


def takes_its_tests_at_the_series_commit_of_the_binary(job) -> bool:
    steps = job.get("steps") or []
    by_id = {step["id"]: i for i, step in enumerate(steps) if step.get("id")}
    for i, step in enumerate(steps):
        if str(step.get("uses", "")).startswith("actions/checkout"):
            match = SERIES_REF.fullmatch(str((step.get("with") or {}).get("ref", "")).strip())
            if match and by_id.get(match.group(1), len(steps)) < i and "binary_series.py" in str(steps[by_id[match.group(1)]].get("run", "")):
                return True
        run = str(step.get("run", ""))
        if re.search(r"series", run, re.I) and ("$GITHUB_SHA" in run or "github.sha" in run) and ("seal" in run or "series-commit" in run) and "exit 1" in run:
            return True
    return False


def jobs_that_break_the_commit_rule(docs, declared=COMMIT_RULE_DECLARED) -> list:
    """The `file::job` of every job that takes a binary it did not build and neither takes its tests at the binary's series commit nor is declared; plus every
    declaration that names a job that is not there or no longer takes such a binary."""
    bad, seen = [], set()
    for name, doc in sorted(docs.items()):
        for job_id, job in sorted(((doc or {}).get("jobs") or {}).items()):
            key = "%s::%s" % (name, job_id)
            if not isinstance(job, dict) or not takes_a_binary_it_did_not_build(job):
                continue
            seen.add(key)
            if key not in declared and not takes_its_tests_at_the_series_commit_of_the_binary(job):
                bad.append(key)
    bad += ["%s (declared, but it is not a job that takes such a binary)" % key for key in sorted(set(declared) - seen)]
    return bad


def test_tests_and_binary_come_from_the_same_commit():
    """RULE (ci-09): every job that downloads a binary of another run or of a release checks out the tests at that binary's series commit (or proves the two commits
    equal), or is a declared comparator, publisher or job whose tests are not the series'. The push mode of xpcshell.yml ran the series' tests of today against
    firefox-69 (an English console message against an Italian one): red on a test, not on the engine."""
    docs = {path.name: _workflow(path.name) for path in sorted(WORKFLOWS.glob("*.y*ml"))}
    assert jobs_that_break_the_commit_rule(docs) == []
    # the two jobs that run the series' tests on such a binary read them from the checkout at the binary's commit, and nothing else puts the pushed commit there
    for name, job_id in (("gate.yml", "gate"), ("xpcshell.yml", "xpcshell")):
        steps = docs[name]["jobs"][job_id]["steps"]
        series = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout") and (s["with"].get("path") == "engine-series")]
        assert len(series) == 1 and SERIES_REF.fullmatch(series[0]["with"]["ref"]), (name, series)
        resolve = [s for s in steps if s.get("id") == "binary"]
        assert len(resolve) == 1 and "binary_series.py" in resolve[0]["run"] and '--own-run-id "$GITHUB_RUN_ID" --own-sha "$GITHUB_SHA"' in resolve[0]["run"], name
    xp_resolve = [s for s in docs["xpcshell.yml"]["jobs"]["xpcshell"]["steps"] if s.get("id") == "binary"][0]["run"]
    assert '"$RESOLVE" seal --dir art' in xp_resolve and '"$RESOLVE" run --repo' in xp_resolve  # a release's seal, or a run's build


def test_the_commit_rule_finds_a_job_that_takes_a_binary_and_its_tests_from_the_pushed_commit_and_lets_the_others_through():
    def job(*steps):
        return {"jobs": {"j": {"steps": list(steps)}}}
    artifact = {"uses": "actions/download-artifact@x", "with": {"name": "asset-${{ matrix.leg }}", "run-id": "${{ inputs.build_run_id }}"}}
    release = {"run": 'gh release download "$TAG" --pattern seal.json --pattern "firefox-*-stealth-${{ matrix.leg }}.*" --dir art'}
    pushed = {"uses": "actions/checkout@x", "with": {"ref": "${{ github.sha }}", "path": "engine-series"}}
    resolve = {"id": "binary", "run": "python engine-ci/platform/ci/src/scripts/ci/binary_series.py seal --dir art --github-output \"$GITHUB_OUTPUT\""}
    at_binary = {"uses": "actions/checkout@x", "with": {"ref": "${{ steps.binary.outputs.series_commit }}", "path": "engine-series"}}
    compare = {"run": 'test "$SERIES_COMMIT" = "$GITHUB_SHA" || { echo "the seal names another series commit"; exit 1; }  # seal'}
    for taken in (artifact, release):
        assert jobs_that_break_the_commit_rule({"w.yml": job(taken, pushed)}, {}) == ["w.yml::j"]
        assert jobs_that_break_the_commit_rule({"w.yml": job(taken, resolve, pushed)}, {}) == ["w.yml::j"]
        assert jobs_that_break_the_commit_rule({"w.yml": job(at_binary, taken)}, {}) == ["w.yml::j"], "the commit is resolved after the checkout that uses it"
        assert jobs_that_break_the_commit_rule({"w.yml": job(taken, {"id": "binary", "run": "echo series_commit=$X"}, at_binary)}, {}) == ["w.yml::j"], "an output that is not derived from the binary"
        assert jobs_that_break_the_commit_rule({"w.yml": job(taken, resolve, at_binary)}, {}) == []
        assert jobs_that_break_the_commit_rule({"w.yml": job(taken, compare)}, {}) == []
        assert jobs_that_break_the_commit_rule({"w.yml": job(taken, pushed)}, {"w.yml::j": "declared"}) == []
    # not a binary of another run or of a release: this run's own artifact (no run-id), a report, the seal alone
    assert jobs_that_break_the_commit_rule({"w.yml": job({"uses": "actions/download-artifact@x", "with": {"name": "asset-linux"}}, pushed)}, {}) == []
    assert jobs_that_break_the_commit_rule({"w.yml": job({"uses": "actions/download-artifact@x", "with": {"pattern": "gtest-reports-*", "run-id": "${{ inputs.r }}"}}, pushed)}, {}) == []
    assert jobs_that_break_the_commit_rule({"w.yml": job({"run": 'gh release download "$T" --pattern series-commit.txt --pattern seal.json'}, pushed)}, {}) == []
    # a declaration of a job that is not there, or that takes no such binary, is itself a failure
    assert jobs_that_break_the_commit_rule({"w.yml": job(pushed)}, {"w.yml::j": "x", "gone.yml::k": "y"}) == [
        "gone.yml::k (declared, but it is not a job that takes such a binary)", "w.yml::j (declared, but it is not a job that takes such a binary)"]


def test_the_series_commit_of_a_binary_is_its_seal_s_or_its_build_s_and_a_run_s_own_is_proved_equal_to_the_pushed_commit():
    import binary_series
    one, two = "a" * 40, "b" * 40
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "seal.json").write_text(json.dumps({"tag": "firefox-1", "series_commit": one}), encoding="utf-8")
        assert binary_series.from_seal(tmp) == one
        out = tmp / "out"
        assert binary_series.main(["seal", "--dir", str(tmp), "--github-output", str(out), "--name", "series_commit"]) == 0 and out.read_text(encoding="utf-8") == "series_commit=%s\n" % one
        for bad in ({"series_commit": "abc"}, {"tag": "x"}, "[]"):
            (tmp / "seal.json").write_text(json.dumps(bad), encoding="utf-8")
            try:
                binary_series.from_seal(tmp)
                raise AssertionError("a seal without a full series_commit was accepted: %r" % (bad,))
            except binary_series.NoSeriesCommit:
                pass
        # a run: what its build recorded, else the head_sha of the run
        rec = tmp / "source-commit"
        rec.mkdir()
        (rec / "series-commit.txt").write_text(two + "\n", encoding="utf-8")
        assert binary_series.from_run("o/r", "7", rec) == two
        real_run, calls = binary_series.subprocess.run, []
        def fake(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout=one + "\n", stderr="")
        binary_series.subprocess.run = fake
        try:
            assert binary_series.from_run("o/r", "8", tmp / "none") == one and calls[0][:3] == ["gh", "api", "repos/o/r/actions/runs/8"], calls
            (rec / "series-commit.txt").write_text("", encoding="utf-8")
            assert binary_series.from_run("o/r", "8", rec) == one
            # this run's own build: equal to the pushed commit passes, another commit is an error; another run's is not compared
            assert binary_series.from_run("o/r", "9", tmp / "none", own_run_id="9", own_sha=one) == one
            for own_sha in (two, ""):
                try:
                    binary_series.from_run("o/r", "9", tmp / "none", own_run_id="9", own_sha=own_sha)
                    raise AssertionError("the series commit of this run's own build differs from the pushed commit and it passed")
                except binary_series.NoSeriesCommit:
                    pass
            assert binary_series.from_run("o/r", "8", tmp / "none", own_run_id="9", own_sha=two) == one
        finally:
            binary_series.subprocess.run = real_run


# ---------------------------------------------------------------- the linkage: tiny PE and ELF files made here

def make_pe(imports=None, delay=None, exports=(), forwarded=(), wide=True):
    """A PE with one section that holds an import directory ({dll: [name or ordinal int]}), a delay-load directory (same) and an export directory
    (names, and names exported as forwarders to another DLL)."""
    sec_rva, sec_raw = 0x1000, 0x200
    blob = bytearray()

    def put(data, align=8):
        blob.extend(b"\0" * (-len(blob) % align))
        rva = sec_rva + len(blob)
        blob.extend(data)
        return rva

    tfmt, flag = ("<Q", 1 << 63) if wide else ("<I", 1 << 31)

    def thunk_array(funcs):
        values = [flag | f if isinstance(f, int) else put(struct.pack("<H", 0) + f.encode() + b"\0", 2) for f in funcs]
        return b"".join(struct.pack(tfmt, v) for v in values) + struct.pack(tfmt, 0)

    descs = b""
    for dll, funcs in (imports or {}).items():
        name = put(dll.encode() + b"\0")
        int_, iat = put(thunk_array(funcs)), put(thunk_array(funcs))
        descs += struct.pack("<5I", int_, 0, 0, name, iat)
    imp = (put(descs + b"\0" * 20), len(descs) + 20) if imports else (0, 0)
    descs = b""
    for dll, funcs in (delay or {}).items():
        name, handle = put(dll.encode() + b"\0"), put(b"\0" * 8)
        int_, iat = put(thunk_array(funcs)), put(thunk_array(funcs))
        descs += struct.pack("<8I", 1, name, handle, iat, int_, 0, 0, 0)
    dly = (put(descs + b"\0" * 32), len(descs) + 32) if delay else (0, 0)
    exp = (0, 0)
    if exports or forwarded:
        names = sorted(list(exports) + list(forwarded))
        blob.extend(b"\0" * (-len(blob) % 8))
        base = sec_rva + len(blob)
        n = len(names)
        afun, anames, aords = base + 40, base + 40 + 4 * n, base + 40 + 8 * n
        strings, pos, name_rvas, fun_rvas = b"", aords + 2 * n, [], []
        for name in names:
            name_rvas.append(pos + len(strings))
            strings += name.encode() + b"\0"
        for name in names:
            if name in forwarded:
                fun_rvas.append(pos + len(strings))
                strings += b"OTHER." + name.encode() + b"\0"
            else:
                fun_rvas.append(0x5000)  # code, outside the export directory
        chunk = struct.pack("<4I6I", 0, 0, 0, 0, 1, n, n, afun, anames, aords) + struct.pack("<%dI" % n, *fun_rvas) + struct.pack("<%dI" % n, *name_rvas)
        chunk += struct.pack("<%dH" % n, *range(n)) + strings
        blob.extend(chunk)
        exp = (base, len(chunk))
    blob.extend(b"\0" * (-len(blob) % 0x200))
    dirs = [(0, 0)] * 16
    dirs[0], dirs[1], dirs[13] = exp, imp, dly
    opt = struct.pack("<HBB5I", 0x20B if wide else 0x10B, 14, 0, 0, 0, 0, 0, 0x1000)
    opt += struct.pack("<Q", 0x180000000) if wide else struct.pack("<II", 0, 0x10000000)
    opt += struct.pack("<II6H4I2H", 0x1000, 0x200, 6, 0, 0, 0, 6, 0, 0, sec_rva + len(blob), sec_raw, 0, 2, 0)
    opt += struct.pack("<4Q" if wide else "<4I", 0, 0, 0, 0) + struct.pack("<II", 0, 16) + b"".join(struct.pack("<II", *d) for d in dirs)
    head = b"MZ" + b"\0" * 0x3A + struct.pack("<I", 0x40) + b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664 if wide else 0x14C, 1, 0, 0, 0, len(opt), 0x22) + opt
    head += struct.pack("<8sIIIIIIHHI", b".rdata", len(blob), sec_rva, len(blob), sec_raw, 0, 0, 0, 0, 0x40000040)
    return head + b"\0" * (sec_raw - len(head)) + bytes(blob)


def make_elf(needed=(), soname=None, undefined=(), defined=()):
    """An ELF64 shared object with .dynstr, .dynsym, .gnu.version, .gnu.version_r and .dynamic: undefined is [(symbol, version or None, library)]."""
    strtab, offsets = bytearray(b"\0"), {}

    def s(text):
        if text not in offsets:
            offsets[text] = len(strtab)
            strtab.extend(text.encode() + b"\0")
        return offsets[text]

    groups = {}
    for _name, version, lib in undefined:
        if version:
            groups.setdefault(lib, [])
            if version not in groups[lib]:
                groups[lib].append(version)
    index, verneed = {}, b""
    files = list(groups)
    for fi, lib in enumerate(files):
        verneed += struct.pack("<HHIII", 1, len(groups[lib]), s(lib), 16, 0 if fi == len(files) - 1 else 16 + 16 * len(groups[lib]))
        for vi, version in enumerate(groups[lib]):
            index[(lib, version)] = len(index) + 2
            verneed += struct.pack("<IHHII", 0, 0, index[(lib, version)], s(version), 0 if vi == len(groups[lib]) - 1 else 16)
    syms, versym = [b"\0" * 24], [0]
    for name, version, lib in undefined:
        syms.append(struct.pack("<IBBHQQ", s(name), 0x12, 0, 0, 0, 0))
        versym.append(index[(lib, version)] if version else 1)
    for name in defined:
        syms.append(struct.pack("<IBBHQQ", s(name), 0x12, 0, 7, 0x1000, 8))
        versym.append(1)
    dyn = b"".join(struct.pack("<qQ", 1, s(lib)) for lib in needed) + (struct.pack("<qQ", 14, s(soname)) if soname else b"") + struct.pack("<qQ", 0, 0)
    parts = [bytes(strtab), b"".join(syms), struct.pack("<%dH" % len(versym), *versym), verneed, dyn]
    body, offs = b"", []
    for part in parts:
        body += b"\0" * (-(64 + len(body)) % 8)
        offs.append(64 + len(body))
        body += part
    body += b"\0" * (-(64 + len(body)) % 8)
    shoff = 64 + len(body)
    # (type, link, info, entsize) of .dynstr, .dynsym, .gnu.version, .gnu.version_r, .dynamic, after the null section
    kinds = [(3, 0, 0, 0), (11, 1, 1, 24), (0x6FFFFFFF, 2, 0, 2), (0x6FFFFFFE, 1, len(files), 0), (6, 1, 0, 16)]
    sh = b"\0" * 64 + b"".join(struct.pack("<IIQQQQIIQQ", 0, t, 2, 0, o, len(p), link, info, 8, ent) for (t, link, info, ent), o, p in zip(kinds, offs, parts))
    header = b"\x7fELF\x02\x01\x01" + b"\0" * 9 + struct.pack("<HHIQQQIHHHHHH", 3, 62, 1, 0, 0, shoff, 0, 64, 56, 0, 64, len(kinds) + 1, 0)
    return header + body + sh


LIBC = [("malloc", "GLIBC_2.2.5", "libc.so.6"), ("socket", "GLIBC_2.2.5", "libc.so.6")]


def linux(xul_undefined=(), xul_needed=("libnss3.so", "libc.so.6"), **more):
    """A tiny Linux package whose libxul.so needs libc and libnss3.so (a library of the package); libmozsandbox.so is in the package, not needed by libxul."""
    files = package(**{"libxul.so": make_elf(needed=xul_needed, soname="libxul.so", undefined=LIBC + list(xul_undefined)),
                       "libnss3.so": make_elf(needed=("libc.so.6",), soname="libnss3.so", undefined=LIBC, defined=["NSS_Init", "CERT_NewCert", "PR_Lock"]),
                       "libmozsandbox.so": make_elf(soname="libmozsandbox.so", defined=["SandboxHook"])})
    files.update(more)
    return files


def windows(xul_imports=None, xul_delay=None, **more):
    """A tiny Windows package: xul.dll imports from kernel32.dll and mozglue.dll (a DLL of the package) and delay-loads user32.dll."""
    files = {"firefox.exe": make_pe({"kernel32.dll": ["GetProcAddress"], "mozglue.dll": ["moz_xmalloc"]}),
             "xul.dll": make_pe(dict({"kernel32.dll": ["CreateFileW", "CloseHandle"], "mozglue.dll": ["moz_xmalloc"]}, **(xul_imports or {})),
                                dict({"user32.dll": ["GetDC"]}, **(xul_delay or {}))),
             "mozglue.dll": make_pe({"kernel32.dll": ["HeapAlloc"]}, exports=["moz_xmalloc", "moz_free"], forwarded=["moz_forwarded"]),
             "api-ms-win-crt-math-l1-1-0.dll": make_pe(exports=["cbrt", "sqrt"]),
             "omni.ja": make_ja({"modules/juggler/Helper.js": b"h\n"})}
    files.update(more)
    return files


def test_the_pe_reader_reads_imports_by_name_and_ordinal_delay_loads_and_exports_without_forwarders():
    for wide in (True, False):
        link = ab_package.pe_linkage(make_pe({"KERNEL32.dll": ["CreateFileW", 17]}, {"user32.dll": ["GetDC"]}, exports=["a", "b"], forwarded=["c"], wide=wide))
        assert link["imports"] == {"kernel32.dll": ["#17", "CreateFileW"]} and link["delay_imports"] == {"user32.dll": ["GetDC"]}, link
        assert link["exports"] == ["#1", "#2", "a", "b"], link["exports"]
    assert "error" in ab_package.linkage("dll", PE) and "error" in ab_package.linkage("dll", make_pe({"k.dll": ["F"]})[:0x220])


def test_the_elf_reader_reads_versioned_and_unversioned_needs_dt_needed_and_exports():
    link = ab_package.elf_linkage(make_elf(needed=("libc.so.6", "libgtk-3.so.0"), soname="libx.so", defined=["mine"],
                                           undefined=[("getifaddrs", "GLIBC_2.3", "libc.so.6"), ("malloc", "GLIBC_2.2.5", "libc.so.6"), ("gtk_init", None, None)]))
    assert link == {"soname": "libx.so", "needed": ["libc.so.6", "libgtk-3.so.0"], "exports": ["mine"],
                    "imports": {"": ["gtk_init"], "libc.so.6": ["getifaddrs@GLIBC_2.3", "malloc@GLIBC_2.2.5"]}}, link
    assert ab_package.elf_linkage(ELF + b"\0" * 32) == {"soname": None, "needed": [], "imports": {}, "exports": []}  # no sections, no dynamic segment


def test_a_new_imported_function_of_a_system_dll_is_red_the_delay_loaded_too():
    for new in (windows(xul_imports={"iphlpapi.dll": ["GetAdaptersAddresses"]}), windows(xul_delay={"iphlpapi.dll": ["GetAdaptersAddresses"]})):
        report = compare(windows(), new, zipped=True)
        assert report["verdict"] == "red" and report["red"] == {"new_host_import": 1}, report["red"]
        assert report["new_imports"] == [{"path": "xul.dll", "library": "iphlpapi.dll", "symbol": "GetAdaptersAddresses", "provider": None}]
        assert "RED: a new call into the host" in ab_package.summary(report)


def test_a_function_moved_to_the_delay_load_table_is_not_a_new_call():
    moved = windows(**{"xul.dll": make_pe({"kernel32.dll": ["CreateFileW"], "mozglue.dll": ["moz_xmalloc"]}, {"user32.dll": ["GetDC"], "kernel32.dll": ["CloseHandle"]})})
    report = compare(windows(), moved, zipped=True)
    assert report["verdict"] == "green" and report["counts"]["changed_binary"] == 1 and report["new_imports"] == report["gone_imports"] == [], report


def test_an_import_that_is_gone_is_reported_and_green():
    report = compare(windows(xul_imports={"iphlpapi.dll": ["GetAdaptersAddresses"]}), windows(), zipped=True)
    assert report["verdict"] == "green" and report["gone_imports"] == [{"path": "xul.dll", "library": "iphlpapi.dll", "symbol": "GetAdaptersAddresses"}]
    assert "gone import" in ab_package.summary(report)


def test_a_new_import_that_a_dll_of_the_package_exports_is_not_red_but_the_ucrt_a_forwarder_and_a_missing_export_are():
    report = compare(windows(), windows(xul_imports={"mozglue.dll": ["moz_xmalloc", "moz_free"]}), zipped=True)
    assert report["verdict"] == "green" and report["new_imports"] == [{"path": "xul.dll", "library": "mozglue.dll", "symbol": "moz_free", "provider": "mozglue.dll"}]
    for imports in ({"mozglue.dll": ["moz_xmalloc", "moz_forwarded"]}, {"mozglue.dll": ["moz_xmalloc", "moz_absent"]}, {"api-ms-win-crt-math-l1-1-0.dll": ["cbrt"]}):
        assert compare(windows(), windows(xul_imports=imports), zipped=True)["red"] == {"new_host_import": 1}, imports


def test_a_new_versioned_symbol_of_the_system_is_red():
    report = compare(linux(), linux([("getifaddrs", "GLIBC_2.3", "libc.so.6")]))
    assert report["verdict"] == "red" and report["red"] == {"new_host_import": 1}, report["red"]
    assert report["new_imports"] == [{"path": "libxul.so", "library": "libc.so.6", "symbol": "getifaddrs@GLIBC_2.3", "provider": None}]


def test_a_symbol_that_a_library_of_the_package_defines_is_not_red():
    for extra in ([("CERT_NewCert", "NSS_3.2", "libnss3.so")], [("PR_Lock", None, None)]):
        report = compare(linux(), linux(extra))
        assert report["verdict"] == "green" and report["new_imports"][0]["provider"] == "libnss3.so", report
    # unversioned and defined only by a library of the package that libxul does not load: the dynamic linker looks for it in the host
    assert compare(linux(), linux([("SandboxHook", None, None)]))["red"] == {"new_host_import": 1}
    # versioned against a library of the package that does not define it
    assert compare(linux(), linux([("NSS_Absent", "NSS_3.2", "libnss3.so")]))["red"] == {"new_host_import": 1}


def test_a_new_dt_needed_of_the_system_is_red_one_of_the_package_is_reported_a_gone_one_too():
    report = compare(linux(), linux(xul_needed=("libnss3.so", "libc.so.6", "libdbus-1.so.3")))
    assert report["red"] == {"new_host_library": 1} and report["new_needed"] == [{"path": "libxul.so", "library": "libdbus-1.so.3", "provider": None}]
    report = compare(linux(), linux(xul_needed=("libnss3.so", "libc.so.6", "libmozsandbox.so"), xul_undefined=[("SandboxHook", None, None)]))
    assert report["verdict"] == "green" and report["new_needed"][0]["provider"] == "libmozsandbox.so", report
    report = compare(linux(xul_needed=("libnss3.so", "libc.so.6", "libdbus-1.so.3")), linux())
    assert report["verdict"] == "green" and report["gone_needed"] == [{"path": "libxul.so", "library": "libdbus-1.so.3"}]


def test_a_table_the_candidate_cannot_read_is_red_unless_the_published_one_could_not_be_read_either():
    report = compare(linux(), linux(**{"libxul.so": ELF[:5] + b"\x09" + ELF[6:] + b"\0" * 32}))
    assert report["red"] == {"linkage_unreadable": 1}, report["red"]
    report = compare(windows(**{"xul.dll": PE + b"1"}), windows(**{"xul.dll": PE + b"2"}), zipped=True)
    assert report["verdict"] == "green" and report["linkage_unreadable"][0]["red"] is False


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
