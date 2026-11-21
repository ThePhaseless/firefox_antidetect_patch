#!/usr/bin/env python3
"""The gcov side of diagnostics.yml: what the node keeps of a coverage build, and what a suite's runner makes of its profiles.

    python3 scripts/ci/gcov_export.py bundle --series-root S --objdir obj-rel --topsrcdir DIR --out notes     (on the node, after the build)
    python3 scripts/ci/gcov_export.py check-tools --objdir obj-rel                                             (on the node, after configure)
    python3 scripts/ci/gcov_export.py env --notes notes --prefix DIR                                           (a suite's runner: GCOV_PREFIX*)
    python3 scripts/ci/gcov_export.py export --notes notes --gcda DIR --suite NAME --out DIR [--rc N] [--junit F] [--raw F.tar.gz]

The build is `--enable-coverage`: every object has a .gcno at compile time and writes a .gcda when its process exits (the tree turns the fast
shutdown off and defines NS_FREE_PERMANENT_DATA for coverage, so a content process exits through its atexit hooks and not through _exit). The
.gcda path is the object's own, under the node's source directory; GCOV_PREFIX moves it to one directory per suite and GCOV_PREFIX_STRIP drops the
node's source directory from it, so a suite's profiles sit at <prefix>/obj-rel/<dir>/<object>.gcda, beside nothing, and a .gcno of the notes at
<notes>/gcno/obj-rel/<dir>/<object>.gcno names the same object. Every process of the suite merges into the same files (the profile runtime locks them).

`bundle` keeps only the objects that carry a file of the series (a hook's file or a file of our own that the folders add, in C or C++): the .gcno
files that name one, found by the paths written in them, so the notes are megabytes and a runner converts a few hundred objects. It also keeps the
sources of those files at the built commit, the clang's llvm-cov (the same clang as the build: it reads its .gcno and .gcda) and what the build says
of itself. `export` converts a suite's profiles for those objects with `llvm-cov gcov --branch-probabilities --stdout` (the .gcov text) into an lcov file of the files of the
series only, which scripts/ci/coverage_map.py reads. It fails when the suite left no profile at all.

Its cases: scripts/ci/test_coverage_map.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import coverage_map  # noqa: E402

# A path written in a .gcno: absolute, ends in a C or C++ extension, NUL-terminated (strings are padded to a word with NULs).
PATH_IN_NOTES = re.compile(rb"/[\x21-\x7e]+\.(?:cpp|cc|cxx|c|h|hh|hpp|hxx)(?=\x00)")


def strip_count(topsrcdir: str) -> int:
    """The number of directories of the node's source path: what GCOV_PREFIX_STRIP drops."""
    return len([p for p in topsrcdir.replace("\\", "/").split("/") if p])


def interest_files(series_root: Path) -> list:
    """The C and C++ files of the series: the files of its hooks, and the files of our own that its folders add."""
    found = {h["file"] for h in coverage_map.load_hooks(series_root)} | set(coverage_map.own_files(series_root))
    return sorted(p for p in found if coverage_map.is_c(p))


def relative(path: str, topsrcdir: str) -> str:
    path = os.path.normpath(path).replace("\\", "/")
    root = os.path.normpath(topsrcdir).replace(chr(92), "/").rstrip("/") + "/"
    return path[len(root):] if path.startswith(root) else path


def header_links(objdir: Path, topsrcdir: str, interest: set) -> dict:
    """{obj-rel/dist/include/<name>: the source it links to} for the exported headers that are files of the series. A header a file includes
    as <mozilla/Foo.h> is found under dist/include, a link to the source, and that is the path the compiler writes in the .gcno."""
    links = {}
    include = Path(objdir) / "dist" / "include"
    for here, _, names in os.walk(include):
        for name in names:
            path = os.path.join(here, name)
            if os.path.islink(path):
                target = relative(os.path.realpath(path), os.path.realpath(topsrcdir))
                if target in interest:
                    links[relative(path, topsrcdir)] = target
    return links


