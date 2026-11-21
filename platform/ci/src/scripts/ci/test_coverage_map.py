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
JS_A = """\
SF:/node/src/toolkit/modules/StealthFoo.sys.mjs
FN:1,doIt
FNDA:3,doIt
DA:2,3
DA:3,3
end_of_record
"""
RS_A = """\
SF:/node/src/netwerk/x.rs
FN:1,_ZN3foo3barE
FNDA:2,_ZN3foo3barE
DA:2,2
end_of_record
"""
SUITE_A += JS_A
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


GCOV_SAMPLE = """\
        -:    0:Source:/node/src/dom/a.cpp
        -:    0:Graph:/node/src/obj-rel/dom/u1.gcno
        -:    0:Data:/gcda/obj-rel/dom/u1.gcda
        -:    0:Runs:3
        -:    1:#include "a.h"
function _Z3Foov called 2 returned 100% blocks executed 100%
        2:    2:void Foo() {
        2:    3:  Work();
       2*:    4:  DoA();  // STEALTH-HOOK(feat/a)
    #####:    5:  Never();
    =====:    6:  Thrown();
        -:    7:}
call    0 returned 2
branch  0 taken 2
branch  1 taken 0
        -:    0:Source:../../dom/other.cpp
        -:    0:Graph:/node/src/obj-rel/dom/u1.gcno
function _Z5Otherv called 0 returned 0% blocks executed 0%
    #####:   10:int Other() {
    #####:   11:  return 1;
        -:    0:Source:/usr/include/c++/v1/vector
        -:    0:Graph:/node/src/obj-rel/dom/u1.gcno
        7:    1:T x;
        -:    0:Source:/node/src/dom/a.h
        -:    0:Graph:/node/src/obj-rel/dom/u1.gcno
        5:   30:inline void InHeader() {}
"""


JS_SOURCE = "function doIt() {\n  count++;\n  other++;\n}\n"
JS_PREPROCESSED = "#ifdef MOZ_X\nlet a = 1;\n#endif\nlet b = 2;\n"


def hook(file, function, line, kind="add", form="unknown"):
    return {"file": file, "function": function, "kind": kind, "form": form, "line": line, "test": ""}


