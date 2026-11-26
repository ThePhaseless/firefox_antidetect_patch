#!/usr/bin/env python3
"""A release keeps its crash symbols as release assets, and a client can never mistake them for the engine.

What publish.yml does with `symbols-<leg>` (scripts/ci/release_symbols.py), each case red on the tree before it:

  * the BuildID in `symbols-<os>-<arch>-<BuildID>.zip` is the package's own, read from its application.ini (a zip and a tar.gz, the shallowest ini);
  * a release whose symbols are missing, ambiguous, or describe other binaries than the package that ships is refused (the function, and the workflow's steps:
    by name, no skip, no `|| true`, before the release is created);
  * symbols.sha256 lists exactly the symbols zips;
  * no symbols name matches the engine's glob `firefox-*-stealth-*`, the seal's NAME_RE or a name `scripts/ci assets` expects, and checksums.txt never lists one.
    The core's own resolver of an engine asset is not in this tree: it must stay on `firefox-*-stealth-*` (the glob of checksums.txt), and this file is where a
    symbols name is held away from every pattern known here;
  * release.yml keeps a release's symbols 30 days and a candidate's 2.

    python3 scripts/ci/test_release_symbols.py
"""
from __future__ import annotations

import fnmatch
import io
import json
import re
import struct
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

WORKFLOWS = HERE.parent.parent / ".github" / "workflows"
BUILD = "20261126101112"
LEG_NAMES = ("win-x86_64", "linux-x86_64")


def load(name):
    import yaml

    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def step(doc, job, name):
    found = [s for s in doc["jobs"][job]["steps"] if str(s.get("name", "")).startswith(name)]
    if len(found) != 1:
        raise KeyError("%s: %d steps start with %r" % (job, len(found), name))
    return found[0]


def elf(build_id: bytes) -> bytes:
    data = bytearray(0x200)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", data, 0x28, 0x100)
    struct.pack_into("<HH", data, 0x3A, 64, 2)
    note = struct.pack("<III", 4, len(build_id), 3) + b"GNU\0" + build_id
    struct.pack_into("<IIQQQQ", data, 0x100 + 64, 0, 7, 0, 0, 0x180, len(note))
    data[0x180:0x180 + len(note)] = note
    return bytes(data)


def ini(build: str = BUILD) -> bytes:
    return ("[App]\nVendor=Mozilla\nVersion=159.0\nBuildID=%s\n" % build).encode()


