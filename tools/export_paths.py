"""The paths `tools/engine.py export` writes, in three classes (the series rule «export commits are named `export:`», scripts/ci/export_commit_names.py).

The names below are the ones `engine.py` writes by (UPSTREAM, BUDGET, REMOVED_BUDGET, ROOT_ONLY_WORKFLOWS, the workflow copies) and `gtest_list.py` (GTEST_SUITES);
the rule reads this file from the series checkout it judges, so a path the export writes is a class here or the test of tools/tests that runs a whole export says
which one is missing.

  mixed  The export writes the file and a hand adds to it afterwards: the hand fields of HOOKS.json (test, anchor, why, exception, quiet_anchor_why), the text of the
         inventory records of MANIFEST.json (anchor, notes, hookable), the FEATURE.md stub of a folder the export makes. A hand commit may touch it; so may an export.
  pure   Everything else the export writes and nobody edits: <folder>/hooks.patch, everything under <folder>/src/, SERIES, UPSTREAM.json, tools/gtest-suites.json, the two
         budget files, the root copy of each workflow of the series (a workflow in ROOT_ONLY_WORKFLOWS is not copied: it is series-own).
  own    Every other path: tools, docs, the root-only workflows, ...

    kind(path) -> "mixed" | "pure" | "own"      (a path of the series, with `/`)

Nothing here imports the engine: the rule runs in a sparse checkout that holds this one file.
"""
from __future__ import annotations

MIXED = "mixed"
PURE = "pure"
OWN = "own"

PATCH = "hooks.patch"
MANIFEST = "MANIFEST.json"
HOOKS = "HOOKS.json"
FEATURE = "FEATURE.md"
SRC = "src"
SERIES = "SERIES"
UPSTREAM = "UPSTREAM.json"
BUDGET = "tools/hook-budget.json"
REMOVED_BUDGET = "tools/removed-budget.json"
GTEST_SUITES = "tools/gtest-suites.json"
WORKFLOWS_ROOT = ".github/workflows"
WORKFLOWS_SERIES = "platform/ci/src/.github/workflows"
ROOT_ONLY_WORKFLOWS = frozenset({"series.yml", "noreply-identity.yml"})

ROOT_FILES = frozenset({SERIES, UPSTREAM, BUDGET, REMOVED_BUDGET, GTEST_SUITES})
MIXED_NAMES = frozenset({MANIFEST, HOOKS})


def kind(path: str) -> str:
    """The class of a path of the series: how the export writes it, and whether a hand writes in it too."""
    parts = path.split("/")
    name = parts[-1]
    if SRC in parts[1:-1] or name == PATCH:
        return PURE                                    # <folder>/src/** and <folder>/hooks.patch (the folder at any depth)
    if name in MIXED_NAMES or (name == FEATURE and len(parts) > 1):
        return MIXED
    if path in ROOT_FILES:
        return PURE
    if len(parts) == 3 and "/".join(parts[:2]) == WORKFLOWS_ROOT and name.endswith(".yml") and name not in ROOT_ONLY_WORKFLOWS:
        return PURE                                    # the root copy of a workflow of the series, written by sync_workflows
    return OWN
