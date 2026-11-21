"""The objects of every directory the series touches, compiled before the browser's build.

    python3 scripts/ci objects --upstream .series/UPSTREAM.json

A leg used to learn that one of our files does not compile after the link of the browser had
started, and then only the errors of the first directory it met. This step compiles, compile only
(`target-objects`: no archive, no link), every directory the series changes against the Mozilla
tag: the directories of the Mozilla files it modifies and those of our own files. The objdir is
the build's own and the flags are its flags, so the build that follows finds the objects made
(and the compile cache sees nothing different).

How the list is made, from the tree and the tag, nothing written by hand:

  base     the Mozilla tag's commit (refs/tags/<mozilla_tag> of UPSTREAM.json; on a node that
           shares the fetch the tag has no ref, and the tree's root commit, which is the shallow
           tag commit the series is applied on, is the same commit)
  files    `git diff --name-only base HEAD`, the ones that are compiled: C, C++, Objective-C
           sources and headers, assembly, and the build files (moz.build, *.mozbuild)
  dirs     for each file the nearest directory, going up, that has objects in the compile graph (see below; a
           source listed by a parent's moz.build belongs to the parent; a directory this build
           does not configure, the Windows ones on the Linux leg, is not a target and is said)

The tiers come first, the ones the build itself runs before it compiles anything. `mach build` is `make` on the
objdir, whose default target runs `$(TIERS)` in order (config/rules.mk:314-315, `$(foreach tier,$(TIERS),$(call SUBMAKE,$(tier)))`), and TIERS is pre-export, export, then
compile and the rest (config/baseconfig.mk:63). A directory compiles alone only with dist/include populated: that is
the pre-export tier's install-manifests (Makefile.in:55-59: `recurse_pre-export: install-manifests`), and the export tier
adds the generated headers (IDL, IPDL, WebIDL, cbindgen) on top of it. `export` alone ran 5 seconds and made a few
stubs (run 44942834683): so `./mach build --keep-going pre-export export`, two make runs in that order (a target with
no `/` is a top-level make target: python/mozbuild/mozbuild/util.py resolve_target_to_make; mach runs them one after
the other: controller/building.py:1510 "Build target pairs").

Then the directories, as nodes of the compile graph. Every directory with objects is a top-level make target
`<dir>/target-objects` (python/mozbuild/mozbuild/backend/recursivemake.py, _compile_graph), listed in the
objdir's root.mk as `compile_targets`, and config/recurse.mk:78-79 gives each the rule that recurses into the
directory after its graph dependencies (the generated sources of the pre-compile tier it needs). A directory with
no objects has no node: it is not a target. They are run as `./mach build --keep-going -C . <dir>/target-objects ...`:
`-C .` makes the target a top-level one (building.py:1462 `make_dir = join(topobjdir, directory)`), which keeps the graph's
dependencies; `mach build <dir>/target-objects` would run make inside the directory and lose them. mach stops at the first
directory that fails (--keep-going goes on inside one make only), so when that run fails each directory is run on its
own: every error of every directory comes out of ONE run, not one directory per run.

The errors are parsed out of the compilers' output (`file:line:col: error:` of clang, `file(line,col):
error:` of clang-cl), listed by file in the job summary and as annotations, and the step fails
if there is any, or if a mach run failed with none recognised (the last lines are then shown), but only with --strict
(the compile-only candidate, stop_after=objects). Without it the step reports and exits 0: a whole candidate goes on to
the real build, which would find the same errors anyway, and never loses a leg to this step.

    scripts/ci/test_objects_first.py holds its known-bad inputs.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import phase  # noqa: E402

# What a compile can fail on. Rust is the gkrust crate's, compiled in the build proper; the
# generated headers of IDL files are the export tier's.
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".m", ".mm", ".h", ".hh", ".hpp", ".hxx", ".s", ".asm")
MAX_ROWS = 200
MAX_ANNOTATIONS = 40

# mach puts the time in front of every line (` 0:33.95 `, then a W or an E for its own).
_STAMP = r"^\s*\d+:\d+(?:\.\d+)?\s+(?:[WE]\s+)?"
# clang: file:12:3: error: msg. clang-cl: file(12,3): error: msg. Also `fatal error:`.
ERROR_LINE = re.compile(
    r"(?:%s)?(?P<file>(?:[A-Za-z]:)?[^\s:()][^:()]*?)"
    r"(?::(?P<line>\d+)(?::\d+)?|\((?P<line2>\d+)(?:,\d+)?\)): (?:fatal )?error: (?P<msg>.*?)\s*$" % _STAMP)
# A compiler's or make's failure with no file: still a failure, listed apart.
OTHER_ERROR = re.compile(r"(^|\s)(error(\[\w+\])?:|ERROR\b|\*\*\* \[.*\] Error \d+|undefined reference|ld\.lld: error)")


def is_compiled(path: str) -> bool:
    name = posixpath.basename(path)
    return path.lower().endswith(SOURCE_SUFFIXES) or name == "moz.build" or name.endswith(".mozbuild")


def compile_targets(objdir: Path) -> set:
    """The `compile_targets` of the objdir's root.mk: the nodes of the compile graph, as `dir/target-objects`."""
    text = (objdir / "root.mk").read_text(encoding="utf-8", errors="replace")
    words, taking = [], False
    for line in text.splitlines():
        if not taking and re.match(r"compile_targets\s*:=", line):
            line, taking = line.split(":=", 1)[1], True
        elif not taking:
            continue
        more = line.rstrip().endswith("\\")
        words += line.rstrip().rstrip("\\").split()
        if not more:
            return set(words)
    raise SystemExit("ERROR: no compile_targets in %s: the backend did not run" % (objdir / "root.mk"))