def tar_package(path: Path, files: dict) -> Path:
    with tarfile.open(path, "w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo("./" + name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return path


def zip_package(path: Path, files: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def symbols_zip(path: Path, binaries: dict) -> Path:
    import symbols_match as sm

    with zipfile.ZipFile(path, "w") as z:
        for name, data in binaries.items():
            z.writestr("%s/%s/%s.sym" % (name, sm.elf_debug_id(data), name), "MODULE Linux x86_64 %s %s\n" % (sm.elf_debug_id(data), name))
    return path


def refused(fn) -> str:
    """The message of the SymbolsError `fn` raises, '' when it raises none."""
    import release_symbols as rs

    try:
        fn()
    except rs.SymbolsError as exc:
        return str(exc) or "refused"
    return ""


def _cases() -> list:
    out = []

    def add(name, fn):
        try:
            ok = bool(fn())
            note = ""
        except Exception as exc:  # a tree without the code is a FAIL that says so, one per case
            ok, note = False, " [%s: %s]" % (type(exc).__name__, exc)
        out.append((name + note, ok))

    def import_rs():
        import release_symbols
        return release_symbols

    # --- the BuildID is the package's: read from application.ini ---------------------------------------------------------------------------------------
    def build_id_reads_the_package():
        rs = import_rs()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            z = zip_package(tmp / "p.zip", {"firefox/application.ini": ini("20261126101112"), "firefox/other/application.ini": ini("20200101000000")})
            g = tar_package(tmp / "p.tar.gz", {"firefox/application.ini": ini("20261127000001"), "firefox/gmp/application.ini": ini("20200101000000")})
            return rs.build_id(z) == "20261126101112" and rs.build_id(g) == "20261127000001"
    add("build id: a zip's and a tar.gz's is the BuildID of its shallowest application.ini", build_id_reads_the_package)

    def build_id_refuses():
        rs = import_rs()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            none = zip_package(tmp / "a.zip", {"firefox/xul.dll": b"MZ"})
            short = zip_package(tmp / "b.zip", {"firefox/application.ini": ini("123")})
            missing = zip_package(tmp / "c.zip", {"firefox/application.ini": b"[App]\nVersion=1\n"})
            return all(refused(lambda p=p: rs.build_id(p)) for p in (none, short, missing)) and "no application.ini" in refused(lambda: rs.build_id(none))
    add("build id: no application.ini, no BuildID, or one that is not 14 digits is refused, never guessed", build_id_refuses)

    def name_has_the_build_id():
        rs = import_rs()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            package = tar_package(tmp / "firefox-159.0-stealth-linux-x86_64.tar.gz",
                                  {"firefox/application.ini": ini("20261126101112"), "firefox/libxul.so": elf(bytes(range(1, 21)))})
            symbols = tmp / "symdl"
            symbols.mkdir()
            symbols_zip(symbols / "target.crashreporter-symbols.zip", {"libxul.so": elf(bytes(range(1, 21)))})
            made = rs.release("linux-x86_64", package, symbols, tmp / "sym")
            return (made.name == "symbols-linux-x86_64-" + rs.build_id(package) + ".zip" == "symbols-linux-x86_64-20261126101112.zip"
                    and made.read_bytes() == (symbols / "target.crashreporter-symbols.zip").read_bytes()
                    and rs.symbols_name("win-x86_64", BUILD) == "symbols-win-x86_64-%s.zip" % BUILD)
    add("name: the symbols of a leg are copied to symbols-<os>-<arch>-<BuildID>.zip with the BuildID of the package that ships", name_has_the_build_id)

    # --- a release whose symbols are missing or do not describe the package is refused --------------------------------------------------------------------
    def refuses_other_binaries_and_odd_counts():
        rs = import_rs()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            package = tar_package(tmp / "firefox-159.0-stealth-linux-x86_64.tar.gz",
                                  {"firefox/application.ini": ini(), "firefox/libxul.so": elf(bytes(range(1, 21)))})
            other = tmp / "other"
            other.mkdir()
            symbols_zip(other / "s.zip", {"libxul.so": elf(bytes(range(21, 41)))})
            empty = tmp / "empty"
            empty.mkdir()
            two = tmp / "two"
            two.mkdir()
            symbols_zip(two / "a.zip", {"libxul.so": elf(bytes(range(1, 21)))})
            symbols_zip(two / "b.zip", {"libxul.so": elf(bytes(range(1, 21)))})
            absent = tmp / "absent"
            said = refused(lambda: rs.release("linux-x86_64", package, other, tmp / "sym"))
            return ("do not describe" in said and refused(lambda: rs.release("linux-x86_64", package, empty, tmp / "sym"))
                    and refused(lambda: rs.release("linux-x86_64", package, two, tmp / "sym"))
                    and refused(lambda: rs.release("linux-x86_64", package, absent, tmp / "sym"))
                    and not (tmp / "sym").exists())
    add("refusal: symbols of other binaries, none, two, or a missing folder are refused, and nothing is written for them", refuses_other_binaries_and_odd_counts)

    def cli_refuses():
        import subprocess
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "empty").mkdir()
            package = zip_package(tmp / "firefox-159.0-stealth-win-x86_64.zip", {"firefox/application.ini": ini()})
            run = subprocess.run([sys.executable, str(HERE / "__main__.py"), "symbols-release", "--leg", "win-x86_64", "--package", str(package),
                                  "--symbols", str(tmp / "empty"), "--out", str(tmp / "sym")], capture_output=True, text=True)
            return run.returncode == 1 and "ERROR:" in run.stderr
    add("refusal: `scripts/ci symbols-release` exits 1 with an ERROR line when the symbols are not there", cli_refuses)

    # --- symbols.sha256 lists exactly the symbols zips ------------------------------------------------------------------------------------------------
    def seal_lists_the_zips():
        rs = import_rs()
        import hashlib
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / ("symbols-linux-x86_64-%s.zip" % BUILD)).write_bytes(b"one")
            (tmp / ("symbols-win-x86_64-%s.zip" % BUILD)).write_bytes(b"two")
            (tmp / "firefox-159.0-stealth-linux-x86_64.tar.gz").write_bytes(b"engine")
            (tmp / "notes.txt").write_bytes(b"x")
            rs.seal(tmp)
            lines = (tmp / "symbols.sha256").read_text(encoding="utf-8").splitlines()
            want = sorted("%s  symbols-%s-%s.zip" % (hashlib.sha256(d).hexdigest(), leg, BUILD) for leg, d in (("linux-x86_64", b"one"), ("win-x86_64", b"two")))
            empty = tmp / "e"
            empty.mkdir()
            return sorted(lines) == want and bool(refused(lambda: rs.seal(empty)))
    add("sha256: symbols.sha256 lists exactly the symbols zips (not the engine, not itself), and an empty folder is refused", seal_lists_the_zips)

    # --- no symbols name is an engine asset, and checksums.txt never lists one -----------------------------------------------------------------------------
    def names_never_match_an_engine_pattern():
        rs = import_rs()
        import legs
        import make_seal
        engine = [l.asset(legs.tree_version()) for l in legs.LEGS]
        symbols = [rs.symbols_name(l.leg, BUILD) for l in legs.LEGS] + [rs.SHA_FILE]
        return (engine and rs.ENGINE_GLOB == "firefox-*-stealth-*"
                and all(fnmatch.fnmatchcase(a, rs.ENGINE_GLOB) and make_seal.NAME_RE.match(a) for a in engine)
                and not any(fnmatch.fnmatchcase(n, rs.ENGINE_GLOB) or make_seal.NAME_RE.match(n) for n in symbols)
                and not any(fnmatch.fnmatchcase(n, "firefox-*-stealth-%s.*" % l.leg) for n in symbols for l in legs.LEGS))
    add("patterns: the names `scripts/ci assets` expects match `firefox-*-stealth-*` and the seal's NAME_RE; no symbols name or symbols.sha256 does, nor `firefox-*-stealth-<leg>.*`",
        names_never_match_an_engine_pattern)

    def guard_works():
        rs = import_rs()
        engine = "firefox-159.0-stealth-win-x86_64.zip"
        good = "%s  %s\n" % ("a" * 64, engine)
        listed = good + "%s  symbols-win-x86_64-%s.zip\n" % ("b" * 64, BUILD)
        starred = good + "%s *symbols.sha256\n" % ("c" * 64)
        clash = ["firefox-1-stealth-symbols-win-x86_64.zip"]
        return (rs.guard([engine, "symbols-win-x86_64-%s.zip" % BUILD, "symbols.sha256"], good) is None
                and bool(refused(lambda: rs.guard([engine], listed))) and bool(refused(lambda: rs.guard([engine], starred)))
                and bool(refused(lambda: rs.guard(clash, good))) and rs.guard([engine], "") is None)
    add("guard: a checksums.txt that lists a symbols file is refused, and so is a symbols name that the engine's glob matches", guard_works)

    # --- the workflows -----------------------------------------------------------------------------------------------------------------------------------
    pub, rel = load("publish.yml"), load("release.yml")
    steps = pub["jobs"]["publish"]["steps"]
    names = [s.get("name", "") for s in steps]

    def at(prefix):
        return next(i for i, n in enumerate(names) if n.startswith(prefix))

    def binds(s):
        run = s.get("run", "")
        return "continue-on-error" not in s and "if" not in s and "|| true" not in run and "set +e" not in run

    def fetches_through_the_function():
        s = step(pub, "publish", "The crash symbols of the release, from its own assets")
        env = s["env"]
        return (binds(s) and s["run"].strip() == 'python3 _src/scripts/ci symbols-fetch --tag "$TAG" --repo "$GITHUB_REPOSITORY" --build-run "$BUILD_RUN" --dest symdl'
                and env["TAG"] == "${{ inputs.tag }}" and env["BUILD_RUN"] == "${{ inputs.build_run_id }}"
                and not any("download-artifact" in str(x.get("uses", "")) and "symbols" in str(x.get("with") or {}) for x in steps)
                and "release_symbols.fetch(" in (HERE / "__main__.py").read_text(encoding="utf-8"))
    add("publish: the symbols come from `scripts/ci symbols-fetch` (release_symbols.fetch), no download-artifact by pattern, and its step binds", fetches_through_the_function)

    def republish_uses_that_step():
        rep = load("republish.yml")["jobs"]["publish"]
        return (rep["uses"] == "./.github/workflows/publish.yml" and rep["with"]["build_run_id"] == "${{ inputs.build_run_id }}"
                and rep["with"]["tag"] == "${{ needs.plan.outputs.tag }}" and rep["permissions"]["contents"] == "write" and "if" not in rep)
    add("republish: it calls publish.yml with the old build run and the tag, with the right to read a draft release: the step above is its symbols", republish_uses_that_step)

    # --- where the symbols come from: the release's own assets, then the build run's artifact, then red -----------------------------------------------
    class FakeGh:
        """gh, as release_symbols calls it. release: None (not found) or {asset name: bytes}; artifacts: {leg: zip bytes}; fail: an error text for `release view`."""

        def __init__(self, release=None, artifacts=None, fail=""):
            self.release, self.artifacts, self.fail, self.calls = release, artifacts or {}, fail, []

        def __call__(self, args, binary=False):
            self.calls.append(list(args))
            if args[:2] == ["release", "view"]:
                if self.fail:
                    return 1, "", self.fail
                if self.release is None:
                    return 1, "", "release not found"
                return 0, json.dumps({"assets": [{"name": n} for n in self.release]}), ""
            if args[:2] == ["release", "download"]:
                out = Path(args[args.index("--dir") + 1])
                for name, data in self.release.items():
                    if any(fnmatch.fnmatchcase(name, args[i + 1]) for i, a in enumerate(args) if a == "--pattern"):
                        (out / name).write_bytes(data)
                return 0, "", ""
            if args[0] == "api" and "artifacts?name=symbols-" in args[1]:
                leg = args[1].split("name=symbols-")[1]
                return 0, ("%s-id" % leg if leg in self.artifacts else ""), ""
            if args[0] == "api" and args[1].endswith("/zip"):
                leg = args[1].split("/artifacts/")[1].split("-id")[0]
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z:
                    z.writestr("x.crashreporter-symbols.zip", self.artifacts[leg])
                return 0, buf.getvalue(), ""
            return 1, "", "unexpected %r" % (args,)

    def release_assets(**override):
        import hashlib
        files = {"symbols-linux-x86_64-%s.zip" % BUILD: b"linux zip", "symbols-win-x86_64-%s.zip" % BUILD: b"win zip"}
        files.update(override.get("files", {}))
        listed = override.get("listed", files)
        sha = "".join("%s  %s\n" % (hashlib.sha256(d).hexdigest(), n) for n, d in sorted(listed.items())).encode()
        out = dict(files)
        if override.get("sha", True):
            out["symbols.sha256"] = override.get("sha_bytes", sha)
        out["firefox-159.0-stealth-win-x86_64.zip"] = b"engine"
        return out

    def run_fetch(gh):
        import release_symbols as rs
        with tempfile.TemporaryDirectory() as t:
            try:
                where = rs.fetch(list(LEG_NAMES), "firefox-70", "o/r", "123", Path(t) / "symdl", gh)
            except rs.SymbolsError as exc:
                return "REFUSED " + str(exc), [], gh
            got = sorted(str(p.relative_to(Path(t) / "symdl")).replace("\\", "/") for p in (Path(t) / "symdl").rglob("*") if p.is_file())
            return where, got, gh

    def release_first():
        where, got, gh = run_fetch(FakeGh(release=release_assets(), artifacts={"win-x86_64": b"a", "linux-x86_64": b"b"}))
        return (where == "the assets of release firefox-70"
                and got == ["linux-x86_64/symbols-linux-x86_64-%s.zip" % BUILD, "win-x86_64/symbols-win-x86_64-%s.zip" % BUILD]
                and not any(c[0] == "api" for c in gh.calls))
    add("fetch: a release that has symbols assets gives them (sha256 verified), and the build run's artifacts are not asked for", release_first)

    def artifact_when_no_assets():
        where, got, gh = run_fetch(FakeGh(release=None, artifacts={"win-x86_64": b"a", "linux-x86_64": b"b"}))
        older = run_fetch(FakeGh(release={"firefox-159.0-stealth-win-x86_64.zip": b"e", "seal.json": b"{}"}, artifacts={"win-x86_64": b"a", "linux-x86_64": b"b"}))
        by_name = [c[1] for c in gh.calls if c[0] == "api" and "artifacts?name=" in c[1]]
        return (where.startswith("the artifacts symbols-<leg> of run 123") and got == ["linux-x86_64/x.crashreporter-symbols.zip", "win-x86_64/x.crashreporter-symbols.zip"]
                and by_name == ["repos/o/r/actions/runs/123/artifacts?name=symbols-win-x86_64", "repos/o/r/actions/runs/123/artifacts?name=symbols-linux-x86_64"]
                and older[0].startswith("the artifacts") and older[1] == got)
    add("fetch: no release, or a release published before the symbols were kept (none of their assets), falls back to the build run's artifact by name", artifact_when_no_assets)

    def red_when_nothing_survives():
        said, got, _ = run_fetch(FakeGh(release=None, artifacts={"win-x86_64": b"a"}))
        both, _, _ = run_fetch(FakeGh(release={"seal.json": b"{}"}))
        return (said.startswith("REFUSED") and "do not survive" in said and "symbols-linux-x86_64" in said and "symbols-win-x86_64" not in said
                and both.startswith("REFUSED") and "do not survive" in both and got == [])
    add("fetch: no symbols assets and an artifact that is gone is red with a message that says the release's symbols do not survive, never a silent pass", red_when_nothing_survives)

    def a_release_that_cannot_be_read_is_red():
        said, _, gh = run_fetch(FakeGh(fail="HTTP 502: Bad Gateway", artifacts={"win-x86_64": b"a", "linux-x86_64": b"b"}))
        return said.startswith("REFUSED") and "502" in said and not any(c[0] == "api" for c in gh.calls)
    add("fetch: a release GitHub cannot answer for (5xx, auth) is red and does not fall back to the artifact", a_release_that_cannot_be_read_is_red)

    def sha_mismatch_is_red():
        bad = run_fetch(FakeGh(release=release_assets(files={"symbols-linux-x86_64-%s.zip" % BUILD: b"a changed zip"},
                                                      listed={"symbols-linux-x86_64-%s.zip" % BUILD: b"linux zip", "symbols-win-x86_64-%s.zip" % BUILD: b"win zip"}),
                               artifacts={"win-x86_64": b"a", "linux-x86_64": b"b"}))
        return bad[0].startswith("REFUSED") and "symbols.sha256 says" in bad[0] and "symbols-linux-x86_64" in bad[0] and not any(c[0] == "api" for c in bad[2].calls)
    add("fetch: a zip whose sha256 differs from symbols.sha256 is red, and the artifact is not a way round it", sha_mismatch_is_red)

    def missing_or_odd_sha_file_is_red():
        no_sha = run_fetch(FakeGh(release=release_assets(sha=False), artifacts={"win-x86_64": b"a", "linux-x86_64": b"b"}))
        short = run_fetch(FakeGh(release=release_assets(listed={"symbols-win-x86_64-%s.zip" % BUILD: b"win zip"})))
        junk = run_fetch(FakeGh(release=release_assets(sha_bytes=b"not a sha line\n")))
        extra = run_fetch(FakeGh(release=release_assets(files={"symbols-macos-arm64-%s.zip" % BUILD: b"mac"})))
        return (no_sha[0].startswith("REFUSED") and "no symbols.sha256" in no_sha[0] and not any(c[0] == "api" for c in no_sha[2].calls)
                and short[0].startswith("REFUSED") and junk[0].startswith("REFUSED") and extra[0].startswith("REFUSED"))
    add("fetch: symbols zips with no symbols.sha256, a list that misses a zip, a line that is no sha256 and a zip of no leg are all red", missing_or_odd_sha_file_is_red)

    def republished_names_are_the_same():
        rs = import_rs()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            package = tar_package(tmp / "firefox-159.0-stealth-linux-x86_64.tar.gz", {"firefox/application.ini": ini(), "firefox/libxul.so": elf(bytes(range(1, 21)))})
            name = "symbols-linux-x86_64-%s.zip" % BUILD
            (tmp / "sd").mkdir()
            symbols_zip(tmp / "sd" / name, {"libxul.so": elf(bytes(range(1, 21)))})
            made = rs.release("linux-x86_64", package, tmp / "sd", tmp / "sym")
            (tmp / "other").mkdir()
            symbols_zip(tmp / "other" / "symbols-linux-x86_64-20200101000000.zip", {"libxul.so": elf(bytes(range(1, 21)))})
            return made.name == name and refused(lambda: rs.release("linux-x86_64", package, tmp / "other", tmp / "sym2"))
    add("republish: symbols taken from a release are attached under the same name, and one named for another BuildID than the package's is red", republished_names_are_the_same)

    def match_again_and_name():
        s = step(pub, "publish", "The crash symbols describe the archives that ship")
        run = s["run"]
        return (binds(s) and "set -euo pipefail" in run
                and 'symbols-release --leg "$leg" --package "dl/$(python3 _src/scripts/ci asset --leg "$leg")" --symbols "symdl/$leg" --out sym' in run
                and "symbols-seal --dir sym" in run
                and at("Assert all 3 target archives present") < at("The crash symbols of the release") < at("The crash symbols describe the archives that ship")
                < at("Generate checksums.txt") < at("No symbols file is an engine archive") < at("Create DRAFT release"))
    add("publish: the symbols are checked again against each leg's downloaded package, named by its BuildID, listed in symbols.sha256, before the release is created",
        match_again_and_name)

    def checksums_never_list_them():
        rs = import_rs()
        s = step(pub, "publish", "Generate checksums.txt")
        m = re.search(r"sha256sum (\S+) > checksums\.txt", s["run"])
        sample = [rs.symbols_name(leg, BUILD) for leg in LEG_NAMES] + [rs.SHA_FILE]
        return m and "cd dl" in s["run"] and m.group(1) == "firefox-*-stealth-*" and not any(fnmatch.fnmatchcase(n, m.group(1)) for n in sample)
    add("checksums: the explicit glob of checksums.txt is firefox-*-stealth-*, run in dl, and no symbols name matches it", checksums_never_list_them)

    def guard_step():
        s = step(pub, "publish", "No symbols file is an engine archive")
        return binds(s) and s["run"].strip() == "python3 _src/scripts/ci symbols-guard --dir dl --dir sym --checksums dl/checksums.txt"
    add("checksums: a guard step after checksums.txt fails if a symbols name matches the glob or checksums.txt lists one", guard_step)

    def release_assets():
        rs = import_rs()
        s = step(pub, "publish", "Create DRAFT release")
        files = [l.strip() for l in s["with"]["files"].splitlines() if l.strip()]
        seal = step(pub, "publish", "Generate + gate seal.json")["run"]
        sample = rs.symbols_name("win-x86_64", BUILD)
        from_dl = [f for f in files if f.startswith("dl/")]
        return ("sym/symbols-*.zip" in files and "sym/symbols.sha256" in files and s["with"]["fail_on_unmatched_files"] is True
                and not any(fnmatch.fnmatchcase("sym/" + sample, f) or fnmatch.fnmatchcase("sym/symbols.sha256", f) for f in from_dl)
                and "--assets dl" in seal and "sym/" not in seal and "symdl" not in seal)
    add("release: the zips and symbols.sha256 are attached beside the assets (sym/), an unmatched file is an error, and the seal reads dl/ only", release_assets)

    def retention():
        s = step(rel, "build", "Upload crash symbols")
        return (str(s["with"]["retention-days"]).replace(" ", "") == "${{needs.plan.outputs.kind=='release'&&30||2}}" and s["with"]["name"] == "symbols-${{ matrix.leg }}"
                and s["with"]["if-no-files-found"] == "error")
    add("release.yml: a release's symbols artifact is kept 30 days so publish can fetch it, a candidate's 2", retention)

    def package_ab_takes_the_engine_only():
        text = (WORKFLOWS / "package-ab.yml").read_text(encoding="utf-8")
        cmds = [l for l in text.splitlines() if "gh release download" in l and "--dir" in l and "checksums.txt" in l]
        return len(cmds) == 2 and all("-p 'firefox-*-stealth-*'" in l and "'*.zip'" not in l for l in cmds)
    add("package-ab: a release's archives are downloaded as `firefox-*-stealth-*`, not `*.zip`: the symbols (~400 MB each) are not engine files", package_ab_takes_the_engine_only)
    return out


def cases() -> list:
    return _cases()


def main() -> int:
    failures = 0
    found = cases()
    for name, ok in found:
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok
    print("%d/%d cases as expected" % (len(found) - failures, len(found)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
