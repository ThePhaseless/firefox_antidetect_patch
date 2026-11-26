"""The export gate tests the series it is about to write, not the old one, and the checkout takes it only when it is green.

The restack rehearsal found the fault: a commit of tools that changes what `export` writes has tests of the series (tools/tests) that
are red until that export has written, and the gate, which ran them on the checkout BEFORE the write, refused the very export that
turns them green (14 tests were red at that point, and the rehearsal had to edit around the gate by hand). The gate now writes the
series into a scratch copy of the checkout, runs `engine.py check` and `tools/tests` there, and only then replaces the series of the
checkout. These tests show it on a small series (the real tools, an empty inventory, no Firefox) and a two-commit source repository:

  * the rehearsal case, red on the old order and green on the new one;
  * a red on the series written leaves the checkout byte for byte as it was, and the scratch tree is gone;
  * the engine tree's tests run first and stop the export before anything is copied or written;
  * the checkout takes exactly what the export wrote (a folder the head no longer owns goes), and a re-export that changes nothing
    touches no file.

    python -m pytest -q tools/tests/test_export_gate_tests_what_it_writes.py
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import engine  # noqa: E402
import export_gate  # noqa: E402

IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid"}
OURS = "browser/fonts/StealthFonts.cpp"                    # a file of ours that layout.OWN_FILES gives to this folder
FOLDER = "fingerprint/fonts/bundle"
# the test the tools change adds: it reads what the export writes, so it is red on the series before the export
THE_TOOLS_TEST = '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_export_wrote_the_folder_of_our_file():
    assert "%s" in (ROOT / "SERIES").read_text(encoding="utf-8").split()
    assert (ROOT / "%s" / "src" / "%s").is_file()
''' % (FOLDER, FOLDER, OURS)


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **IDENTITY}).stdout.strip()


def snapshot(root: Path) -> dict:
    """Every file of the checkout (not .git, not __pycache__) with its bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts and "__pycache__" not in p.relative_to(root).parts}