def touched_dirs(files, has_objects) -> tuple:
    """(directories to compile, files with no directory in this build). `has_objects(dir)` says
    whether the compile graph has the directory's objects. A file goes up to the nearest directory that has
    them; the top of the tree is never a target (it is the whole build)."""
    dirs, outside = set(), []
    for path in files:
        if not is_compiled(path):
            continue
        d = posixpath.dirname(path)
        while d and not has_objects(d):
            d = posixpath.dirname(d)
        if d:
            dirs.add(d)
        else:
            outside.append(path)
    return sorted(dirs), sorted(outside)


def clean_path(path: str, root: str) -> str:
    """The file as the tree names it: no root of the checkout, no `../` of a make run from the objdir."""
    path = path.replace("\\", "/")
    root = root.replace("\\", "/").rstrip("/") + "/"
    if path.startswith(root):
        path = path[len(root):]
    path = posixpath.normpath(path)
    while path.startswith("../"):
        path = path[3:]
    return path


def parse_errors(lines, root: str = "") -> tuple:
    """([(file, line, message)] in order, without repeats; the count of other error lines)."""
    seen, found, other = set(), [], 0
    for text in lines:
        m = ERROR_LINE.match(text.rstrip())
        if m:
            row = (clean_path(m.group("file"), root), int(m.group("line") or m.group("line2")), m.group("msg"))
            if row not in seen:
                seen.add(row)
                found.append(row)
        elif OTHER_ERROR.search(text) and "warning" not in text.lower():
            other += 1
    return found, other


def render(leg: str, dirs, errors, failed, outside, other_lines=(), unparsed=()) -> str:
    """The job summary: what was built, and every error by file."""
    head = "%s **%s** objects: %d directories%s" % (
        "❌" if (errors or failed) else "✅", leg, len(dirs), (", %d errors in %d files" % (len(errors), len({e[0] for e in errors}))) if errors else "")
    out = [head, ""]
    if errors:
        out += ["| file | line | error |", "|---|---|---|"]
        for path, line, msg in errors[:MAX_ROWS]:
            out.append("| `%s` | %d | %s |" % (path, line, msg.replace("|", "\\|")))
        if len(errors) > MAX_ROWS:
            out.append("| | | %d more in logs/objects.log |" % (len(errors) - MAX_ROWS))
        out.append("")
    if failed:
        out.append("directories that failed: %s" % ", ".join("`%s`" % d for d in failed))
    if failed and not errors:
        out += ["", "no `file:line: error:` line was recognised; the last lines:", "", "```"] + list(unparsed)[-15:] + ["```"]
    if outside:
        out.append("files in no directory of this build (not compiled here): %s" % ", ".join("`%s`" % p for p in outside[:20]))
    return "\n".join(out)


def annotations(errors, level: str = "error") -> list:
    return ["::%s file=%s,line=%d::%s" % (level, p, l, m.replace("%", "%25").replace("\r", "").replace("\n", " "))
            for p, l, m in errors[:MAX_ANNOTATIONS]]


# ── what runs ────────────────────────────────────────────────────────────────────────────────

