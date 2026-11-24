#!/usr/bin/env python3
"""The series commit of an engine binary a job did not build: the commit whose tests that binary is tested with (decision ci-09).

    python scripts/ci/binary_series.py seal --dir <folder with the release's seal.json> [--github-output <file>] [--name series_commit]
    python scripts/ci/binary_series.py run --repo <owner/repo> --run-id <id> [--source-commit-dir <folder>] [--own-run-id <id> --own-sha <sha>]
                                           [--github-output <file>] [--name series_commit]

`seal`: the `series_commit` of the seal of a release (the archives are checked against the same seal by xpcshell_run.py verify-asset or
ab_package.py seal-check).
`run`: the series commit another run's build recorded (`series-commit.txt` of its artifact `source-commit`, downloaded into --source-commit-dir),
else the head_sha of that run (`gh api repos/<repo>/actions/runs/<id>`, GH_TOKEN from the environment). When the run is this run's own
(--run-id equal to --own-run-id) the binary was built from the commit that is checked out here: the series commit must equal --own-sha, and a
difference is an error, so the proof that the two commits are equal is made and not assumed.

The commit is printed and, with --github-output, appended as `<name>=<sha>` to that file (a step output). A value that is not a full commit sha
is an error, never an empty output.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")


class NoSeriesCommit(Exception):
    pass


def _sha(value, where: str) -> str:
    text = value.strip().lower() if isinstance(value, str) else ""
    if not SHA.fullmatch(text):
        raise NoSeriesCommit("%s: %r is not a full commit sha" % (where, value))
    return text


def from_seal(directory) -> str:
    path = Path(directory) / "seal.json"
    try:
        seal = json.loads(path.read_text(encoding="utf-8"))
        value = seal["series_commit"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise NoSeriesCommit("%s has no readable series_commit: %s" % (path, exc))
    return _sha(value, str(path))


def from_run(repo: str, run_id: str, source_commit_dir=None, own_run_id: str = "", own_sha: str = "") -> str:
    recorded = Path(source_commit_dir) / "series-commit.txt" if source_commit_dir else None
    if recorded is not None and recorded.is_file() and recorded.read_text(encoding="utf-8").strip():
        commit = _sha(recorded.read_text(encoding="utf-8"), "series-commit.txt of run %s" % run_id)
    else:
        done = subprocess.run(["gh", "api", "repos/%s/actions/runs/%s" % (repo, run_id), "--jq", ".head_sha"], capture_output=True, text=True)
        if done.returncode != 0:
            raise NoSeriesCommit("run %s recorded no series-commit.txt and gh api could not give its head_sha (%d): %s" % (run_id, done.returncode, done.stderr.strip()))
        commit = _sha(done.stdout, "head_sha of run %s" % run_id)
    if own_run_id and str(run_id) == str(own_run_id):
        if commit != _sha(own_sha, "the commit of this run"):
            raise NoSeriesCommit("the binary of this run was built from series commit %s but the tests are at %s" % (commit, own_sha))
    return commit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--dir", required=True)
    run = sub.add_parser("run")
    run.add_argument("--repo", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--source-commit-dir")
    run.add_argument("--own-run-id", default="")
    run.add_argument("--own-sha", default="")
    for p in (seal, run):
        p.add_argument("--github-output")
        p.add_argument("--name", default="series_commit")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "seal":
            commit = from_seal(args.dir)
        else:
            commit = from_run(args.repo, args.run_id, args.source_commit_dir, args.own_run_id, args.own_sha)
    except NoSeriesCommit as error:
        print("ERROR: %s" % error, file=sys.stderr)
        return 1
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8", newline="\n") as handle:
            handle.write("%s=%s\n" % (args.name, commit))
    print(commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