@pytest.fixture
def world(tmp_path):
    """(series, source, head): a series whose tools carry a test that needs the export, and a source whose head adds one file of ours."""
    source = tmp_path / "firefox"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "core.autocrlf", "false")
    (source / "README").write_bytes(b"mozilla\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "upstream")
    git(source, "tag", "FIREFOX_159_0_RELEASE")
    (source / OURS).parent.mkdir(parents=True)
    (source / OURS).write_bytes(b"// ours\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "ours")

    series = tmp_path / "series"
    (series / "tools" / "tests").mkdir(parents=True)
    for tool in TOOLS.glob("*.py"):
        shutil.copy(tool, series / "tools" / tool.name)
    for name, empty in {"hook-budget.json": {}, "removed-budget.json": {}, "hook-debt.json": [], "inventory.json": [],
                        "hook-budget-raises.json": [], "budget-realign-69.json": []}.items():
        (series / "tools" / name).write_text(json.dumps(empty) + "\n", encoding="utf-8")
    shutil.copy(TOOLS / "hook-names.json", series / "tools" / "hook-names.json")
    ledger = json.loads((TOOLS / "birth-ledger.json").read_text(encoding="utf-8"))
    ledger.update(entries=[], chrome_js_http={})
    (series / "tools" / "birth-ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    (series / "UPSTREAM.json").write_text(json.dumps({"mozilla_tag": "FIREFOX_159_0_RELEASE", "source_branch": "main", "exported_from": "",
                                                      "exported_tree": ""}), encoding="utf-8")
    (series / "SERIES").write_text("", encoding="utf-8")
    (series / FOLDER).mkdir(parents=True)                  # series-02: the folder states its relation to Mozilla, by hand
    (series / FOLDER / "FOLDER.json").write_text(json.dumps({"relation": "product"}, indent=1) + chr(10), encoding="utf-8")
    (series / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    git(series, "init", "-q")
    git(series, "add", "-A")
    git(series, "commit", "-qm", "main")
    git(series, "update-ref", "refs/remotes/origin/main", "HEAD")
    # the commit of tools under test, not committed yet: the scratch copy must carry it
    (series / "tools" / "tests" / "test_the_export_wrote_the_folder.py").write_text(THE_TOOLS_TEST, encoding="utf-8")
    return series, source, git(source, "rev-parse", "HEAD")


def run_gate(world, gate=None):
    """`engine.py export` of the series of `world`: the engine of this module, pointed at the series, through the gate."""
    series, source, head = world
    with engine.rebased(series):
        (gate or export_gate.gate)(source, head, lambda scratch: engine.export_into(scratch, source, "FIREFOX_159_0_RELEASE", head), series)


@pytest.fixture(autouse=True)
def no_engine_tree(monkeypatch):
    """The engine tree's tests need Node and a whole Firefox tree: here they are green, and two tests say what they do."""
    monkeypatch.setattr(export_gate, "run_engine_tree_tests", lambda source, head: [])


def old_order(source, head, write, root):
    """The gate as it was: the series tests on the checkout as it is, then the write. Kept to show what it refused."""
    problems = export_gate.run_series_tests(root)
    if problems:
        raise SystemExit("export refused: red before the write:\n  " + "\n  ".join(problems))
    write(root)


def worktrees(series: Path) -> list:
    return [line for line in git(series, "worktree", "list").splitlines() if line.strip()]


def test_the_rehearsal_case_is_refused_by_the_old_order_and_written_by_the_new_one(world):
    series, source, head = world
    before = snapshot(series)
    # the old order: the tests of the tools commit are red on the old series, so the export that turns them green is refused
    with pytest.raises(SystemExit, match="(?s)red before the write.*test_the_export_wrote_the_folder_of_our_file"):
        run_gate(world, gate=old_order)
    assert snapshot(series) == before and not (series / FOLDER / "src").exists()
    # the new order: the same tests run on the series the export writes, and they are green
    run_gate(world)
    assert (series / FOLDER / "src" / OURS).read_bytes() == b"// ours\n"
    assert (series / "SERIES").read_text(encoding="utf-8") == FOLDER + "\n"
    assert json.loads((series / "UPSTREAM.json").read_text(encoding="utf-8"))["exported_from"] == head
    assert export_gate.run_series_tests(series) == [], "what the checkout took passes the tests where they live"
    assert export_gate.run_series_check(series) == []
    assert len(worktrees(series)) == 1, "the scratch tree is registered nowhere after the export"


def test_a_red_on_the_series_it_writes_leaves_the_checkout_byte_identical(world, capsys):
    series, source, head = world
    (series / "tools" / "tests" / "test_a_second_one.py").write_text(
        "def test_red_even_on_the_series_written():\n    assert False, 'red on what export writes'\n", encoding="utf-8")
    before = snapshot(series)
    status = git(series, "status", "--porcelain", "--ignored")
    with pytest.raises(SystemExit) as stopped:
        run_gate(world)
    message = str(stopped.value)
    assert message.startswith("FAIL ") and "red on what export writes" in message, message
    assert "\nnext: " in message and "Rule: docs/decisions/series-01-export-is-the-only-writer.md" in message, message
    assert snapshot(series) == before and not (series / FOLDER / "src").exists()
    assert git(series, "status", "--porcelain", "--ignored").replace("__pycache__/", "") == status.replace("__pycache__/", "")
    assert len(worktrees(series)) == 1, "the scratch tree is removed on a red"
    assert not any(Path(line.split()[0]).name == "s" for line in worktrees(series)[1:])


def test_the_engine_tree_tests_run_before_anything_is_written(world, monkeypatch):
    series, source, head = world
    order = []
    monkeypatch.setattr(export_gate, "scratch_series", lambda root: order.append("scratch") or pytest.fail("scratch made"))
    monkeypatch.setattr(export_gate, "run_engine_tree_tests", lambda source, head: order.append("engine tree") or ["a node test is red"])
    before = snapshot(series)
    with pytest.raises(SystemExit, match="a node test is red") as stopped:
        export_gate.gate(source, head, lambda scratch: order.append("write"), series)
    assert order == ["engine tree"], "a red node test stops the export before the scratch copy and the write"
    assert "\nnext: " in str(stopped.value) and snapshot(series) == before


def test_the_engine_tree_tests_come_first_when_all_is_green(world, monkeypatch):
    series, source, head = world
    order = []
    monkeypatch.setattr(export_gate, "run_engine_tree_tests", lambda source, head: order.append("engine tree") or [])
    monkeypatch.setattr(export_gate, "run_series_check", lambda tree: order.append("check") or [])
    monkeypatch.setattr(export_gate, "run_series_tests", lambda tree: order.append("series tests") or [])
    export_gate.gate(source, head, lambda scratch: order.append("write"), series)
    assert order == ["engine tree", "write", "check", "series tests"]


def test_the_checkout_takes_exactly_what_the_export_wrote_and_a_no_op_touches_nothing(world, monkeypatch):
    series, source, head = world
    monkeypatch.setattr(export_gate, "run_series_tests", lambda tree: [])      # the tests are the subject of the others
    run_gate(world)
    # a folder the head no longer owns, left by an older export, goes with its files; a stale file of a kept folder goes too
    stale = series / "port" / "old"
    (stale / "src").mkdir(parents=True)
    (stale / "src" / "x.cpp").write_bytes(b"x\n")
    (stale / "MANIFEST.json").write_text(json.dumps({"modified": [], "added": {"x.cpp": "100644"}}), encoding="utf-8")
    (stale / "FEATURE.md").write_text("# port/old\n", encoding="utf-8")
    (series / "SERIES").write_text("%s\nport/old\n" % FOLDER, encoding="utf-8")
    (series / FOLDER / "src" / "browser" / "fonts" / "Leftover.cpp").write_bytes(b"left\n")
    run_gate(world)
    assert not stale.exists(), "a folder that owns nothing is removed with everything in it"
    assert not (series / FOLDER / "src" / "browser" / "fonts" / "Leftover.cpp").exists()
    assert (series / "SERIES").read_text(encoding="utf-8") == FOLDER + "\n"
    # a re-export that changes nothing: no file is rewritten
    stamps = {p: p.stat().st_mtime_ns for p in series.rglob("*") if p.is_file() and ".git" not in p.relative_to(series).parts
              and "__pycache__" not in p.parts}
    after = snapshot(series)
    run_gate(world)
    assert snapshot(series) == after
    assert {p: p.stat().st_mtime_ns for p in stamps} == stamps


def test_a_path_constant_of_engine_follows_the_scratch_root_and_comes_back(tmp_path):
    here = engine.ROOT
    named = {n: v for n, v in vars(engine).items() if isinstance(v, Path) and (v == here or here in v.parents)}
    assert {"ROOT", "UPSTREAM", "INVENTORY", "BUDGET", "REMOVED_BUDGET", "HOOK_DEBT", "WORKFLOWS_ROOT"} <= set(named)
    with engine.rebased(tmp_path):
        for name, value in named.items():
            assert getattr(engine, name) == tmp_path / value.relative_to(here), name
    for name, value in named.items():
        assert getattr(engine, name) == value, name


def test_the_series_tests_run_in_parallel_and_the_gate_has_no_switch():
    text = Path(export_gate.__file__).read_text(encoding="utf-8")
    assert '"-n", "auto"' in text and '"tools/tests"' in text
    assert "environ" not in text[text.index("def gate("):], "nothing in the gate reads a variable that could skip it"
