#!/usr/bin/env python3
"""The map of diagnostics.yml: which hook does a suite execute (scripts/ci/coverage_map.py), the export of a suite's profiles
(scripts/ci/gcov_export.py), the coverage .mozconfig, and the workflow that runs them.

    python3 scripts/ci/test_coverage_map.py          (the plan job of diagnostics.yml; scripts/ci/test_ci.py takes cases() too)
    python -m pytest scripts/ci/test_coverage_map.py

Tiny fixtures: a series of two folders, a few sources, two suites' lcov exports.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import coverage_map as cm  # noqa: E402
import coverage_mozconfig  # noqa: E402
import gcov_export as ge  # noqa: E402
import mozconfig  # noqa: E402

WORKFLOW = HERE.parent.parent / ".github" / "workflows" / "diagnostics.yml"

A_CPP = """\
#include "a.h"
void Foo() {
  Work();
  DoA();  // STEALTH-HOOK(feat/a)
}
void Bar() {
  Work();
  DoB();
  Log();
}
"""
DUP_CPP = """\
void First() {
  Log();
  Work();
}
void Second() {
  Work();
  Log();
}
"""
IFDEF_CPP = """\
void Gated() {
  Work();
#ifdef MOZ_NOT_ON_LINUX
  Other();
  Third();
#endif
  if (Check()) {
    Act();
  }
}
"""
# the two suites' exports: suiteA counts Foo's hook line (4), suiteB counts Bar's Log (9) and the second Log of dup.cpp (7)
SUITE_A = """\
TN:suiteA
SF:/node/src/dom/a.cpp
FN:2,Foo
FNDA:3,Foo
FN:6,Bar
FNDA:0,Bar
DA:3,3
DA:4,3
DA:7,0
DA:8,0
DA:9,0
end_of_record
SF:/node/src/dom/dup.cpp
DA:2,1
DA:3,1
DA:6,0
DA:7,0
end_of_record
SF:/node/src/dom/gated.cpp
DA:2,1
DA:7,1
DA:8,0
end_of_record
"""
SUITE_B = """\
TN:suiteB
SF:/node/src/dom/a.cpp
FN:2,Foo
FNDA:0,Foo
FN:6,Bar
FNDA:2,Bar
DA:3,0
DA:4,0
DA:7,2
DA:8,0
DA:9,2
end_of_record
SF:/node/src/dom/dup.cpp
DA:2,0
DA:3,0
DA:6,1
DA:7,1
end_of_record
SF:/node/src/dom/gated.cpp
DA:2,0
DA:7,0
DA:8,0
end_of_record
"""


def hook(file, function, line, kind="add", form="unknown"):
    return {"file": file, "function": function, "kind": kind, "form": form, "line": line, "test": ""}


def fixture(root: Path, hooks_a=None, hooks_b=None) -> dict:
    """A series, a source tree and the exports under `root`; the paths of the arguments of `map`."""
    series, src, prof = root / "series", root / "src", root / "profiles"
    for rel, text in {"dom/a.cpp": A_CPP, "dom/dup.cpp": DUP_CPP, "dom/gated.cpp": IFDEF_CPP,
                      "dom/windows_only.cpp": "void W() {\n  WinThing();\n}\n"}.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="utf-8", newline="\n")
    hooks_a = hooks_a if hooks_a is not None else [
        hook("dom/a.cpp", "void Foo() {", "  DoA();  // STEALTH-HOOK(feat/a)"),                  # suiteA only
        hook("dom/a.cpp", "void Bar() {", "  DoB();"),                                          # a counter, no suite counts it
        hook("dom/windows_only.cpp", "void W() {", "  WinThing();"),                           # in no export: not compiled
        hook("dom/a.cpp", "void Foo() {", "  }", form="unknown"),                              # a brace: no counter, takes the hook beside it
        hook("netwerk/x.rs", "fn x() {", "    do_it();"),                                    # Rust
        dict(hook("dom/a.cpp", "void Foo() {", "", kind="delete"), removed="  Old();"),       # a hook that deletes lines: no line of its own
    ]
    hooks_b = hooks_b if hooks_b is not None else [
        hook("dom/dup.cpp", "void Second() {", "  Log();"),                                    # the text repeats: the function says which
        hook("dom/gated.cpp", "void Gated() {", "  Third();"),                                # inside a #ifdef whose code has no counter
    ]
    for folder, hooks in (("feat/a", hooks_a), ("feat/b", hooks_b)):
        d = series / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "HOOKS.json").write_text(json.dumps(hooks), encoding="utf-8")
        (d / "MANIFEST.json").write_text(json.dumps({"modified": [], "added": {"dom/own.cpp": "100644", "dom/own.h": "100644", "x/y.py": "100644"}}),
                                         encoding="utf-8")
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "suiteA.info").write_text(SUITE_A, encoding="utf-8")
    (prof / "suiteB.info").write_text(SUITE_B, encoding="utf-8")
    (prof / "suiteA.meta.json").write_text(json.dumps({"rc": 0, "passed": True}), encoding="utf-8")
    (prof / "suiteB.meta.json").write_text(json.dumps({"rc": 1, "passed": False, "failures": 2}), encoding="utf-8")
    return {"profiles": prof, "source_root": src, "series_root": series}


def run(root: Path, **extra):
    """(exit code, stderr, rows by (file, text) of hooks.csv) of `map` over the fixture."""
    import csv
    paths = fixture(root, **{k: v for k, v in extra.items() if k in ("hooks_a", "hooks_b")})
    out = root / "out"
    argv = ["map", "--profiles", str(paths["profiles"]), "--source-root", str(paths["source_root"]), "--series-root", str(paths["series_root"]),
            "--out", str(out), "--run-id", "7", "--source-commit", "abc", "--series-commit", "def", "--strip-prefix", "/node/src",
            "--expect", "suiteA", "suiteB", "suiteC"]
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        code = cm.main(argv)
    from collections import defaultdict
    rows = defaultdict(lambda: defaultdict(str))  # a hook the map did not locate where it should be reads as empty, and the case is red by name
    if (out / "hooks.csv").is_file():
        with open(out / "hooks.csv", encoding="utf-8", newline="") as f:
            rows.update({(r["file"], r["function"], r["line"] or ""): r for r in csv.DictReader(f)})
    return code, err.getvalue(), rows, out


def cases() -> list:
    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    with tempfile.TemporaryDirectory() as tmp:
        code, err, rows, out_dir = run(Path(tmp))
        add("map: a clean run exits 0 (%s)" % err.strip()[:80], code == 0)
        by_text = {(r["file"], r["line"]): r for r in rows.values()}
        a = rows[("dom/a.cpp", "void Foo() {", "4")]
        add("map: a hook one suite executes is yes, and names that suite only", a["executed"] == "yes" and a["suites"] == "suiteA")
        n = rows[("dom/a.cpp", "void Bar() {", "8")]
        add("map: a hook with a counter that no suite counts is no", n["executed"] == "no" and n["suites"] == "")
        add("map: and it is in uncovered.txt, and the executed one is not",
            "dom/a.cpp:8" in (out_dir / "uncovered.txt").read_text(encoding="utf-8")
            and "dom/a.cpp:4" not in (out_dir / "uncovered.txt").read_text(encoding="utf-8"))
        w = rows[("dom/windows_only.cpp", "void W() {", "2")]
        add("map: a hook in a file that is not in the build is not-compiled, for that reason",
            w["executed"] == "not-compiled" and w["reason"] == cm.REASON_FILE)
        nc = (out_dir / "not_compiled.txt").read_text(encoding="utf-8")
        add("map: not_compiled.txt names the file and the reason", "windows_only.cpp" in nc and cm.REASON_FILE in nc)
        d = rows[("dom/dup.cpp", "void Second() {", "7")]
        add("map: a text that repeats in the file is found in the function the hook names (line 7, not 2)", d["suites"] == "suiteB" and d["executed"] == "yes")
        g = rows[("dom/gated.cpp", "void Gated() {", "5")]
        add("map: a hook in an #ifdef region whose code has no counter is not-compiled, for that reason",
            g["executed"] == "not-compiled" and g["reason"] == cm.REASON_IFDEF)
        b = rows[("dom/a.cpp", "void Foo() {", "5")]
        add("map: a closing brace takes the status of the hook line beside it", b["executed"] == "yes" and b["suites"] == "suiteA")
        r = rows[("netwerk/x.rs", "fn x() {", "")]
        add("map: a hook in Rust is not-instrumented, not no", r["executed"] == "not-instrumented")
        removed = [r for r in rows.values() if r["executed"] == "removed"]
        add("map: a hook that deletes lines has no line to find and is removed, not a failure", len(removed) == 1 and removed[0]["file"] == "dom/a.cpp")
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        add("map: meta has the commits, the run, the suites with their result and the suite that has no profile",
            meta["source_commit"] == "abc" and meta["series_commit"] == "def" and meta["run_id"] == "7"
            and meta["suites"]["suiteA"]["passed"] is True and meta["suites"]["suiteB"]["passed"] is False
            and meta["suites_without_profile"] == ["suiteC"])
        add("map: the INDEX row is one line under its header", len((out_dir / "index.csv").read_text(encoding="utf-8").splitlines()) == 2)
        own = (out_dir / "functions.csv").read_text(encoding="utf-8")
        add("map: functions.csv is of our own files only (dom/a.cpp is not one, dom/own.cpp has no function here)", own.splitlines() == ["file,function,line,executed,suites"])

    with tempfile.TemporaryDirectory() as tmp:
        code, err, _, _ = run(Path(tmp), hooks_b=[hook("dom/dup.cpp", "void Second() {", "  NotInTheFile();")])
        add("map: a hook text that is not in its file is a failure of the tool, and says which (%s)" % err.strip()[:70],
            code == 1 and "NotInTheFile" in err)

    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp))
        for f in Path(paths["profiles"]).glob("*"):
            f.unlink()
        err = io.StringIO()
        with redirect_stderr(err):
            code = cm.main(["map", "--profiles", str(paths["profiles"]), "--source-root", str(paths["source_root"]),
                            "--series-root", str(paths["series_root"]), "--out", str(Path(tmp) / "o")])
        add("map: no profile at all is a failure of the tool", code == 1 and "no profile" in err.getvalue())

    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp))
        (Path(paths["profiles"]) / "suiteA.info").write_text("TN:suiteA\n", encoding="utf-8")
        (Path(paths["profiles"]) / "suiteB.info").write_text("", encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err):
            code = cm.main(["map", "--profiles", str(paths["profiles"]), "--source-root", str(paths["source_root"]),
                            "--series-root", str(paths["series_root"]), "--out", str(Path(tmp) / "o")])
        add("map: profiles with no line in them are a failure of the tool", code == 1 and "no line" in err.getvalue())

    parsed = cm.parse_lcov(SUITE_A, "/node/src")
    add("lcov: the build machine's directory is stripped, lines and functions are read",
        sorted(parsed) == ["dom/a.cpp", "dom/dup.cpp", "dom/gated.cpp"] and parsed["dom/a.cpp"]["lines"][4] == 3
        and parsed["dom/a.cpp"]["functions"]["Foo"] == (2, 3))

    # the export of a suite's profiles
    topsrc = "/node/src"
    notes_bytes = b"\x01\x00\x00\x00" + b"/node/src/dom/a.cpp\x00" + b"\x00\x00\x00\x00/usr/include/c++/v1/vector.h\x00" + b"_ZN3Foo\x00x" + b"/node/src/obj-rel/x/Unified.cpp\x00"
    named = ge.files_named_in(notes_bytes, topsrc)
    add("notes: the sources a .gcno names are found by their paths, relative to the node's directory",
        named == {"dom/a.cpp", "obj-rel/x/Unified.cpp", "/usr/include/c++/v1/vector.h"})
    links = {"obj-rel/dist/include/mozilla/Foo.h": "dom/Foo.h"}
    exported = b"/node/src/obj-rel/dist/include/mozilla/Foo.h\x00/node/src/dom/a.cpp\x00"
    add("notes: an exported header is named by the source it links to (dist/include/mozilla/Foo.h is dom/Foo.h), or not found at all",
        ge.files_named_in(exported, topsrc, links) == {"dom/Foo.h", "dom/a.cpp"}
        and ge.files_named_in(exported, topsrc) == {"obj-rel/dist/include/mozilla/Foo.h", "dom/a.cpp"})
    with tempfile.TemporaryDirectory() as tmp:
        top = Path(tmp).resolve()
        (top / "dom").mkdir()
        (top / "dom" / "Foo.h").write_text("int x;", encoding="utf-8")
        (top / "obj-rel" / "dist" / "include" / "mozilla").mkdir(parents=True)
        try:
            (top / "obj-rel" / "dist" / "include" / "mozilla" / "Foo.h").symlink_to(top / "dom" / "Foo.h")
            found = ge.header_links(top / "obj-rel", str(top), {"dom/Foo.h"})
            add("notes: dist/include's links to the series' headers are read from the build's objdir (%s)" % found,
                found == {"obj-rel/dist/include/mozilla/Foo.h": "dom/Foo.h"})
        except OSError:
            add("notes: dist/include's links (no symlinks on this machine: not run)", True)
    doc = {"current_working_directory": "/node/src/obj-rel/dom", "files": [
        {"file": "/node/src/dom/a.cpp", "lines": [{"line_number": 4, "count": 2}, {"line_number": 5, "count": 0}],
         "functions": [{"name": "_Z3Foov", "demangled_name": "Foo()", "start_line": 2, "execution_count": 2}]},
        {"file": "../../dom/other.cpp", "lines": [{"line_number": 1, "count": 9}], "functions": []},
        {"file": "/usr/include/x.h", "lines": [{"line_number": 1, "count": 9}], "functions": []}]}
    got = ge.parse_gcov_json(doc, topsrc, {"dom/a.cpp", "dom/other.cpp"})
    add("export: llvm-cov's JSON gives the lines and the functions of the files of the series, and drops the others",
        sorted(got) == ["dom/a.cpp", "dom/other.cpp"] and got["dom/a.cpp"]["lines"] == {4: 2, 5: 0}
        and got["dom/a.cpp"]["functions"] == {"Foo()": (2, 2)} and got["dom/other.cpp"]["lines"] == {1: 9})
    again = ge.to_lcov(got, "s")
    back = cm.parse_lcov(again)
    add("export: what it writes is what the map reads", back["dom/a.cpp"]["lines"] == {4: 2, 5: 0} and back["dom/a.cpp"]["functions"]["Foo()"] == (2, 2))

    with tempfile.TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        (notes / "gcno" / "obj-rel" / "dom").mkdir(parents=True)
        (notes / "gcno" / "obj-rel" / "dom" / "u1.gcno").write_bytes(b"x")
        (notes / "gcno" / "obj-rel" / "dom" / "u2.gcno").write_bytes(b"x")
        (notes / "topsrcdir.txt").write_text(topsrc + "\n", encoding="utf-8")
        (notes / "interest.json").write_text(json.dumps(["dom/a.cpp"]), encoding="utf-8")
        profile = Path(tmp) / "gcda"
        (profile / "obj-rel" / "dom").mkdir(parents=True)
        calls = []

        def fake(cmd, **kw):
            calls.append(cmd)
            import subprocess
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"files": [{"file": "/node/src/dom/a.cpp", "lines": [{"line_number": 4, "count": 1}],
                                                                              "functions": []}]}), "")
        try:
            ge.export(notes, profile, "s", Path(tmp) / "o", run=fake)
            none = False
        except SystemExit as exc:
            none = "left no profile" in str(exc)
        add("export: a suite that left no profile is a failure, not an empty file", none and not calls)
        (profile / "obj-rel" / "dom" / "u1.gcda").write_bytes(b"y")
        (profile / "obj-rel" / "dom" / "u2.gcda").write_bytes(b"y")
        meta = ge.export(notes, profile, "s", Path(tmp) / "o", rc=1, run=fake)
        text = (Path(tmp) / "o" / "s.info").read_text(encoding="utf-8")
        add("export: each object with a profile is converted once, their counts add, and a red rc is a result (passed false)",
            len(calls) == 2 and "DA:4,2" in text and meta["gcda_files"] == 2 and meta["passed"] is False and meta["rc"] == 1)
        add("export: the converter is called on this object's own .gcno and .gcda",
            any("--gcno=%s" % (notes / "gcno" / "obj-rel" / "dom" / "u1.gcno") in c and "--gcda=%s" % (profile / "obj-rel" / "dom" / "u1.gcda") in c for c in calls))
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        bindir = Path(tmp) / "clang" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "llvm-cov").write_text("", encoding="utf-8")
        obj = Path(tmp) / "obj-rel"
        obj.mkdir()
        (obj / "config.status.json").write_text(json.dumps({"substs": {"CC": str(bindir / "clang") + " --target=x"}}), encoding="utf-8")

        def helper(text):
            return lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, text, "")
        good = ge.check_tools(obj, helper("  --json-format  Output JSON"))
        try:
            ge.check_tools(obj, helper("  --stdout"))
            refused = False
        except SystemExit as exc:
            refused = "--json-format" in str(exc)
        (bindir / "llvm-cov").unlink()
        try:
            ge.check_tools(obj, helper(""))
            gone = False
        except SystemExit as exc:
            gone = "no llvm-cov" in str(exc)
        add("check-tools: the build's llvm-cov is found beside its clang and must list --json-format; one that does not, or none, stops the build early",
            good.endswith("llvm-cov") and refused and gone)
    add("env: GCOV_PREFIX_STRIP drops the node's directory", ge.strip_count("/home/runner/work/engine/engine") == 5)

    with tempfile.TemporaryDirectory() as tmp:
        obj = Path(tmp) / "obj-rel"
        (obj / "dom").mkdir(parents=True)
        (obj / "dom" / "u1.gcno").write_bytes(b"\x01\x00\x00\x00/node/src/dom/a.cpp\x00\x00\x00\x00")
        (obj / "dom" / "u2.gcno").write_bytes(b"\x01\x00\x00\x00/node/src/dom/elsewhere.cpp\x00")
        chosen, seen = ge.scan_notes(obj, "/node/src", {"dom/a.cpp"})
        add("notes: of the objects of a build, the ones that name a file of the series are chosen, and those files are the compiled ones",
            len(chosen) == 1 and next(iter(chosen)).endswith("u1.gcno") and seen == {"dom/a.cpp"})

    if os.name == "nt":
        add("bundle: the paths in a .gcno are POSIX ones: not run on Windows", True)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp).resolve()
            paths = fixture(top / "fx")
            (top / "dom").mkdir()
            (top / "dom" / "a.cpp").write_text(A_CPP, encoding="utf-8")
            (top / "obj-rel" / "dom").mkdir(parents=True)
            (top / "obj-rel" / "dom" / "u1.gcno").write_bytes(b"\x01\x00\x00\x00" + (str(top) + "/dom/a.cpp").encode() + b"\x00")
            (top / "obj-rel" / "dom" / "u2.gcno").write_bytes(b"\x01\x00\x00\x00" + (str(top) + "/dom/elsewhere.cpp").encode() + b"\x00")
            cov = top / "fake-llvm-cov"
            cov.write_text("#!/bin/sh\n", encoding="utf-8")
            info = ge.bundle(paths["series_root"], top / "obj-rel", str(top), top / "notes", cov, lambda cmd: "llvm-cov 22\n")
            add("bundle: only the objects that carry a file of the series are kept, with their sources, the llvm-cov and the directory (%s)" % info,
                sorted(p.name for p in (top / "notes" / "gcno").rglob("*.gcno")) == ["u1.gcno"]
                and json.loads((top / "notes" / "compiled.json").read_text(encoding="utf-8")) == ["dom/a.cpp"]
                and (top / "notes" / "sources" / "dom" / "a.cpp").is_file() and (top / "notes" / "llvm-cov").is_file()
                and (top / "notes" / "topsrcdir.txt").read_text(encoding="utf-8").strip() == str(top)
                and (top / "notes" / "versions.txt").read_text(encoding="utf-8") == "llvm-cov 22\n")

    # the coverage .mozconfig
    base = "ac_add_options --enable-application=browser\nac_add_options --with-ccache=sccache\nmk_add_options 'export RUSTC_WRAPPER=sccache'\n"
    text = coverage_mozconfig.compose(base, mozconfig.Plan("gha", "/x/sccache", parallel=12))
    active = mozconfig.active(text)
    add("mozconfig: coverage on, LTO off, no PGO profile, the platform's host, the node's jobs and obj-rel",
        "ac_add_options --enable-coverage" in active and "ac_add_options --disable-lto" in active
        and not [l for l in active if "profile-use" in l or "pgo" in l.lower() or "enable-lto" in l]
        and "ac_add_options --host=x86_64-unknown-linux-gnu" in active and "mk_add_options MOZ_PARALLEL_BUILD=12" in active
        and "mk_add_options MOZ_OBJDIR=@TOPSRCDIR@/obj-rel" in active)
    add("mozconfig: the cache is the pinned sccache by its path, once, and the sandbox stays compiled",
        "ac_add_options --with-ccache=/x/sccache" in active and not [l for l in active if "=sccache" in l]
        and not [l for l in active if "disable-sandbox" in l])

    # the workflow
    import yaml
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    text = WORKFLOW.read_text(encoding="utf-8")
    on = wf.get(True, wf.get("on"))
    add("workflow: it starts on a push to latitude/*-diag and by hand, and cancels the older run of its ref",
        on["push"] == {"branches": ["latitude/*-diag"]} and "workflow_dispatch" in on and wf["concurrency"]["cancel-in-progress"] is True
        and "github.ref" in wf["concurrency"]["group"])
    uploads = [s["with"]["name"] for j in wf["jobs"].values() for s in j.get("steps", []) if "upload-artifact" in s.get("uses", "")]
    add("workflow: every artifact is named cov-*, never asset-, symbols- or an archive of a release (%s)" % ", ".join(uploads),
        uploads and all(u.startswith("cov-") for u in uploads))
    texts = [str(s.get("run", "")) + str(s.get("uses", "")) for j in wf["jobs"].values() for s in j.get("steps", [])] +             [str(j.get("uses", "")) for j in wf["jobs"].values()]
    add("workflow: nothing publishes: no release, no draft, no seal script, no call to publish.yml or gate.yml",
        not [x for x in texts for w in ("gh release", "release create", "publish.yml", "gate.yml", "make_seal", "action-gh-release") if w in x])
    cache_uses = [s.get("uses", "") for j in wf["jobs"].values() for s in j.get("steps", []) if s.get("uses", "").startswith("actions/cache")]
    add("workflow: it saves no cache entry: every use of actions/cache is `restore` (%d of them), none is a save or a plain actions/cache" % len(cache_uses),
        len(cache_uses) == 3 and all(u.startswith("actions/cache/restore@") for u in cache_uses) and "cache/save" not in text)
    keys = [str(s["with"]["key"]) for j in wf["jobs"].values() for s in j.get("steps", []) if s.get("uses", "").startswith("actions/cache/restore@")]
    add("workflow: what it restores is release's own entries (toolchains, sccache binary, Vulkan driver), by their keys, and no key of its own",
        len(keys) == 3 and any(k.startswith("sccache-bin-") for k in keys) and any(k.startswith("${{ steps.toolchains-key") for k in keys)
        and any(k.startswith("${{ steps.lavapipe-key") for k in keys) and not [k for k in keys if "-cov" in k]
        and not [s for j in wf["jobs"].values() for s in j.get("steps", []) if "restore-keys" in (s.get("with") or {})])
    standin = next(s["run"] for s in wf["jobs"]["wrapper-e2e"]["steps"] if s["name"].startswith("Unpack the browser"))
    add("workflow: the sandbox is switched off by a stand-in `firefox` that execs the real one, renamed; the sandbox leg has none, and the core is not asked",
        'if [ "${{ matrix.sandbox }}" != "true" ]; then' in standin and "mv ff/firefox ff/firefox.cov-real" in standin
        and 'exec "$(dirname "$0")/firefox.cov-real" "$@"' in standin and standin.count("MOZ_DISABLE_") >= 10)
    build_steps = [s.get("name", "") for s in wf["jobs"]["build"]["steps"]]
    early = next(i for i, n in enumerate(build_steps) if n.startswith("Configure (the toolchain bootstrap)"))
    add("workflow: the build's llvm-cov is looked for right after configure and before the compile",
        early < build_steps.index("Build") and "gcov_export.py check-tools" in wf["jobs"]["build"]["steps"][early]["run"])
    add("workflow: no job names a label of ours literally (the node's comes from the plan), and the build is on it",
        all("latitude-" not in json.dumps(j.get("runs-on", "")) for j in wf["jobs"].values())
        and wf["jobs"]["build"]["runs-on"] == "${{ needs.plan.outputs.attempt == github.run_attempt && needs.plan.outputs.node_label || '' }}")
    add("workflow: the node is turned off whatever happened, and by the script that deletes it",
        wf["jobs"]["stop-node"]["if"].startswith("always()")
        and "latitude_node.py off" in wf["jobs"]["stop-node"]["steps"][-1]["run"] and "--if-legs-done" not in wf["jobs"]["stop-node"]["steps"][-1]["run"])
    add("workflow: every job has a timeout",
        all("timeout-minutes" in j for j in wf["jobs"].values()))
    legs = wf["jobs"]["wrapper-e2e"]["strategy"]["matrix"]["include"]
    add("workflow: the suites are in the matrix of `wrapper-e2e`, the sandbox leg keeps its sandbox, at most 8 at a time",
        len(legs) == 20 and [r["suite"] for r in legs if r.get("sandbox")] == ["wrapper.e2e.udp.sandbox"]
        and wf["jobs"]["wrapper-e2e"]["strategy"]["max-parallel"] == 8)
    needed = {"id": "x"}
    required = [dict(needed, id=r["suite"], os=["linux", "windows"]) for r in legs if r["suite"].startswith("wrapper.")]
    add("legs-check: the suites of a list that has all of them pass, with their Windows rows ignored", cm.legs_missing(required, wf) == [])
    add("legs-check: a Linux suite with no leg is named",
        cm.legs_missing(required + [{"id": "wrapper.e2e.new", "os": ["linux"]}], wf) == ["wrapper.e2e.new has no leg in the wrapper-e2e matrix"]
        and cm.legs_missing([{"id": "wrapper.unit.all.windows", "os": ["windows"]}], wf) == [])
    add("legs-check: the suites a run expects are gtest and every leg", cm.suites_of(wf)[0] == "gtest" and len(cm.suites_of(wf)) == 21)
    return out


def _all():
    return cases()


def test_every_case_holds():
    failed = [name for name, ok in cases() if not ok]
    assert not failed, failed


def main(argv=None) -> int:
    if any(a in ("-h", "--help") for a in (sys.argv[1:] if argv is None else argv)):
        print(__doc__)
        return 0
    failures = 0
    found = cases()
    for name, ok in found:
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok
    print("%d/%d cases as expected" % (len(found) - failures, len(found)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