def fixture(root: Path, hooks_a=None, hooks_b=None, js=True, rust=False) -> dict:
    """A series, a source tree and the exports under `root`; the paths of the arguments of `map`."""
    series, src, prof = root / "series", root / "src", root / "profiles"
    for rel, text in {"dom/a.cpp": A_CPP, "dom/dup.cpp": DUP_CPP, "dom/gated.cpp": IFDEF_CPP,
                      "dom/windows_only.cpp": "void W() {\n  WinThing();\n}\n", "toolkit/modules/StealthFoo.sys.mjs": JS_SOURCE,
                      "toolkit/modules/NeverLoaded.sys.mjs": JS_SOURCE, "browser/app/pp.js": JS_PREPROCESSED,
                      "netwerk/x.rs": "fn x() {\n    do_it();\n}\n"}.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="utf-8", newline="\n")
    hooks_a = hooks_a if hooks_a is not None else [
        hook("dom/a.cpp", "void Foo() {", "  DoA();  // STEALTH-HOOK(feat/a)"),                  # suiteA only
        hook("dom/a.cpp", "void Bar() {", "  DoB();"),                                          # a counter, no suite counts it
        hook("dom/windows_only.cpp", "void W() {", "  WinThing();"),                           # in no export: not compiled
        hook("dom/a.cpp", "void Foo() {", "  }", form="unknown"),                              # a brace: no counter, takes the hook beside it
        dict(hook("netwerk/x.rs", "fn x() {", "    do_it();"), test="tests/test_rust_thing.py"),  # Rust, with the test its author declared
        hook("toolkit/modules/StealthFoo.sys.mjs", "function doIt() {", "  count++;"),            # JavaScript, run by suiteA
        hook("toolkit/modules/NeverLoaded.sys.mjs", "function doIt() {", "  count++;"),         # JavaScript, in no export
        hook("browser/app/pp.js", "", "let b = 2;"),                                            # preprocessed JavaScript
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
    (prof / "suiteA.info").write_text(SUITE_A + (RS_A if rust else ""), encoding="utf-8")
    (prof / "suiteB.info").write_text(SUITE_B, encoding="utf-8")
    (prof / "suiteA.meta.json").write_text(json.dumps({"rc": 0, "passed": True, "sandbox": "off", "js_info_files": 3 if js else 0,
                                                                  "rust_profraw_files": 4 if rust else 0}), encoding="utf-8")
    (prof / "suiteB.meta.json").write_text(json.dumps({"rc": 1, "passed": False, "failures": 2, "sandbox": "on", "js_info_files": 5 if js else 0}),
                                           encoding="utf-8")
    return {"profiles": prof, "source_root": src, "series_root": series}


def run(root: Path, **extra):
    """(exit code, stderr, rows by (file, text) of hooks.csv) of `map` over the fixture."""
    import csv
    paths = fixture(root, **{k: v for k, v in extra.items() if k in ("hooks_a", "hooks_b", "js", "rust")})
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
        add("map: a hook in Rust is not-measured, not no", r["executed"] == "not-measured")
        rt = rows[("netwerk/x.rs", "fn x() {", "")]
        add("map: a hook that is not measured carries the test its authors declared, in hooks.csv and not_measured.txt",
            rt["test"] == "tests/test_rust_thing.py" and "tests/test_rust_thing.py" in (out_dir / "not_measured.txt").read_text(encoding="utf-8"))
        jr = rows[("toolkit/modules/StealthFoo.sys.mjs", "function doIt() {", "2")]
        add("map: a JavaScript hook is measured like a C one, from the lcov of SpiderMonkey: the suite that ran it is named", jr["executed"] == "yes" and jr["suites"] == "suiteA")
        ju = rows[("toolkit/modules/NeverLoaded.sys.mjs", "function doIt() {", "2")]
        add("map: a JavaScript file that no suite loaded is no, for that reason", ju["executed"] == "no" and ju["reason"] == cm.REASON_JS_UNLOADED)
        add("map: a preprocessed JavaScript file is not measured (its lines are the generated file's)",
            rows[("browser/app/pp.js", "", "")]["executed"] == "not-measured" and "preprocessed" in rows[("browser/app/pp.js", "", "")]["reason"])
        removed = [r for r in rows.values() if r["executed"] == "removed"]
        add("map: a hook that deletes lines has no line to find and is removed, not a failure", len(removed) == 1 and removed[0]["file"] == "dom/a.cpp")
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        add("map: meta has the commits, the run, the suites with their result and the suite that has no profile",
            meta["source_commit"] == "abc" and meta["series_commit"] == "def" and meta["run_id"] == "7"
            and meta["suites"]["suiteA"]["passed"] is True and meta["suites"]["suiteB"]["passed"] is False
            and meta["suites_without_profile"] == ["suiteC"])
        add("map: meta declares that the sandbox was off in the coverage runs, except in the suite that had it on",
            "suiteB" in meta["sandbox"] and "switched off" in meta["sandbox"] and meta["javascript_measured"] is True)
        add("map: the INDEX row is one line under its header", len((out_dir / "index.csv").read_text(encoding="utf-8").splitlines()) == 2)
        own = (out_dir / "functions.csv").read_text(encoding="utf-8")
        add("map: functions.csv is of our own files only (dom/a.cpp is not one, dom/own.cpp has no function here)", own.splitlines() == ["file,function,line,executed,suites"])

    with tempfile.TemporaryDirectory() as tmp:
        code, err, rows, out_dir = run(Path(tmp), rust=True)
        rr = rows[("netwerk/x.rs", "fn x() {", "2")]
        add("map: with a Rust profile in a suite a Rust hook is measured like a C one (yes, and which suite)",
            code == 0 and rr["executed"] == "yes" and rr["suites"] == "suiteA"
            and json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))["rust_measured"] is True)

    with tempfile.TemporaryDirectory() as tmp:
        code, err, rows, out_dir = run(Path(tmp), js=False)
        jr = rows[("toolkit/modules/StealthFoo.sys.mjs", "function doIt() {", "")]
        add("map: with no JavaScript profile in any suite the JavaScript hooks are not-measured, not no",
            code == 0 and jr["executed"] == "not-measured" and json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))["javascript_measured"] is False)

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
        sorted(parsed) == ["dom/a.cpp", "dom/dup.cpp", "dom/gated.cpp", "toolkit/modules/StealthFoo.sys.mjs"] and parsed["dom/a.cpp"]["lines"][4] == 3
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
    got = ge.parse_gcov_text(GCOV_SAMPLE, topsrc, {"dom/a.cpp", "dom/other.cpp", "dom/a.h"}, base="/node/src/obj-rel/dom")
    add("export: llvm-cov's text gives the lines (executed, unexecuted, never-run exception blocks) and drops the lines with no code",
        sorted(got) == ["dom/a.cpp", "dom/a.h", "dom/other.cpp"]
        and got["dom/a.cpp"]["lines"] == {2: 2, 3: 2, 4: 2, 5: 0, 6: 0} and got["dom/other.cpp"]["lines"] == {10: 0, 11: 0})
    add("export: a function line gives the function its start line (the line after it) and its count; a header and a relative Source are read; others dropped",
        got["dom/a.cpp"]["functions"] == {"_Z3Foov": (2, 2)} and got["dom/other.cpp"]["functions"] == {"_Z5Otherv": (10, 0)}
        and got["dom/a.h"]["lines"] == {30: 5} and "usr/include/c++/v1/vector" not in "".join(got))
    names = ge.demangle({"f": {"lines": {}, "functions": {"_Z3Foov": (2, 2), "plain": (3, 1)}}}) or None
    files = {"f": {"lines": {}, "functions": {"_Z3Foov": (2, 2), "plain": (3, 1)}}}
    import subprocess as _sp
    ge.demangle(files, lambda cmd, **kw: _sp.CompletedProcess(cmd, 0, "Foo()\n", ""))
    add("export: mangled names go through c++filt, and stay as they are when it says nothing usable",
        files["f"]["functions"] == {"Foo()": (2, 2), "plain": (3, 1)} and names is None)
    gone = {"f": {"lines": {}, "functions": {"_Z3Foov": (2, 2)}}}
    ge.demangle(gone, lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError("c++filt")))
    add("export: no c++filt on the machine leaves the names mangled", gone["f"]["functions"] == {"_Z3Foov": (2, 2)})
    again = ge.to_lcov(got, "s")
    back = cm.parse_lcov(again)
    add("export: what it writes is what the map reads", back["dom/a.cpp"]["lines"] == {2: 2, 3: 2, 4: 2, 5: 0, 6: 0} and back["dom/a.cpp"]["functions"]["_Z3Foov"] == (2, 2))

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
            return subprocess.CompletedProcess(cmd, 0, "        -:    0:Source:/node/src/dom/a.cpp\n        1:    4:  DoA();\n", "")
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
            len(calls) == 3 and "DA:4,2" in text and meta["gcda_files"] == 2 and meta["passed"] is False and meta["rc"] == 1)
        add("export: the converter is called on this object's own .gcno and .gcda",
            any("--gcno=%s" % (notes / "gcno" / "obj-rel" / "dom" / "u1.gcno") in c and "--gcda=%s" % (profile / "obj-rel" / "dom" / "u1.gcda") in c
                and "--stdout" in c and "--branch-probabilities" in c for c in calls))
    import subprocess
    import io as _io
    from contextlib import redirect_stdout as _redir

    SMOKE = "        -:    0:Source:t.c\n        1:    2:  return 2 * x;\n        -:    3:}\n    #####:    5:  return x;\n"

    def llvm_machine(accepted, help_text="", build_ok=True, files=False, text=SMOKE):
        """A fake llvm-cov and clang: `gcov` takes exactly the flags in `accepted` (dashes and all), anything else is `Unknown command line argument`."""
        seen = []

        def run(cmd, **kw):
            seen.append(cmd)
            name = str(cmd[0])
            if name.endswith("clang"):
                return subprocess.CompletedProcess(cmd, 0 if build_ok else 1, "", "" if build_ok else "no linker")
            if name.endswith("llvm-cov") and cmd[1:] == ["--version"]:
                return subprocess.CompletedProcess(cmd, 0, "LLVM version 99.0.0\n", "")
            if name.endswith("llvm-cov") and cmd[1:] == ["gcov", "--help"]:
                return subprocess.CompletedProcess(cmd, 0, help_text, "")
            if name.endswith("llvm-cov"):
                flags = [a.split("=")[0] for a in cmd[2:] if a.startswith("-")]
                bad = [f for f in flags if f not in accepted]
                if bad:
                    return subprocess.CompletedProcess(cmd, 1, "", "Unknown command line argument '%s'" % bad[0])
                if files:
                    (Path(kw["cwd"]) / "t.c.gcov").write_text(text, encoding="utf-8")
                    return subprocess.CompletedProcess(cmd, 0, "File 't.c'\nLines executed:50.00% of 2\n", "")
                return subprocess.CompletedProcess(cmd, 0, text, "")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        run.seen = seen
        return run

    with tempfile.TemporaryDirectory() as tmp:
        bindir = Path(tmp) / "clang" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "llvm-cov").write_text("", encoding="utf-8")
        (bindir / "clang").write_text("", encoding="utf-8")
        obj = Path(tmp) / "obj-rel"
        obj.mkdir()
        (obj / "config.status.json").write_text(json.dumps({"substs": {"CC": str(bindir / "clang") + " --target=x"}}), encoding="utf-8")

        def checked(machine, n):
            sink = _io.StringIO()
            with _redir(sink):
                ge.check_tools(obj, machine, work=Path(tmp) / ("w%d" % n))
            return sink.getvalue(), json.loads((obj / ge.SPELLING_FILE).read_text(encoding="utf-8"))

        said, got = checked(llvm_machine({"--branch-probabilities", "--stdout", "--gcno", "--gcda"}, "  --stdout  Print\n"), 1)
        add("check-tools: it prints llvm-cov's version and the whole help it gave, and keeps the first spelling that works on the program",
            "LLVM version 99.0.0" in said and "--stdout  Print" in said and got["label"] == "long, branches, stdout" and got["chosen_by"] == "smoke test")
        _, got = checked(llvm_machine({"-b", "-t", "-gcno", "-gcda"}), 2)
        add("check-tools: the long forms refused, the short ones are found", got["label"] == "short, branches, stdout")
        _, got = checked(llvm_machine({"-stdout", "-gcno", "-gcda"}), 3)
        add("check-tools: with a single dash and no -b it is the spelling that works (the dashes are not assumed)", got["label"] == "single dash, stdout")
        _, got = checked(llvm_machine({"--gcno", "--gcda"}, files=True), 4)
        add("check-tools: when nothing prints to stdout the .gcov files it writes are read", got["mode"] == "files" and got["label"] == "long, files")
        try:
            checked(llvm_machine({"--gcno", "--gcda"}, text="garbage\n", files=False), 5)
            red = False
        except SystemExit as exc:
            red = "no spelling" in str(exc) and "stdout" in str(exc)
        try:
            checked(llvm_machine(set()), 6)
            red_none = False
        except SystemExit as exc:
            red_none = "Unknown command line argument" in str(exc)
        add("check-tools: red only when no spelling gives a file the parser reads, and the message says what each said", red and red_none)
        wrong = SMOKE.replace("1:    2:", "#####:    2:")
        try:
            checked(llvm_machine({"--stdout", "--gcno", "--gcda"}, text=wrong), 7)
            wrong_red = False
        except SystemExit:
            wrong_red = True
        add("check-tools: a file that reads but does not show line 2 run and line 5 not is not accepted", wrong_red)
        said, got = checked(llvm_machine({"-b", "-t", "-gcno", "-gcda"}, "  -b  branches\n  -t  stdout\n  -gcno=<gcno>\n  -gcda=<gcda>\n", build_ok=False), 8)
        add("check-tools: a program that cannot be built falls back to the help text, accepting short forms and a single dash",
            got["label"] == "short, branches, stdout" and got["chosen_by"] == "help text" and "warning" in said)
        try:
            checked(llvm_machine(set(), "  --verbose\n", build_ok=False), 9)
            nohelp = False
        except SystemExit as exc:
            nohelp = "lists no spelling" in str(exc)
        add("check-tools: no program and no listed spelling is red", nohelp)
    with tempfile.TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        (notes / "gcno" / "obj-rel" / "dom").mkdir(parents=True)
        (notes / "gcno" / "obj-rel" / "dom" / "u1.gcno").write_bytes(b"x")
        (notes / "topsrcdir.txt").write_text("/node/src\n", encoding="utf-8")
        (notes / "interest.json").write_text(json.dumps(["dom/a.cpp"]), encoding="utf-8")
        profile = Path(tmp) / "gcda"
        (profile / "obj-rel" / "dom").mkdir(parents=True)
        (profile / "obj-rel" / "dom" / "u1.gcda").write_bytes(b"y")
        sample = "        -:    0:Source:/node/src/dom/a.cpp\n        1:    4:  DoA();\n"
        calls = []

        def only_short(cmd, **kw):
            calls.append(cmd)
            if "--stdout" in cmd or "--branch-probabilities" in cmd:
                return subprocess.CompletedProcess(cmd, 1, "", "Unknown command line argument")
            return subprocess.CompletedProcess(cmd, 0, sample, "")
        meta = ge.export(notes, profile, "s", Path(tmp) / "o1", run=only_short)
        add("export: with no spelling in the notes the first that gives a text for the first profile is used, and the meta says so",
            meta["gcov_command"][0] == "short, branches, stdout" and meta["gcov_command"][2] == "the first profile of this suite" and "DA:4,1" in (Path(tmp) / "o1" / "s.info").read_text(encoding="utf-8"))
        (notes / ge.SPELLING_FILE).write_text(json.dumps(dict(ge.GCOV_SPELLINGS[4], chosen_by="smoke test")), encoding="utf-8")
        calls.clear()
        meta = ge.export(notes, profile, "s", Path(tmp) / "o2", run=only_short)
        add("export: the spelling in the notes is the one used, with its own flags, and is in the meta",
            all("-t" in c for c in calls) and tuple(meta["gcov_command"]) == ("short, stdout", ["-t", "-gcno={gcno}", "-gcda={gcda}"], "smoke test"))
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
    rust_text = coverage_mozconfig.compose(base, mozconfig.Plan("gha", "/x/sccache", parallel=12), rust=True)
    add("mozconfig: Rust is instrumented only when asked (-C instrument-coverage in RUSTFLAGS), and the rest is the same",
        "mk_add_options 'export RUSTFLAGS=-Cinstrument-coverage'" in mozconfig.active(rust_text) and "RUSTFLAGS" not in text
        and [l for l in mozconfig.active(rust_text) if "RUSTFLAGS" not in l] == active)
    add("mozconfig: the cache is the pinned sccache by its path, once, and the sandbox stays compiled",
        "ac_add_options --with-ccache=/x/sccache" in active and not [l for l in active if "=sccache" in l]
        and not [l for l in active if "disable-sandbox" in l])

    # the workflow
    import yaml
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    text = WORKFLOW.read_text(encoding="utf-8")
    on = wf.get(True, wf.get("on"))
    add("workflow: it starts on a push to latitude/*-diag (and *-diag-rust, which also measures Rust) and by hand, and cancels the older run of its ref",
        on["push"] == {"branches": ["latitude/*-diag", "latitude/*-diag-rust"]}
        and wf["jobs"]["plan"]["outputs"]["rust"] == "${{ endsWith(github.ref_name, '-rust') && 'true' || 'false' }}" and "workflow_dispatch" in on and wf["concurrency"]["cancel-in-progress"] is True
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
