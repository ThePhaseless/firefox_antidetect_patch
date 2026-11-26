#!/usr/bin/env python3
"""Series rule: export commits are named `export:`.

    python3 scripts/ci/export_commit_names.py --repo <series checkout> --range BASE..HEAD

Judged on the non-merge commits of the range, by the paths each one changes (tree paths of the SERIES repository):

  EXPORTED  anything under `<folder>/src/**` (a folder of the series, at any depth: automation/juggler/src/..., platform/ci/src/...), every
            `MANIFEST.json` and every `hooks.patch`.
  SERIES-OWN every other path (tools/**, docs/**, .github/workflows/**, SERIES, UPSTREAM.json, ...).

  (A) a commit that touches ONLY exported paths has a subject that starts with `export: `;
  (B) a commit whose subject starts with `export:` touches ONLY exported paths.

A commit that touches both kinds and is not named `export:` is neither: it is not judged. A merge commit and a commit that touches no file are not judged.
One FAIL line per violation. Exit 0 and `OK <n> commits` when there is none, 1 on a violation, 2 on bad usage or a range git cannot read (never a pass
that read nothing).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

PREFIX = "export:"
RULE = "Rule: export commits are named export:"
SEP = "\x01"


def is_exported(path: str) -> bool:
    """True for <folder>/src/** (src below at least one folder, with something under it), MANIFEST.json and hooks.patch, at any depth."""
    parts = path.split("/")
    if parts[-1] in ("MANIFEST.json", "hooks.patch"):
        return True
    return "src" in parts[1:-1]


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
        exported = [p for p in paths if is_exported(p)]
        own = [p for p in paths if not is_exported(p)]
        short = sha[:10]
        if not own and not subject.startswith(PREFIX + " "):
            shown = ", ".join(exported[:3]) + (" and %d more" % (len(exported) - 3) if len(exported) > 3 else "")
            problems.append('FAIL %s "%s": it touches only exported paths (%s) and its subject does not start with "export: ". '
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