def say(text: str) -> None:
    """print, for a console that cannot show the summary's marks (a Windows one); the summary file has them either way."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def git(*args) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode:
        raise SystemExit("ERROR: git %s: %s" % (" ".join(args), done.stderr.strip()[-300:]))
    return done.stdout


def tag_commit(tag: str) -> str:
    """The Mozilla tag's commit: its ref when there is one, else the root of the tree's history (the shallow tag commit)."""
    done = subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/tags/%s^{commit}" % tag], capture_output=True, text=True)
    if done.returncode == 0 and done.stdout.strip():
        return done.stdout.strip()
    roots = git("rev-list", "--max-parents=0", "HEAD").split()
    if len(roots) != 1:
        raise SystemExit("ERROR: no ref for %s and %d root commits: the tag's commit is unknown" % (tag, len(roots)))
    return roots[0]


def changed_files(base: str) -> list:
    return [p for p in git("diff", "--name-only", "--no-renames", "-z", base, "HEAD").split("\0") if p]


def run_mach(args, log) -> tuple:
    """(exit code, lines) of one `./mach build --keep-going ...`; its output is the console's and the log's."""
    lines = []
    proc = subprocess.Popen(["./mach", "build", "--keep-going", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    for line in proc.stdout:
        sys.stdout.write(line)
        log.write(line)
        lines.append(line.rstrip("\n"))
    return proc.wait(), lines


def build_objects(dirs, mach=run_mach, log=None) -> tuple:
    """(0 or 1, [(dir, exit code)] of the ones that failed on their own, all the output lines)."""
    targets = ["%s/target-objects" % d for d in dirs]
    code, lines = mach(["-C", ".", *targets], log)
    if code == 0:
        return 0, [], lines
    # mach stopped at the first directory that failed: each on its own, so the others' errors come out too.
    print("objects: a directory failed (exit %d); each one on its own, so that every error shows" % code, flush=True)
    failed, everything = [], list(lines)
    for d, target in zip(dirs, targets):
        one, more = mach(["-C", ".", target], log)
        everything += more
        if one:
            failed.append((d, one))
    # Each alone is the truth: when none fails, the batch's failure was an interplay and the objects are all made.
    return (1 if failed else 0), failed, everything


def main(argv=None, mach=run_mach) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--upstream", type=Path, default=Path(".series/UPSTREAM.json"))
    ap.add_argument("--base", default="", help="the commit to compare with (default: the Mozilla tag's)")
    ap.add_argument("--objdir", type=Path, default=Path("obj-rel"))
    ap.add_argument("--strict", action="store_true", help="fail the step on any error (stop_after=objects); else report and exit 0")
    a = ap.parse_args(argv)
    leg = os.environ.get("CI_LEG", "")
    phase.LOGS.mkdir(parents=True, exist_ok=True)
    phase.event("objects", "start")
    began = time.monotonic()
    with (phase.LOGS / "objects.log").open("w", encoding="utf-8", errors="replace") as log:
        # The tiers the build runs before it compiles (the docstring says why both), and the first mach run configures:
        # the objdir's root.mk is what says which directories have objects.
        code, lines = mach(["pre-export", "export"], log)
        errors, other = parse_errors(lines, os.getcwd())
        dirs, outside, failed = [], [], []
        if code == 0:
            base = a.base or tag_commit(json.loads(a.upstream.read_text(encoding="utf-8"))["mozilla_tag"])
            files = changed_files(base)
            targets = compile_targets(a.objdir)
            dirs, outside = touched_dirs(files, lambda d: "%s/target-objects" % d in targets)
            print("objects: %d files differ from %s; %d are compiled; %d directories of this build:\n  %s"
                  % (len(files), base[:10], sum(1 for f in files if is_compiled(f)), len(dirs), "\n  ".join(dirs)), flush=True)
            if not dirs:
                print("ERROR: the series changes no directory of this build: the list is wrong", file=sys.stderr)
                code = 1
            else:
                code, failed, lines = build_objects(dirs, mach, log)
                found, more = parse_errors(lines, os.getcwd())
                errors, other = found, other + more
        else:
            failed = [(".", code)]
    seconds = round(time.monotonic() - began)
    bad = bool(errors or failed or code)
    text = render(leg, dirs, errors, [d for d, _ in failed], outside, unparsed=lines)
    if bad and not a.strict:
        text += "\n\nthis run goes on to the build (no stop_after=objects): the step does not fail the leg"
    say(text)
    phase.summary(text)
    for note in annotations(errors, "error" if a.strict else "warning"):
        print(note)
    phase.event("objects", "end", exit=1 if (bad and a.strict) else 0, seconds=seconds, found=1 if bad else 0,
                errors=["%s:%d: %s" % e for e in errors[:10]])
    return 1 if (bad and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
