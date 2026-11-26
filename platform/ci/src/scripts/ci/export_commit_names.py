#!/usr/bin/env python3
"""Series rule: export commits are named `export:`.

    python3 scripts/ci/export_commit_names.py --repo <series checkout> --range BASE..HEAD

Judged on the non-merge commits of the range, by the class of each path they change (tree paths of the SERIES repository).

THE CLASSES come from the code that writes the paths, not from a list kept here: tools/export_paths.py of the series, which `tools/engine.py export` writes by (its
constants for UPSTREAM.json, the budget files, the workflow copies, gtest-suites.json are that file's, and a test of tools/tests runs a whole export and refuses a
file that no class covers, so an export that starts writing a new kind of file stays red until its class is decided there). This script finds that file beside
itself: in the series checkout it runs in (<series>/tools/export_paths.py, the exported path of this script being <series>/platform/ci/src/scripts/ci/) or, in a
source tree, in the series beside it (.series/tools/export_paths.py). Without it the rule stops with exit 2: a rule that cannot read its classes is never a pass.

  MIXED  the export writes the file and a hand adds to it: the hand fields of every HOOKS.json (test, anchor, why, exception), the text of the inventory records
         of every MANIFEST.json, the FEATURE.md stub of a folder the export makes.
  PURE   the rest of what the export writes: <folder>/hooks.patch, <folder>/src/**, SERIES, UPSTREAM.json, tools/gtest-suites.json, the two budget files, the root copy
         of each workflow of the series.
  OWN    every other path (tools/**, docs/**, the root-only workflows series.yml and noreply-identity.yml, ...).

  (A) a commit that touches ONLY pure paths has a subject that starts with `export: `;
  (B) a commit whose subject starts with `export:` touches only pure or mixed paths.

A hand commit may touch a mixed file, alone or with anything else; so may an export. A commit that touches pure paths with a mixed or own one and is not named `export:` is
neither (A) nor (B): it is not judged. A merge commit and a commit with no file are not judged.

WHAT THIS RULE DOES NOT SEE: a hand commit that edits the part of a mixed file that the export writes (the line, the form and the removed text of a HOOKS.json entry,
the `modified`, `added` and `sha256` of a MANIFEST.json, the counts of an inventory record). `python tools/engine.py check` sees it, on every pull request: it compares
HOOKS.json with the one `hooks_list.py` generates from hooks.patch (hooks_list.problems), the sha256 of every file under src/ (manifest_hash_problems) and the counts
and inline_logic_lines of every record with the hooks.patch (record_count_problems, record_inline_problems). `engine.py verify` does not: it rebuilds the tree from the
series and compares it with the source head, and no hand field is in that tree.

One FAIL line per violation. Exit 0 and `OK <n> commits` when there is none, 1 on a violation, 2 on bad usage, on a range git cannot read or on classes that cannot be
read (never a pass that read nothing).
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

PREFIX = "export:"
RULE = "Rule: export commits are named export:"
SEP = "\x01"


def _load_classes():
    """tools/export_paths.py of the series this script is part of, found beside it (see above); SystemExit(2) when there is none."""
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        for sub in ("tools", ".series/tools"):
            found = base / sub / "export_paths.py"
            if found.is_file():
                spec = importlib.util.spec_from_file_location("export_paths", found)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    print("tools/export_paths.py, the classes of what the export writes, is not in the series beside %s (tools/ or .series/tools/ of an ancestor folder)" % here,
          file=sys.stderr)
    raise SystemExit(2)


CLASSES = _load_classes()


def kind(path: str) -> str:
    """mixed, pure or own: the class of the path (tools/export_paths.py)."""
    return CLASSES.kind(path)


def is_exported(path: str) -> bool:
    """True for a path the export writes (mixed or pure)."""
    return kind(path) != CLASSES.OWN


def read_commits(repo: str, rng: str) -> list:
    """[(sha, subject, [paths])] of the non-merge commits of the range, newest first. SystemExit(2) when git cannot read the range."""
    if ".." not in rng or rng.startswith("..") or rng.endswith(".."):
        print("bad range %r: expected BASE..HEAD" % rng, file=sys.stderr)
        raise SystemExit(2)
    cmd = ["git", "-C", repo, "-c", "core.quotepath=false", "log", "--no-merges", "--name-only", "--format=" + SEP + "%H" + SEP + "%s", rng, "--"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        print("cannot run git: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
    if done.returncode != 0:
        print("git cannot read the range %s in %s: %s" % (rng, repo, done.stderr.strip()), file=sys.stderr)
        raise SystemExit(2)
    return _blocks(done.stdout)


def _blocks(text: str) -> list:
    """The output of git log as [(sha, subject, paths)]: each commit starts at a line that begins with SEP."""
    out = []
    current = None
    for line in text.splitlines():
        if line.startswith(SEP):
            _, sha, subject = line.split(SEP, 2)
            current = (sha, subject, [])
            out.append(current)
        elif line and current is not None:
            current[2].append(line)
    return out


def judge(commits: list) -> list:
    """One FAIL line per violation."""
    problems = []
    for sha, subject, paths in commits:
        if not paths:
            continue
        classes = {p: kind(p) for p in paths}
        pure = [p for p in paths if classes[p] == CLASSES.PURE]
        own = [p for p in paths if classes[p] == CLASSES.OWN]
        short = sha[:10]
        if pure and len(pure) == len(paths) and not subject.startswith(PREFIX + " "):
            shown = ", ".join(pure[:3]) + (" and %d more" % (len(pure) - 3) if len(pure) > 3 else "")
            problems.append('FAIL %s "%s": it touches only paths the export writes and nobody edits (%s) and its subject does not start with "export: ". '
                            'Fix: reword the subject to start with "export: " (git commit --amend or a reword rebase). %s' % (short, subject, shown, RULE))
        elif own and subject.startswith(PREFIX):
            shown = ", ".join(own[:3]) + (" and %d more" % (len(own) - 3) if len(own) > 3 else "")
            problems.append('FAIL %s "%s": its subject starts with "export:" and it touches series-own paths (%s). '
                            'Fix: move the series-own files into a commit of their own, or drop the "export:" prefix. %s' % (short, subject, shown, RULE))
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Judge that export commits are named export:, and only they.")
    parser.add_argument("--repo", required=True, help="a git checkout of the series (a partial clone is fine)")
    parser.add_argument("--range", required=True, dest="rng", help="BASE..HEAD")
    args = parser.parse_args(argv)
    commits = read_commits(args.repo, args.rng)
    problems = judge(commits)
    for line in problems:
        print(line)
    if problems:
        return 1
    print("OK %d commits" % len(commits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
