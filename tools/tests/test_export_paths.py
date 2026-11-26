"""The classes of what the export writes (tools/export_paths.py), which the series rule «export commits are named export:» reads.

  * the three classes, by example;
  * the names `engine.py` and `gtest_list.py` write by are the ones of export_paths.py (one place);
  * a whole export in a throwaway series: every file it writes is mixed or pure, so an export that starts writing a file of a new kind turns this red until the
    class of that file is decided in export_paths.py (with the negative control: a path no class covers is found).

    python -m pytest -q tools/tests/test_export_paths.py
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402
import export_paths  # noqa: E402
import gtest_list  # noqa: E402
from test_apply_builds_the_layer_stack import run, world  # noqa: E402,F401
from test_series_writes_what_it_computes import exported  # noqa: E402,F401


def snapshot(root: Path) -> dict:
    """path -> (modification time in ns, size): a file the export writes again with the same bytes is a write too."""
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def uncovered(paths) -> list:
    """The paths that no class of export_paths.py covers (the series-own ones): what an export may not write."""
    return sorted(p for p in paths if export_paths.kind(p) == export_paths.OWN)


def test_mixed_is_what_the_export_writes_and_a_hand_adds_to():
    for path in ("automation/juggler/MANIFEST.json", "network/doh/HOOKS.json", "fingerprint/screen-window/geometry/HOOKS.json", "platform/ci/FEATURE.md", "MANIFEST.json"):
        assert export_paths.kind(path) == export_paths.MIXED, path


def test_pure_is_what_the_export_writes_and_nobody_edits():
    for path in ("automation/juggler/hooks.patch", "a/b/c/hooks.patch", "automation/x/src/a.js", "platform/ci/src/scripts/ci/a.py", "platform/ci/src/.github/workflows/checks.yml",
                 "SERIES", "UPSTREAM.json", "tools/gtest-suites.json", "tools/hook-budget.json", "tools/removed-budget.json",
                 ".github/workflows/checks.yml", ".github/workflows/release.yml"):
        assert export_paths.kind(path) == export_paths.PURE, path


def test_own_is_everything_else_and_the_root_only_workflows():
    for path in ("tools/engine.py", "tools/hook-budget-raises.json", "tools/churn.json", "tools/birth-ledger.json", "docs/a.md", "src/a.py", "a/src", "a/srcs/b",
                 ".github/workflows/series.yml", ".github/workflows/noreply-identity.yml", ".github/other/x.yml", ".github/workflows/sub/x.yml", "a/MANIFEST.jsonl", "FEATURE.md",
                 "UPSTREAM.json.bak"):
        assert export_paths.kind(path) == export_paths.OWN, path


def test_the_names_the_engine_writes_by_are_the_ones_of_the_classes():
    root = engine.ROOT
    assert engine.UPSTREAM == root / export_paths.UPSTREAM and engine.BUDGET == root / export_paths.BUDGET and engine.REMOVED_BUDGET == root / export_paths.REMOVED_BUDGET
    assert engine.WORKFLOWS_ROOT == root / export_paths.WORKFLOWS_ROOT and engine.WORKFLOWS_SERIES == root / export_paths.WORKFLOWS_SERIES
    assert engine.ROOT_ONLY_WORKFLOWS == set(export_paths.ROOT_ONLY_WORKFLOWS) and gtest_list.FILE == export_paths.GTEST_SUITES
    for name in (export_paths.UPSTREAM, export_paths.BUDGET, export_paths.REMOVED_BUDGET, export_paths.GTEST_SUITES, export_paths.SERIES):
        assert export_paths.kind(name) == export_paths.PURE, name


def test_a_path_no_class_covers_is_found():
    assert uncovered(["automation/x/src/a.js", "network/doh/HOOKS.json", "tools/new-thing.json"]) == ["tools/new-thing.json"]


def whole_export(exported) -> list:
    """The files a whole export writes into the throwaway series, as paths of the series."""
    world_, root, inventory, budget, removed = exported
    before = snapshot(root)
    engine.export(world_, "TAG", "series")
    after = snapshot(root)
    return sorted(p for p, stamp in after.items() if before.get(p) != stamp)


def test_an_export_that_starts_writing_a_file_of_a_new_kind_is_found(exported, monkeypatch):
    real = engine.write_gtest_list

    def writes_one_more() -> str:
        (engine.ROOT / "tools").mkdir(exist_ok=True)
        (engine.ROOT / "tools" / "a-new-file.json").write_text("{}\n", encoding="utf-8")
        return real()

    monkeypatch.setattr(engine, "write_gtest_list", writes_one_more)
    assert uncovered(whole_export(exported)) == ["tools/a-new-file.json"]


def test_every_file_a_whole_export_writes_is_mixed_or_pure(exported):
    _, _, _, budget, removed = exported
    written = whole_export(exported)
    assert written, "the export wrote nothing: the test looks at nothing"
    assert uncovered(written) == [], "the export writes a file that no class of tools/export_paths.py covers: decide its class there"
    kinds = {export_paths.kind(p) for p in written}
    assert kinds == {export_paths.MIXED, export_paths.PURE}, (kinds, written)
    assert any(p.endswith("MANIFEST.json") for p in written) and any(p.endswith("hooks.patch") for p in written) and any("/src/" in p for p in written), written
    # the files outside the throwaway series that the export writes by name (the fixture moves them to a temporary directory)
    for name, copy in ((export_paths.BUDGET, budget), (export_paths.REMOVED_BUDGET, removed)):
        assert copy.is_file() and export_paths.kind(name) == export_paths.PURE
