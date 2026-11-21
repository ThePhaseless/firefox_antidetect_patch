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
  dirs     for each file the nearest directory, going up, that has a Makefile in the objdir (a
           source listed by a parent's moz.build belongs to the parent; a directory this build
           does not configure, the Windows ones on the Linux leg, is not a target and is said)

The tiers come first: `export` (generated headers, the IDL and IPDL ones) is what a directory
needs to compile alone, and the build runs it anyway. Then one `mach build --keep-going
<dir>/target-objects ...` for all the directories. mach stops at the first directory that fails
(--keep-going goes on inside one make only), so when that run fails each directory is run on its
own: every error of every directory comes out of ONE run, not one directory per run.

The errors are parsed out of the compilers' output (`file:line:col: error:` of clang, `file(line,col):
error:` of clang-cl), listed by file in the job summary and as annotations, and the step fails
if there is any, or if a mach run failed with none recognised (the last lines are then shown).

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


def touched_dirs(files, has_makefile) -> tuple:
    """(directories to compile, files with no directory in this build). `has_makefile(dir)` says
    whether the objdir has a Makefile there. A file goes up to the nearest directory that has one;
    the top of the tree is never a target (it is the whole build)."""
    dirs, outside = set(), []
    for path in files:
        if not is_compiled(path):
            continue
        d = posixpath.dirname(path)
        while d and not has_makefile(d):
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


def annotations(errors) -> list:
    return ["::error file=%s,line=%d::%s" % (p, l, m.replace("%", "%25").replace("\r", "").replace("\n", " "))
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
    code, lines = mach(targets, log)
    if code == 0:
        return 0, [], lines
    # mach stopped at the first directory that failed: each on its own, so the others' errors come out too.
    print("objects: a directory failed (exit %d); each one on its own, so that every error shows" % code, flush=True)
    failed, everything = [], list(lines)
    for d, target in zip(dirs, targets):
        one, more = mach([target], log)
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
    a = ap.parse_args(argv)
    leg = os.environ.get("CI_LEG", "")
    phase.LOGS.mkdir(parents=True, exist_ok=True)
    phase.event("objects", "start")
    began = time.monotonic()
    with (phase.LOGS / "objects.log").open("w", encoding="utf-8", errors="replace") as log:
        # The export tier first, and it configures: the objdir is what says which directories exist.
        code, lines = mach(["export"], log)
        errors, other = parse_errors(lines, os.getcwd())
        dirs, outside, failed = [], [], []
        if code == 0:
            base = a.base or tag_commit(json.loads(a.upstream.read_text(encoding="utf-8"))["mozilla_tag"])
            files = changed_files(base)
            dirs, outside = touched_dirs(files, lambda d: (a.objdir / d / "Makefile").is_file())
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
    say(text)
    phase.summary(text)
    for note in annotations(errors):
        print(note)
    phase.event("objects", "end", exit=1 if bad else 0, seconds=seconds, errors=["%s:%d: %s" % e for e in errors[:10]])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
