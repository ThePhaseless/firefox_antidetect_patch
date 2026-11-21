#!/usr/bin/env python3
"""The gcov side of diagnostics.yml: what the node keeps of a coverage build, and what a suite's runner makes of its profiles.

    python3 scripts/ci/gcov_export.py bundle --series-root S --objdir obj-rel --topsrcdir DIR --out notes     (on the node, after the build)
    python3 scripts/ci/gcov_export.py check-tools --objdir obj-rel                                             (on the node, after configure)
    python3 scripts/ci/gcov_export.py env --notes notes --prefix DIR [--js DIR] [--rust DIR]                                           (a suite's runner: GCOV_PREFIX*)
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

JavaScript is measured by SpiderMonkey itself, at run time and in any build: JS_CODE_COVERAGE_OUTPUT_DIR names a directory and every process that
runs JavaScript writes an lcov file there when its runtime ends (js/src/vm/CodeCoverage.cpp; the same clean exit the gcov counters need). The
scripts are named by URL (resource://gre/modules/X.sys.mjs, chrome://juggler/content/Y.js); `export --js DIR` finds the file of the series each
URL is (js_resolver: by its name, the tail of its path when names repeat) and adds its records to the suite's lcov. A preprocessed file's lines
are those of the generated file, so the map does not measure those.

Rust is measured only by a run of a branch `latitude/*-diag-rust`: the build adds RUSTFLAGS=-C instrument-coverage (the retail's rustc from rustup,
with its `llvm-tools`), every process writes LLVM_PROFILE_FILE=<dir>/%p-%m.profraw, and `export --rust DIR --object libxul.so` merges and exports them
with the llvm-profdata and llvm-cov of that rustc, which read what that rustc's LLVM wrote.

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


def interest_js_files(series_root: Path) -> list:
    """The JavaScript files of the series: the files of its hooks, and the files of our own that its folders add."""
    found = {h["file"] for h in coverage_map.load_hooks(series_root)} | set(coverage_map.own_files(series_root))
    return sorted(p for p in found if coverage_map.is_js(p))


def interest_rs_files(series_root: Path) -> list:
    """The Rust files of the series: the files of its hooks, and the files of our own that its folders add."""
    found = {h["file"] for h in coverage_map.load_hooks(series_root)} | set(coverage_map.own_files(series_root))
    return sorted(p for p in found if coverage_map.is_rs(p))


def rs_resolver(interest: list):
    """A function from the path llvm-cov names a Rust source by (relative to the source directory, or remapped) to the file of the series: the
    path itself, else the one file of the series it ends with, or that ends with it (a remapped prefix)."""
    wanted = set(interest)

    def resolve(path: str):
        if path in wanted:
            return path
        tails = [p for p in interest if path.endswith("/" + p) or p.endswith("/" + path)]
        return tails[0] if len(tails) == 1 else None
    return resolve


def rust_files(profraw_dir: Path, notes: Path, objects: list, topsrcdir: str, interest: list, run=subprocess.run) -> tuple:
    """(the records of the Rust files of the series, how many .profraw files). The suite's .profraw files are merged by the llvm-profdata of
    the rustc that built the Rust (the build's clang may be older than rustc's LLVM and then cannot read the mapping), and llvm-cov of the same
    exports the objects' coverage mapping as lcov."""
    raws = sorted(Path(profraw_dir).glob("*.profraw")) if profraw_dir and Path(profraw_dir).is_dir() else []
    tools = notes / "rust-llvm-cov", notes / "rust-llvm-profdata"
    if not raws or not all(t.is_file() for t in tools) or not objects:
        return {}, len(raws)
    merged = Path(profraw_dir) / "merged.profdata"
    listing = Path(profraw_dir) / "merge.list"
    listing.write_text("\n".join(str(r) for r in raws) + "\n", encoding="utf-8", newline="\n")
    done = run([str(tools[1]), "merge", "-sparse", "--input-files=%s" % listing, "-o", str(merged)], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError("llvm-profdata exited %d: %s" % (done.returncode, (done.stderr or done.stdout).strip()[:300]))
    cmd = [str(tools[0]), "export", "-format=lcov", "-instr-profile=%s" % merged, str(objects[0])] + ["-object=%s" % o for o in objects[1:]]
    done = run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError("llvm-cov export exited %d: %s" % (done.returncode, (done.stderr or done.stdout).strip()[:300]))
    resolve = rs_resolver(interest)
    files: dict = {}
    for path, rec in coverage_map.parse_lcov(done.stdout, topsrcdir).items():
        found = resolve(path)
        if found:
            merge(files, {found: rec})
    return files, len(raws)


def url_tail(url: str) -> str:
    """The path of a script's URL below its host or package: resource://gre/modules/X.sys.mjs -> modules/X.sys.mjs, chrome://juggler/content/Y.js
    -> content/Y.js, jar:file:///.../omni.ja!/modules/X.sys.mjs -> modules/X.sys.mjs; a query, a fragment and `x -> y` (the loader's) are dropped."""
    url = url.split(" -> ")[-1].strip().split("?")[0].split("#")[0]
    if "!/" in url:
        return url.split("!/", 1)[1]
    m = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:(?://[^/]*)?/*(.*)$", url)
    return m.group(1) if m else url


def js_resolver(interest: list):
    """A function from a script's URL to the file of the series it is, or None. By the file's name when that is the only one of the series
    with it, else by the longest tail of the URL's path that ends one of them (the tree's own flattening of a directory into a package, as
    toolkit/modules into resource://gre/modules, is why the whole path cannot be compared)."""
    by_base: dict = {}
    for path in interest:
        by_base.setdefault(path.rsplit("/", 1)[-1], []).append(path)

    def resolve(url: str):
        tail = url_tail(url)
        found = by_base.get(tail.rsplit("/", 1)[-1], [])
        if len(found) == 1:
            return found[0]
        best = [p for p in found if ("/" + p).endswith("/" + tail)]
        if len(best) == 1:
            return best[0]
        parts = tail.split("/")
        for n in range(len(parts) - 1, 0, -1):
            narrowed = [p for p in found if ("/" + p).endswith("/" + "/".join(parts[-n:]))]
            if len(narrowed) == 1:
                return narrowed[0]
        return None
    resolve.bases = set(by_base)
    return resolve


def js_files(directory: Path, interest: list) -> tuple:
    """(the records of the interest files in the .info files SpiderMonkey wrote under `directory`, how many .info files, how many scripts of the
    series whose URL no file of the series answers to). One process writes one file per runtime; a record is a script's URL and its lines."""
    resolve = js_resolver(interest)
    files: dict = {}
    seen = unresolved = 0
    for info in sorted(Path(directory).rglob("*.info")):
        seen += 1
        text = info.read_text(encoding="utf-8", errors="replace")
        if not any(base in text for base in resolve.bases):
            continue
        for url, rec in coverage_map.parse_lcov(text).items():
            path = resolve(url)
            if path is None:
                unresolved += url_tail(url).rsplit("/", 1)[-1] in resolve.bases
                continue
            merge(files, {path: rec})
    return files, seen, unresolved


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


# The spellings of `llvm-cov gcov` the export may use, in the order they are tried: the long and the short forms of the options, with a single dash
# or two (LLVM takes both), printing to stdout or writing .gcov files in the directory it runs in. -b (the branch probabilities) is what makes it
# print `function NAME called N`, which gives the functions; the map does not need the rest of it. Which one this llvm-cov takes is found by
# trying them on a program of a few lines (check_tools), never by reading its help.
GCOV_SPELLINGS = (
    {"label": "long, branches, stdout", "mode": "stdout", "args": ["--branch-probabilities", "--stdout", "--gcno={gcno}", "--gcda={gcda}"]},
    {"label": "short, branches, stdout", "mode": "stdout", "args": ["-b", "-t", "-gcno={gcno}", "-gcda={gcda}"]},
    {"label": "single dash, branches, stdout", "mode": "stdout", "args": ["-branch-probabilities", "-stdout", "-gcno={gcno}", "-gcda={gcda}"]},
    {"label": "long, stdout", "mode": "stdout", "args": ["--stdout", "--gcno={gcno}", "--gcda={gcda}"]},
    {"label": "short, stdout", "mode": "stdout", "args": ["-t", "-gcno={gcno}", "-gcda={gcda}"]},
    {"label": "single dash, stdout", "mode": "stdout", "args": ["-stdout", "-gcno={gcno}", "-gcda={gcda}"]},
    {"label": "long, branches, files", "mode": "files", "args": ["--branch-probabilities", "--gcno={gcno}", "--gcda={gcda}"]},
    {"label": "long, files", "mode": "files", "args": ["--gcno={gcno}", "--gcda={gcda}"]},
    {"label": "single dash, files", "mode": "files", "args": ["-gcno={gcno}", "-gcda={gcda}"]},
)
SPELLING_FILE = "gcov-spelling.json"
CHECK_C = "int twice(int x) {\n  return 2 * x;\n}\nint never(int x) {\n  return x;\n}\nint main(void) {\n  return twice(0);\n}\n"


def gcov_text(llvm_cov: str, spelling: dict, gcno: Path, gcda: Path, run=subprocess.run) -> str:
    """The .gcov text `llvm-cov gcov` gives for one object, spelled as `spelling` says: its stdout, or the .gcov files it wrote in a directory of its own."""
    import tempfile
    argv = [llvm_cov, "gcov"] + [a.format(gcno=gcno, gcda=gcda) for a in spelling["args"]] + [str(gcno)]
    if spelling["mode"] == "stdout":
        done = run(argv, capture_output=True, text=True, check=False, cwd=str(gcno.parent))
        text = done.stdout or ""
    else:
        with tempfile.TemporaryDirectory() as tmp:
            done = run(argv, capture_output=True, text=True, check=False, cwd=tmp)
            text = "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(Path(tmp).glob("*.gcov")))
    if done.returncode != 0:
        raise RuntimeError("llvm-cov exited %d on %s: %s" % (done.returncode, gcno.name, (done.stderr or done.stdout or "").strip()[:300]))
    if not text.strip():
        raise RuntimeError("llvm-cov printed no .gcov text for %s (%s)" % (gcno.name, spelling["label"]))
    return text


def help_options(text: str) -> set:
    """The names of the options a help text lists, whatever their dashes: `-b`, `--stdout`, `-gcno=<gcno>` -> b, stdout, gcno."""
    return set(re.findall(r"(?<![\w-])-{1,2}([A-Za-z][\w-]*)", text))


def spelling_by_help(text: str):
    """The first spelling all of whose options the help lists (with a single dash, two, or as a short form), else None."""
    listed = help_options(text)
    for spelling in GCOV_SPELLINGS:
        if all(a.lstrip("-").split("=")[0] in listed for a in spelling["args"]):
            return spelling
    return None


def smoke_ok(files: dict) -> bool:
    rec = files.get("t.c", {"lines": {}})
    return rec["lines"].get(2, 0) >= 1 and rec["lines"].get(5) == 0


def check_tools(objdir: Path, run=subprocess.run, work=None) -> str:
    """The build's llvm-cov and which spelling of `llvm-cov gcov` this one takes, said right after the toolchain's bootstrap, before an hour of
    compiling. It prints `llvm-cov --version` and the whole of `gcov --help`. The authority is a program of a few lines built and run here with the
    build's own clang: each spelling is tried, in order, on its profile, and the first that gives a file the parser reads, with line 2 run and line 5
    not, is kept (and written to <objdir>/gcov-spelling.json, which the notes carry to the suites). If the program cannot be built here, the first
    spelling the help text lists is kept. Red only when none works."""
    import tempfile
    llvm_cov = find_llvm_cov(objdir)
    version = run([str(llvm_cov), "--version"], capture_output=True, text=True, check=False)
    print("llvm-cov --version:\n%s" % ((version.stdout or "") + (version.stderr or "")).strip())
    helped = run([str(llvm_cov), "gcov", "--help"], capture_output=True, text=True, check=False)
    help_text = (helped.stdout or "") + (helped.stderr or "")
    print("llvm-cov gcov --help:\n%s" % help_text.strip())
    chosen, how = None, ""
    clang = Path(llvm_cov).parent / "clang"
    failed = "no clang beside llvm-cov"
    if clang.is_file():
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(work or tmp)
            tmp.mkdir(parents=True, exist_ok=True)
            (tmp / "t.c").write_text(CHECK_C, encoding="utf-8", newline="\n")
            failed = None
            for cmd in ([str(clang), "--coverage", "-O0", "-c", "t.c", "-o", "t.o"], [str(clang), "--coverage", "t.o", "-o", "t"], [str(tmp / "t")]):
                done = run(cmd, capture_output=True, text=True, check=False, cwd=str(tmp))
                if done.returncode != 0:
                    failed = (done.stderr or done.stdout or "").strip()[:200] or "exit %d" % done.returncode
                    break
            if failed is None:
                tried = []
                for spelling in GCOV_SPELLINGS:
                    try:
                        text = gcov_text(str(llvm_cov), spelling, tmp / "t.gcno", tmp / "t.gcda", run)
                        ok = smoke_ok(parse_gcov_text(text, str(tmp), {"t.c"}, None, str(tmp)))
                        tried.append("%s: %s" % (spelling["label"], "read, but not the program's lines" if not ok else "ok"))
                    except RuntimeError as exc:
                        ok = False
                        tried.append("%s: %s" % (spelling["label"], str(exc)[:160]))
                    if ok:
                        chosen, how = spelling, "smoke test"
                        break
                if chosen is None:
                    raise SystemExit("ERROR: no spelling of `llvm-cov gcov` gave a file the export reads on a program of a few lines:\n  %s" % "\n  ".join(tried))
    if chosen is None:
        print("warning: the check program did not build and run (%s): the spelling is taken from the help text" % failed)
        chosen, how = spelling_by_help(help_text), "help text"
        if chosen is None:
            raise SystemExit("ERROR: %s gcov lists no spelling of the options the export uses (--gcno, --gcda, and --stdout or files), and no program "
                             "could be built to try them" % llvm_cov)
    print("gcov spelling: %s (%s): %s" % (chosen["label"], how, " ".join(chosen["args"])))
    Path(objdir).mkdir(parents=True, exist_ok=True)
    (Path(objdir) / SPELLING_FILE).write_text(json.dumps(dict(chosen, chosen_by=how), indent=1) + "\n", encoding="utf-8", newline="\n")
    return str(llvm_cov)


def bundle(series_root: Path, objdir: Path, topsrcdir: str, out: Path, llvm_cov: Path = None, version=lambda cmd: "", rust_tools: Path = None) -> dict:
    interest = interest_files(series_root)
    links = header_links(objdir, topsrcdir, set(interest))
    chosen, compiled = scan_notes(objdir, topsrcdir, set(interest), links)
    for rel in chosen:
        target = Path(out) / "gcno" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(topsrcdir) / rel, target)
    interest_js = interest_js_files(series_root)
    interest_rs = interest_rs_files(series_root)
    sources = 0
    for rel in interest + interest_js + interest_rs:
        if (Path(topsrcdir) / rel).is_file():
            target = Path(out) / "sources" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(topsrcdir) / rel, target)
            sources += 1
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "compiled.json").write_text(json.dumps(sorted(compiled), indent=1) + "\n", encoding="utf-8")
    (Path(out) / "interest.json").write_text(json.dumps(interest, indent=1) + "\n", encoding="utf-8")
    (Path(out) / "interest-js.json").write_text(json.dumps(interest_js, indent=1) + "\n", encoding="utf-8")
    (Path(out) / "interest-rs.json").write_text(json.dumps(interest_rs, indent=1) + "\n", encoding="utf-8")
    for name in ("llvm-cov", "llvm-profdata"):
        if rust_tools and (Path(rust_tools) / name).is_file():
            shutil.copy2(Path(rust_tools) / name, Path(out) / ("rust-" + name))
            os.chmod(Path(out) / ("rust-" + name), 0o755)
    (Path(out) / "topsrcdir.txt").write_text(topsrcdir + "\n", encoding="utf-8")
    if (Path(objdir) / SPELLING_FILE).is_file():
        shutil.copy2(Path(objdir) / SPELLING_FILE, Path(out) / SPELLING_FILE)
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
    return {"interest": len(interest), "gcno": len(chosen), "compiled": len(compiled), "sources": sources, "header_links": len(links), "interest_js": len(interest_js), "interest_rs": len(interest_rs)}


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