def files_named_in(data: bytes, topsrcdir: str, links: dict = None) -> set:
    """The sources (relative to topsrcdir) a .gcno names, an exported header by the source it links to."""
    links = links or {}
    names = {relative(m.group(0).decode("ascii", "replace"), topsrcdir) for m in PATH_IN_NOTES.finditer(data)}
    return {links.get(n, n) for n in names}


def scan_notes(objdir: Path, topsrcdir: str, interest: set, links: dict = None) -> tuple:
    """({gcno path relative to topsrcdir: the interest files it names}, the interest files named by any .gcno)."""
    chosen, compiled = {}, set()
    for gcno in sorted(Path(objdir).rglob("*.gcno")):
        named = files_named_in(gcno.read_bytes(), topsrcdir, links) & interest
        if named:
            chosen[relative(str(gcno), topsrcdir)] = named
            compiled |= named
    return chosen, compiled


def find_llvm_cov(objdir: Path) -> Path:
    """The llvm-cov of the clang the build used (config.status.json's CC), else of the toolchain the build fetched."""
    candidates = []
    try:
        cc = json.loads((Path(objdir) / "config.status.json").read_text(encoding="utf-8"))["substs"].get("CC") or ""
        cc = cc if isinstance(cc, str) else (cc[0] if cc else "")
        if cc.split():
            candidates.append(Path(cc.split()[0]).parent / "llvm-cov")
    except (OSError, ValueError, KeyError):
        pass
    candidates += sorted((Path.home() / ".mozbuild").glob("clang*/bin/llvm-cov"))
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit("ERROR: no llvm-cov beside the build's clang (looked at %s): the toolchain that built the objects is the only one that "
                     "reads their .gcno" % ", ".join(str(c) for c in candidates))


CHECK_C = "int twice(int x) {\n  return 2 * x;\n}\nint never(int x) {\n  return x;\n}\nint main(void) {\n  return twice(0);\n}\n"


def check_tools(objdir: Path, run=subprocess.run, work=None) -> str:
    """The build's llvm-cov, what its `gcov` lists of the options the export uses, and the export itself on a program of a few lines, built
    and run here with the build's own clang. Said right after the toolchain's bootstrap, before an hour of compiling. A program that cannot be
    built here (no linker for it on this machine) is a warning, not a stop; one whose output the parser cannot read is a stop."""
    llvm_cov = find_llvm_cov(objdir)
    done = run([str(llvm_cov), "gcov", "--help"], capture_output=True, text=True, check=False)
    text = (done.stdout or "") + (done.stderr or "")
    missing = [o for o in ("--gcno", "--gcda", "--stdout", "--branch-probabilities") if o not in text]
    if missing:
        raise SystemExit("ERROR: %s gcov does not list %s: this llvm-cov cannot give the export the map reads" % (llvm_cov, ", ".join(missing)))
    clang = Path(llvm_cov).parent / "clang"
    if clang.is_file():
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(work or tmp)
            tmp.mkdir(parents=True, exist_ok=True)
            (tmp / "t.c").write_text(CHECK_C, encoding="utf-8", newline="\n")
            steps = [[str(clang), "--coverage", "-O0", "-c", "t.c", "-o", "t.o"], [str(clang), "--coverage", "t.o", "-o", "t"], [str(tmp / "t")]]
            failed = None
            for cmd in steps:
                done = run(cmd, capture_output=True, text=True, check=False, cwd=str(tmp))
                if done.returncode != 0:
                    failed = (done.stderr or done.stdout or "").strip()[:200]
                    break
            if failed is not None:
                print("warning: the check program did not build and run with %s (%s): the export's format is not checked here" % (clang, failed))
            else:
                got = convert_one(str(llvm_cov), tmp / "t.gcno", tmp / "t.gcda", str(tmp), {"t.c"}, run, None, str(tmp))
                rec = got.get("t.c", {"lines": {}, "functions": {}})
                if not (rec["lines"].get(2, 0) >= 1 and rec["lines"].get(5) == 0 and 5 in rec["lines"]):
                    raise SystemExit("ERROR: llvm-cov gcov printed something the export cannot read on a program of a few lines: %s" % got)
    return str(llvm_cov)


