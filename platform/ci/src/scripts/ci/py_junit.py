#!/usr/bin/env python3
"""Which python tests of OURS the `checks` job runs with pytest, for the junit the named hook tests judge reads (`junit-py`, nodes `py:<path>::<name>`).

The tree the job materializes holds Mozilla's python tests (marionette, mach, ...) and ours; only ours are run. Ours are the files the series ADDS: the
`test_*.py` of `<group>/<folder>/src/<path in the tree>`. Left out, on purpose: scripts/ci/ (the plan job's cases, run by test_ci.py, with their own runners)
and scripts/tests/ (smoke tests that need a browser and the wrapper). A file with no `def test_` / `class Test` has nothing for pytest to collect (its checks
run in `__main__`, as `python3 scripts/test_make_seal.py` does in the same job), so it is not listed: a hook cannot name a test it does not have.

    python3 scripts/ci/py_junit.py list --series .series --tree .

Prints the paths in the tree, one per line, sorted.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: Folders of the tree whose python tests are not for pytest in `checks` (see the docstring).
SKIPPED = ("scripts/ci/", "scripts/tests/")
HAS_TESTS = re.compile(r"^(?:def test_|async def test_|class Test)", re.M)


def ours(series: Path, tree: Path) -> list:
    """The python tests of ours that exist in `tree`, collectable by pytest, as paths in the tree."""
    found = set()
    for src in sorted(Path(series).glob("*/*/src")):
        for path in src.rglob("test_*.py"):
            rel = path.relative_to(src).as_posix()
            if rel.startswith(SKIPPED) or not (Path(tree) / rel).is_file():
                continue
            if HAS_TESTS.search(path.read_text(encoding="utf-8", errors="replace")):
                found.add(rel)
    return sorted(found)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--series", required=True, type=Path)
    ls.add_argument("--tree", required=True, type=Path)
    args = ap.parse_args(argv)
    files = ours(args.series, args.tree)
    for rel in files:
        print(rel)
    if not files:
        print("py_junit: no python test of ours in %s" % args.series, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