def convert_one(llvm_cov: str, gcno: Path, gcda: Path, topsrcdir: str, interest: set, run=subprocess.run, links: dict = None, base: str = "",
                spelling: dict = None) -> dict:
    """One object's profile through `llvm-cov gcov`: the text it gives for each source file the object names (the headers too)."""
    return parse_gcov_text(gcov_text(llvm_cov, spelling or GCOV_SPELLINGS[0], gcno, gcda, run), topsrcdir, interest, links, base)


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


def export(notes: Path, gcda_root: Path, suite: str, out: Path, jobs: int = 4, rc=None, junit=None, raw=None, run=subprocess.run,
           js_dir=None, sandbox: str = "off", rust_dir=None, objects=()) -> dict:
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
    spelling_file = notes / SPELLING_FILE
    spelling = json.loads(spelling_file.read_text(encoding="utf-8")) if spelling_file.is_file() else None
    if spelling is None:
        # no check on the node: the first spelling that gives a text for the first profile
        for candidate in GCOV_SPELLINGS:
            try:
                gcov_text(llvm_cov, candidate, pairs[0][0], pairs[0][1], run)
            except RuntimeError:
                continue
            spelling = dict(candidate, chosen_by="the first profile of this suite")
            break
    files: dict = {}
    errors: list = []

    def one(pair):
        try:
            return convert_one(llvm_cov, pair[0], pair[1], topsrcdir, interest, run, links,
                               str(Path(topsrcdir) / pair[0].relative_to(notes / "gcno").parent), spelling)
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
    js_seen = js_unresolved = 0
    if js_dir and Path(js_dir).is_dir():
        js_path = notes / "interest-js.json"
        found, js_seen, js_unresolved = js_files(Path(js_dir), json.loads(js_path.read_text(encoding="utf-8")) if js_path.is_file() else [])
        merge(files, found)
    rust_raw = 0
    if rust_dir:
        rs_path = notes / "interest-rs.json"
        found, rust_raw = rust_files(Path(rust_dir), notes, [Path(o) for o in objects], topsrcdir,
                                     json.loads(rs_path.read_text(encoding="utf-8")) if rs_path.is_file() else [], run)
        merge(files, found)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ("%s.info" % suite)).write_text(to_lcov(files, suite), encoding="utf-8", newline="\n")
    meta = {"suite": suite, "rc": rc, "gcov_command": ((spelling or {}).get("label"), (spelling or {}).get("args"), (spelling or {}).get("chosen_by")), "gcda_files": len(pairs), "export_errors": len(errors), "files": len(files), "sandbox": sandbox,
            "js_info_files": js_seen, "rust_profraw_files": rust_raw, "js_unresolved_scripts": js_unresolved,
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
    b.add_argument("--rust-tools", type=Path, help="the bin directory of the rustc's llvm-tools (llvm-cov, llvm-profdata): a run that measures Rust")
    k = sub.add_parser("check-tools")
    k.add_argument("--objdir", type=Path, required=True)
    e = sub.add_parser("env")
    e.add_argument("--notes", type=Path, required=True)
    e.add_argument("--prefix", type=Path, required=True)
    e.add_argument("--js", type=Path, help="the directory SpiderMonkey writes its lcov into (JS_CODE_COVERAGE_OUTPUT_DIR)")
    e.add_argument("--rust", type=Path, help="the directory the Rust code's .profraw files go to (LLVM_PROFILE_FILE), when the notes have the Rust tools")
    x = sub.add_parser("export")
    x.add_argument("--notes", type=Path, required=True)
    x.add_argument("--gcda", type=Path, required=True)
    x.add_argument("--suite", required=True)
    x.add_argument("--out", type=Path, required=True)
    x.add_argument("--rc", type=int)
    x.add_argument("--junit", type=Path)
    x.add_argument("--jobs", type=int, default=4)
    x.add_argument("--raw", type=Path)
    x.add_argument("--js", type=Path, help="the directory SpiderMonkey wrote its lcov into")
    x.add_argument("--rust", type=Path, help="the directory the .profraw files of the Rust code were written to")
    x.add_argument("--object", type=Path, action="append", default=[], help="a binary with Rust coverage mapping (libxul.so)")
    x.add_argument("--sandbox", choices=("on", "off"), default="off", help="whether the browser's sandbox was on in this suite")
    a = ap.parse_args(argv)
    if a.cmd == "bundle":
        llvm_cov = a.llvm_cov or find_llvm_cov(a.objdir)

        def version(cmd):
            done = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return done.stdout.strip() + "\n"
        print(json.dumps(bundle(a.series_root, a.objdir, a.topsrcdir, a.out, llvm_cov, version, a.rust_tools), sort_keys=True))
    elif a.cmd == "check-tools":
        print("llvm-cov: %s" % check_tools(a.objdir))
    elif a.cmd == "env":
        top = (a.notes / "topsrcdir.txt").read_text(encoding="utf-8").strip()
        print("GCOV_PREFIX=%s" % a.prefix.resolve())
        print("GCOV_PREFIX_STRIP=%d" % strip_count(top))
        if a.js:
            print("JS_CODE_COVERAGE_OUTPUT_DIR=%s" % a.js.resolve())
        if a.rust and (a.notes / "rust-llvm-cov").is_file():
            print("LLVM_PROFILE_FILE=%s" % (a.rust.resolve() / "%p-%m.profraw"))
    else:
        print(json.dumps(export(a.notes, a.gcda, a.suite, a.out, a.jobs, a.rc, a.junit, a.raw, js_dir=a.js, sandbox=a.sandbox, rust_dir=a.rust, objects=a.object), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