def bundle(series_root: Path, objdir: Path, topsrcdir: str, out: Path, llvm_cov: Path = None, version=lambda cmd: "") -> dict:
    interest = interest_files(series_root)
    links = header_links(objdir, topsrcdir, set(interest))
    chosen, compiled = scan_notes(objdir, topsrcdir, set(interest), links)
    for rel in chosen:
        target = Path(out) / "gcno" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(topsrcdir) / rel, target)
    sources = 0
    for rel in interest:
        if (Path(topsrcdir) / rel).is_file():
            target = Path(out) / "sources" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(topsrcdir) / rel, target)
            sources += 1
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "compiled.json").write_text(json.dumps(sorted(compiled), indent=1) + "\n", encoding="utf-8")
    (Path(out) / "interest.json").write_text(json.dumps(interest, indent=1) + "\n", encoding="utf-8")
    (Path(out) / "topsrcdir.txt").write_text(topsrcdir + "\n", encoding="utf-8")
    (Path(out) / "header-links.json").write_text(json.dumps(links, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    versions = ""
    if llvm_cov:
        shutil.copy2(llvm_cov, Path(out) / "llvm-cov")
        os.chmod(Path(out) / "llvm-cov", 0o755)
        versions = version([str(llvm_cov), "--version"])
        clang = Path(llvm_cov).parent / "clang"
        if clang.is_file():
            versions += version([str(clang), "--version"])
    (Path(out) / "versions.txt").write_text(versions, encoding="utf-8")
    return {"interest": len(interest), "gcno": len(chosen), "compiled": len(compiled), "sources": sources, "header_links": len(links)}


# ------------------------------------------------------------------------------------------------------------------- converting

# One line of `llvm-cov gcov --stdout` (the .gcov text): the count in nine columns (`-` for a line with no code, `#####` or `=====` for code that
# never ran, a number otherwise, with a `*` when some of its blocks did not run), the line number in five, then the source line.
GCOV_LINE = re.compile(r"^\s*(-|#####|=====|\d+)\*?:\s*(\d+):(.*)$")
GCOV_FUNCTION = re.compile(r"^function (\S+) called (\d+)\b")


def parse_gcov_text(text: str, topsrcdir: str, interest: set, links: dict = None, base: str = "") -> dict:
    """{file: {"lines": {n: count}, "functions": {name: (line, count)}}} of the interest files in the .gcov text llvm-cov printed.

    `Source:<path>` on line 0 opens a file (a path that is not absolute is the compile directory's: `base`). A `function NAME called N ...` line
    (printed by -b, before the line the function starts on) gives the function its start line and its count. Branch and call lines are skipped."""
    out: dict = {}
    rec = None
    pending = []
    for raw in text.splitlines():
        m = GCOV_LINE.match(raw)
        if not m:
            f = GCOV_FUNCTION.match(raw)
            if f and rec is not None:
                pending.append((f.group(1), int(f.group(2))))
            continue
        count, n, source = m.group(1), int(m.group(2)), m.group(3)
        if n == 0:
            if source.startswith("Source:"):
                name = source[len("Source:"):].strip()
                path = relative(name if os.path.isabs(name) or not base else os.path.join(base, name), topsrcdir)
                path = (links or {}).get(path, path)
                rec = out.setdefault(path, {"lines": {}, "functions": {}}) if path in interest else None
                pending = []
            continue
        if rec is None:
            continue
        if count != "-":
            rec["lines"][n] = rec["lines"].get(n, 0) + (int(count) if count.isdigit() else 0)
        for fname, calls in pending:
            start, old = rec["functions"].get(fname, (n, 0))
            rec["functions"][fname] = (start or n, old + calls)
        pending = []
    return {path: rec for path, rec in out.items() if rec["lines"] or rec["functions"]}


def merge(into: dict, more: dict) -> None:
    for path, rec in more.items():
        have = into.setdefault(path, {"lines": {}, "functions": {}})
        for n, count in rec["lines"].items():
            have["lines"][n] = have["lines"].get(n, 0) + count
        for name, (start, count) in rec["functions"].items():
            old = have["functions"].get(name, (start, 0))
            have["functions"][name] = (old[0] or start, old[1] + count)


def to_lcov(files: dict, suite: str) -> str:
    out = []
    for path in sorted(files):
        rec = files[path]
        out += ["TN:%s" % suite, "SF:%s" % path]
        out += ["FN:%d,%s" % (start, name) for name, (start, _) in sorted(rec["functions"].items(), key=lambda kv: (kv[1][0], kv[0]))]
        out += ["FNDA:%d,%s" % (count, name) for name, (_, count) in sorted(rec["functions"].items(), key=lambda kv: (kv[1][0], kv[0]))]
        out += ["DA:%d,%d" % (n, rec["lines"][n]) for n in sorted(rec["lines"])]
        out.append("end_of_record")
    return "\n".join(out) + ("\n" if out else "")


GCOV_FLAGS = ("--branch-probabilities", "--stdout")


def convert_one(llvm_cov: str, gcno: Path, gcda: Path, topsrcdir: str, interest: set, run=subprocess.run, links: dict = None, base: str = "") -> dict:
    """One object's profile through `llvm-cov gcov`: the text it prints for each source file the object names (the headers too)."""
    done = run([llvm_cov, "gcov", *GCOV_FLAGS, "--gcno=%s" % gcno, "--gcda=%s" % gcda, str(gcno)],
               capture_output=True, text=True, check=False, cwd=str(gcno.parent))
    if done.returncode != 0:
        raise RuntimeError("llvm-cov exited %d on %s: %s" % (done.returncode, gcno.name, (done.stderr or done.stdout).strip()[:300]))
    return parse_gcov_text(done.stdout, topsrcdir, interest, links, base)


def demangle(files: dict, run=subprocess.run) -> None:
    """The names of the functions as c++filt reads them, in place; the mangled ones stay when there is no c++filt."""
    names = sorted({n for rec in files.values() for n in rec["functions"] if n.startswith("_Z")})
    if not names:
        return
    try:
        done = run(["c++filt"], input="\n".join(names) + "\n", capture_output=True, text=True, check=False)
    except OSError:
        return
    plain = done.stdout.splitlines()
    if done.returncode != 0 or len(plain) != len(names):
        return
    table = dict(zip(names, plain))
    for rec in files.values():
        rec["functions"] = {table.get(n, n): v for n, v in rec["functions"].items()}


def junit_counts(path: Path) -> dict:
    tests = failures = errors = skipped = 0
    for suite in ET.parse(path).getroot().iter("testsuite"):
        tests += int(suite.get("tests") or 0)
        failures += int(suite.get("failures") or 0)
        errors += int(suite.get("errors") or 0)
        skipped += int(suite.get("skipped") or 0)
    return {"tests": tests, "failures": failures, "errors": errors, "skipped": skipped}


def export(notes: Path, gcda_root: Path, suite: str, out: Path, jobs: int = 4, rc=None, junit=None, raw=None, run=subprocess.run) -> dict:
    notes, gcda_root = Path(notes), Path(gcda_root)
    topsrcdir = (notes / "topsrcdir.txt").read_text(encoding="utf-8").strip()
    interest = set(json.loads((notes / "interest.json").read_text(encoding="utf-8")))
    llvm_cov = str(notes / "llvm-cov")
    links_file = notes / "header-links.json"
    links = json.loads(links_file.read_text(encoding="utf-8")) if links_file.is_file() else {}
    pairs = []
    for gcno in sorted((notes / "gcno").rglob("*.gcno")):
        gcda = gcda_root / gcno.relative_to(notes / "gcno").with_suffix(".gcda")
        if gcda.is_file():
            pairs.append((gcno, gcda))
    if not pairs:
        raise SystemExit("ERROR: suite %s left no profile: not one .gcda of the %d objects the notes name is under %s. The counters did not "
                         "reach the directory: the browser was killed instead of quitting, GCOV_PREFIX did not reach it, or a sandbox refused "
                         "the write" % (suite, len(list((notes / "gcno").rglob("*.gcno"))), gcda_root))
    files: dict = {}
    errors: list = []

    def one(pair):
        try:
            return convert_one(llvm_cov, pair[0], pair[1], topsrcdir, interest, run, links,
                               str(Path(topsrcdir) / pair[0].relative_to(notes / "gcno").parent))
        except (RuntimeError, ValueError) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for result in pool.map(one, pairs):
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                merge(files, result)
    if len(errors) == len(pairs):
        raise SystemExit("ERROR: llvm-cov could not read any of the %d profiles of suite %s; the first: %s" % (len(pairs), suite, errors[0]))
    demangle(files, run)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ("%s.info" % suite)).write_text(to_lcov(files, suite), encoding="utf-8", newline="\n")
    meta = {"suite": suite, "rc": rc, "gcda_files": len(pairs), "export_errors": len(errors), "files": len(files),
            "lines": sum(len(r["lines"]) for r in files.values())}
    if junit and Path(junit).is_file():
        meta.update(junit_counts(Path(junit)))
    meta["passed"] = (rc == 0 and not meta.get("failures") and not meta.get("errors")) if rc is not None else None
    if errors:
        meta["first_error"] = errors[0]
    (out / ("%s.meta.json" % suite)).write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if raw:
        with tarfile.open(raw, "w:gz") as tar:
            for _, gcda in pairs:
                tar.add(gcda, arcname=str(gcda.relative_to(gcda_root)))
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("--series-root", type=Path, required=True)
    b.add_argument("--objdir", type=Path, required=True)
    b.add_argument("--topsrcdir", required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--llvm-cov", type=Path)
    k = sub.add_parser("check-tools")
    k.add_argument("--objdir", type=Path, required=True)
    e = sub.add_parser("env")
    e.add_argument("--notes", type=Path, required=True)
    e.add_argument("--prefix", type=Path, required=True)
    x = sub.add_parser("export")
    x.add_argument("--notes", type=Path, required=True)
    x.add_argument("--gcda", type=Path, required=True)
    x.add_argument("--suite", required=True)
    x.add_argument("--out", type=Path, required=True)
    x.add_argument("--rc", type=int)
    x.add_argument("--junit", type=Path)
    x.add_argument("--jobs", type=int, default=4)
    x.add_argument("--raw", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "bundle":
        llvm_cov = a.llvm_cov or find_llvm_cov(a.objdir)

        def version(cmd):
            done = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return done.stdout.strip() + "\n"
        print(json.dumps(bundle(a.series_root, a.objdir, a.topsrcdir, a.out, llvm_cov, version), sort_keys=True))
    elif a.cmd == "check-tools":
        print("llvm-cov: %s (the export reads its text output)" % check_tools(a.objdir))
    elif a.cmd == "env":
        top = (a.notes / "topsrcdir.txt").read_text(encoding="utf-8").strip()
        print("GCOV_PREFIX=%s" % a.prefix.resolve())
        print("GCOV_PREFIX_STRIP=%d" % strip_count(top))
    else:
        print(json.dumps(export(a.notes, a.gcda, a.suite, a.out, a.jobs, a.rc, a.junit, a.raw), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
