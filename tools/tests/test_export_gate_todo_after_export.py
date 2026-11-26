"""The export gate lets `check` miss two things, and only the ones this export itself made: the text of an inventory record the export
derived, and the churn rows of the hunks the export moved or created.

A restack rehearsal found that an export which has to be followed by a hand step could never pass the gate, because the gate runs `check`
on the series the export writes and `check` refuses both (the empty `anchor`/`notes`/`hookable` of a derived record, C18 for a hunk with no
row in tools/churn.json: a human writes the first, tools/churn.py writes the second and needs the release tags). The gate now says
`TODO after export: <file>: <what>. Fix: <step>` for those and goes on; `check` is not changed, so a pull request still refuses them.

The source is a file two folders patch (one marker each), exported once from a head that has the first folder's lines only, and committed
with its text and churn rows: that is the checkout. The gate then exports a head that adds the second folder's lines: a derived record
and new hunks. The `check` of the gate is the real check's own messages (the functions it calls, on the scratch tree), so that the
other failures of a series built from nothing do not hide what is under test; the last test runs the real `check` on the result.

    python -m pytest -q tools/tests/test_export_gate_todo_after_export.py
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import churn  # noqa: E402
import engine  # noqa: E402
import export_gate  # noqa: E402
import hook_contract  # noqa: E402
from test_export_gate_tests_what_it_writes import TAG, git, make_series, snapshot  # noqa: E402

A, B = "fingerprint/screen-window/screen", "network/proxy-udp"      # the folders of the features screen-metrics and proxy-udp-egress
FILE = "mozilla.txt"
BASE = "".join("int v%d;\n" % n for n in range(1, 31))
RECORD = {"file": FILE, "category": "spoof", "feature": "screen-metrics", "prefs": [], "added": 0, "removed": 0, "hunks": 0, "inline_logic_lines": 0,
          "hookable": "movable", "anchor": "by hand: the anchor", "notes": "by hand: the notes"}


# the test of tools/tests that says again, over the whole series, what C18 says: the gate lets it through with C18's own failures
RESTATING_TEST = '''import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
import hook_contract as hc


def test_every_hook_of_the_series_has_its_churn():
    missing = [v for v in hc.churn_violations(engine.ROOT) if "has no churn" in v.detail]
    assert missing == [], [(v.folder, v.file) for v in missing]
'''
RESTATING_ID = "tools/tests/test_quiet_anchors.py::test_every_hook_of_the_series_has_its_churn"


def text_of(with_b: bool) -> str:
    lines = BASE.splitlines(keepends=True)
    if with_b:
        lines.insert(lines.index("int v20;\n") + 1, "StealthB2();  // STEALTH-HOOK(%s)\n" % B)
    lines[lines.index("int v10;\n")] = "int v10 = StealthA2();  // STEALTH-HOOK(%s)\n" % A
    lines[2:2] = ["StealthA1();  // STEALTH-HOOK(%s)\n" % A] + (["StealthB1();  // STEALTH-HOOK(%s)\n" % B] if with_b else [])
    return "".join(lines)


def rows_of(root: Path, drop=()) -> dict:
    """tools/churn.json as tools/churn.py would write it for the hooks.patch files under `root` (no churn anywhere)."""
    hooks = [{"key": key, "folder": f, "file": p, "hunk": n, "churn": 0, "which": []}
             for (f, p, n), key in sorted(churn.hunk_keys(root).items()) if (f, p, n) not in drop]
    return {"base": TAG, "releases": [], "band": 2, "hooks": hooks}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """(series, source, head): the checkout holds the export of a head with the first folder's lines, hand text and churn rows included; `head`
    adds the second folder's lines."""
    monkeypatch.setattr(export_gate, "run_engine_tree_tests", lambda source, head: [])
    source = tmp_path / "firefox"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "core.autocrlf", "false")
    (source / FILE).write_bytes(BASE.encode())
    git(source, "add", ".")
    git(source, "commit", "-qm", "upstream")
    git(source, "tag", TAG)
    (source / FILE).write_bytes(text_of(False).encode())
    git(source, "commit", "-qam", "first folder")
    first = git(source, "rev-parse", "HEAD")
    (source / FILE).write_bytes(text_of(True).encode())
    git(source, "commit", "-qam", "second folder")
    series = make_series(tmp_path, [A, B])
    (series / A / "MANIFEST.json").write_text(json.dumps({"inventory": [RECORD]}, indent=1) + "\n", encoding="utf-8")   # the first folder's hand work
    (series / "tools" / "tests" / "test_nothing_to_see.py").write_text("def test_it_runs():\n    pass\n", encoding="utf-8")
    (series / "tools" / "tests" / "test_quiet_anchors.py").write_text(RESTATING_TEST, encoding="utf-8")
    engine.export_into(series, source, TAG, first, {})           # the previous export; its hand work is the record above and the rows
    (series / "tools" / "churn.json").write_text(json.dumps(rows_of(series)), encoding="utf-8")
    git(series, "add", "-A")
    git(series, "commit", "-qm", "the series as the last export and its hand work left it")
    return series, source, git(source, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def check_by_its_own_functions(monkeypatch):
    """`engine.py check` of the scratch tree, as far as these two classes go: the failures the real functions of check make, printed as
    check prints them. `extra` lines are other failures of check."""
    real = export_gate._run
    extra = []

    def run(command, cwd):
        if command[1:] != ["tools/engine.py", "check"]:
            return real(command, cwd)
        with engine.rebased(Path(cwd)):
            records = engine.inventory_records()
            found = engine.inventory_hand_problems(records, engine.folder_diffs())
            found += [v.failure for v in hook_contract.churn_violations(engine.ROOT) if v.failure is not None]
        lines = [str(f) for f in found] + extra
        return subprocess.CompletedProcess(command, 1 if lines else 0, stdout="".join(line + "\n" for line in lines) or "ok: stand-in\n", stderr="")

    monkeypatch.setattr(export_gate, "_run", run)
    return extra


def run_gate(world, **kw):
    series, source, head = world
    with engine.rebased(series):
        return export_gate.gate(source, head, lambda scratch: engine.export_into(scratch, source, TAG, head, {}), series, **kw)


def old_gate(monkeypatch):
    """The gate without the tolerance: nothing the export made is let through (what the gate did before)."""
    monkeypatch.setattr(export_gate.News, "of", classmethod(lambda cls, root, tree: cls(set(), set(), set())))


def commit(series, message):
    git(series, "add", "-A")
    git(series, "commit", "-qm", message)


# ------------------------------------------------------------------------------------------------ green in the gate, red in check

def test_the_export_passes_the_gate_with_a_todo_for_each_derived_text_and_each_new_churn_row(world, capsys):
    series, source, head = world
    todo = run_gate(world)
    printed = capsys.readouterr().out
    texts = [t for t in todo if "record in" in t]
    rows = [t for t in todo if "C18: the hook" in t]
    restating = [t for t in todo if t.startswith("TODO after export: %s: " % RESTATING_ID)]
    assert len(texts) == 2 and len(rows) == 2 and len(restating) == 1 and len(todo) == 5, todo
    assert "Fix: python tools/churn.py --source <repo with the tags> --write" in restating[0]
    assert all(t.startswith("TODO after export: %s: " % FILE) for t in texts + rows)
    assert any("record in %s: its `anchor` is empty" % B in t and "Fix: write `anchor` in the record" in t for t in texts), texts
    assert any("its `notes` is empty" in t for t in texts), texts
    assert all("C18: the hook `" in t and "Fix: python tools/churn.py --source <repo with the tags> --write" in t for t in rows), rows
    assert all(line in printed for line in todo) and "5 TODO after export" in printed
    assert (series / B / "hooks.patch").is_file() and "StealthB1" in (series / B / "hooks.patch").read_text(encoding="utf-8"), "the export was taken"


def test_check_is_red_on_exactly_what_the_gate_let_through(world):
    series, source, head = world
    todo = run_gate(world)
    done = subprocess.run([sys.executable, "tools/engine.py", "check"], cwd=series, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode != 0
    out = done.stdout
    assert out.count("its `anchor` is empty") == 1 and out.count("its `notes` is empty") == 1, out
    assert out.count("has no churn row in tools/churn.json") == 2, out
    assert len(todo) == 5


def test_the_gate_before_the_tolerance_refuses_the_same_export(world, monkeypatch):
    """Red on the old gate: nothing of what the export made was let through, so the export that has to be followed by a hand step was refused."""
    series, source, head = world
    before = snapshot(series)
    old_gate(monkeypatch)
    with pytest.raises(SystemExit) as stopped:
        run_gate(world)
    message = str(stopped.value)
    assert "export refused: red on the series it would write" in message and "its `anchor` is empty" in message and "has no churn row" in message
    assert "\nnext: " in message and snapshot(series) == before


# ------------------------------------------------------------------------------------------------ everything else stays red

def test_an_empty_field_of_a_record_the_export_did_not_derive_is_red(world):
    series, source, head = world
    kept = json.loads((series / A / "MANIFEST.json").read_text(encoding="utf-8"))["inventory"]
    kept[0]["anchor"] = ""                         # the record of the first folder, which the checkout had: a hand left it empty
    manifest = json.loads((series / A / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["inventory"] = kept
    (series / A / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    commit(series, "an empty anchor")
    before = snapshot(series)
    with pytest.raises(SystemExit) as stopped:
        run_gate(world)
    message = str(stopped.value)
    assert "FAIL %s/MANIFEST.json, the record of %s in %s: its `anchor` is empty" % (A, FILE, A) in message, message
    assert "the record of %s in %s" % (FILE, B) not in message, "the record the export derived is not what stops it"
    assert snapshot(series) == before


def test_a_missing_churn_row_of_a_hunk_the_export_did_not_touch_is_red(world):
    series, source, head = world
    rows = rows_of(series)
    kept = churn.hunk_keys(series)
    victim = sorted(kept)[0]
    assert victim[0] == A
    rows["hooks"] = [r for r in rows["hooks"] if r["key"] != kept[victim]]      # a hunk of the first folder that never had its row
    (series / "tools" / "churn.json").write_text(json.dumps(rows), encoding="utf-8")
    commit(series, "a hole in churn.json")
    before = snapshot(series)
    with pytest.raises(SystemExit) as stopped:
        run_gate(world)
    message = str(stopped.value)
    assert "FAIL %s/hooks.patch, %s" % (A, FILE) in message and "C18: the hook `" in message and "has no churn row" in message, message
    assert "FAIL %s/hooks.patch" % B not in message, "the rows of the folder the export made are not what stops it"
    assert snapshot(series) == before


def test_another_failure_of_check_stays_red_beside_the_todo_lines(world, check_by_its_own_functions):
    series, source, head = world
    check_by_its_own_functions.append(str(export_gate.fail("SERIES", "it lists a folder that is not there", "write it with export", export_gate.RULE)))
    before = snapshot(series)
    with pytest.raises(SystemExit) as stopped:
        run_gate(world)
    message = str(stopped.value)
    assert "FAIL SERIES: it lists a folder that is not there" in message and "TODO after export" not in message
    assert snapshot(series) == before


def test_a_line_that_is_not_a_failure_the_check_made_is_red_and_a_crash_is_too(world):
    tree = world[0]
    news = export_gate.News({(FILE, B)}, set(), set())
    commandline = [sys.executable, "tools/engine.py", "check"]
    for stdout, stderr in (("FAIL it is red and says nothing a failure says\n", ""), ("", "Traceback (most recent call last):\n")):
        export_gate._run = lambda command, cwd, o=stdout, e=stderr: subprocess.CompletedProcess(command, 1, stdout=o, stderr=e)
        problems, todo = export_gate.run_series_check(tree, news)
        assert problems and not todo, (stdout, stderr)


def test_only_the_two_classes_are_named_and_only_for_what_the_export_made():
    news = export_gate.News({(FILE, B)}, {(B, FILE, 1)}, {(B, "whole.txt")})
    mine = export_gate.fail("%s/MANIFEST.json, the record of %s in %s" % (B, FILE, B), "its `notes` is empty: the text of an inventory record is written by hand",
                            "write `notes` in the record", "repo-07-one-fact-one-place")
    other_record = export_gate.fail("%s/MANIFEST.json, the record of %s in %s" % (A, FILE, A), "its `notes` is empty: x", "write it", "repo-07-one-fact-one-place")
    row = lambda folder, hunk: export_gate.fail(  # noqa: E731
        "%s/hooks.patch, %s, f()" % (folder, FILE), "C18: the hook `X();`%s has no churn row in tools/churn.json" % (", hunk %d," % hunk if hunk else ""),
        "run churn", export_gate.RULE)
    assert export_gate.tolerated(mine, news).startswith("TODO after export: %s: the record in %s: its `notes` is empty" % (FILE, B))
    assert export_gate.tolerated(other_record, news) is None
    assert export_gate.tolerated(row(B, 1), news).endswith("Fix: " + export_gate.CHURN_FIX)
    assert export_gate.tolerated(row(B, 2), news) is None and export_gate.tolerated(row(A, 1), news) is None
    assert export_gate.tolerated(row(B, 0), news) is None, "a whole file is the export's only when no hunk of it was in that folder before"
    whole = export_gate.fail("%s/hooks.patch, whole.txt" % B, "C18: the hook `<delete> x` has no churn row in tools/churn.json", "run churn", export_gate.RULE)
    assert export_gate.tolerated(whole, news) is not None
    with_cause = export_gate.fail("%s/hooks.patch, %s, f()" % (B, FILE),
                                  "C18: the hook `X();`, hunk 1, has no churn row in tools/churn.json (tools/churn.json is missing)", "run churn", export_gate.RULE)
    assert export_gate.tolerated(with_cause, news) is None, "a missing or unreadable churn.json is not a missing row"
    line = str(mine)
    assert export_gate.parse_failure(line) == line and export_gate.parse_failure(line + " x") is None and export_gate.parse_failure("ok: fine") is None


def test_a_hook_found_by_a_c_plus_plus_context_with_a_colon_is_read_whole():
    """The `where` of a hook failure holds the host function or class (`class NrSocket : public NrSocketBase {`), so it has ": " in it: cut at the
    first one, the failure is misread (the real export had eight of them go red)."""
    news = export_gate.News(set(), {(B, "a.h", 2)}, set())
    where = "%s/hooks.patch, a.h, class NrSocket : public NrSocketBase, public nsASocketHandler {" % B
    line = str(export_gate.fail(where, "C18: the hook `X();`, hunk 2, has no churn row in tools/churn.json", "run churn", export_gate.RULE))
    failure = export_gate.parse_failure(line)
    assert failure is not None and failure.where == where and failure.what.startswith("C18: the hook `X();`"), failure
    assert export_gate.tolerated(failure, news).startswith("TODO after export: a.h: C18: the hook `X();`, hunk 2, has no churn row")
    record = "%s/MANIFEST.json, the record of a.h in %s" % (B, B)
    line = str(export_gate.fail(record, "its `notes` is empty: a record: it was derived", "write `notes`", "repo-07-one-fact-one-place"))
    assert export_gate.parse_failure(line).where == record


def test_a_test_beside_the_one_that_restates_churn_is_red_when_it_fails(world):
    series, source, head = world
    (series / "tools" / "tests" / "test_another.py").write_text("def test_red():\n    assert False, 'not about churn'\n", encoding="utf-8")
    before = snapshot(series)
    with pytest.raises(SystemExit) as stopped:
        run_gate(world)
    message = str(stopped.value)
    assert "FAIL tools/tests: " in message and "not about churn" in message and "\nnext: " in message
    assert snapshot(series) == before


def test_the_restating_test_is_red_when_check_made_no_churn_todo(world, monkeypatch):
    """Alone it explains nothing: it is let through only beside the failure of check that it restates."""
    series, source, head = world
    rows = rows_of(series)
    (series / "tools" / "churn.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(export_gate, "RESTATES_CHURN", {RESTATING_ID: ("why", "fix")})
    monkeypatch.setattr(export_gate, "run_series_check", lambda tree, news=None: ([], []))
    with pytest.raises(SystemExit) as stopped:
        run_gate(world)
    assert "FAIL tools/tests: " in str(stopped.value) and "test_every_hook_of_the_series_has_its_churn" in str(stopped.value)


def test_the_tests_the_gate_lets_through_exist():
    for test in export_gate.RESTATES_CHURN:
        path, name = test.split("::")
        assert "def %s(" % name in (TOOLS.parent / path).read_text(encoding="utf-8"), test


def test_the_record_is_told_by_its_field_and_its_key_and_not_by_the_sentence():
    news = export_gate.News({(FILE, B)}, set(), set())
    where = "%s/MANIFEST.json, the record of %s in %s" % (B, FILE, B)
    other = "%s/MANIFEST.json, the record of %s in %s" % (A, FILE, A)
    for sentence in ("the text of an inventory record is written by hand", "some other words", "x"):
        assert export_gate.tolerated(export_gate.fail(where, "its `anchor` is empty: " + sentence, "write it", "repo-07-one-fact-one-place"), news)
        assert export_gate.tolerated(export_gate.fail(other, "its `anchor` is empty: " + sentence, "write it", "repo-07-one-fact-one-place"), news) is None
    assert export_gate.tolerated(export_gate.fail(where, "its `prefs` is empty: whatever", "write it", "repo-07-one-fact-one-place"), news) is None


# ------------------------------------------------------------------------------------------------ a backport hunk with no churn row
def test_a_backport_hunk_the_export_created_with_no_row_is_a_todo_and_one_it_did_not_is_red(tmp_path):
    """C18 sees the hunks of a backport folder too (test_c18_covers_the_hunks_of_a_backport.py): the failure it prints is read by the
    gate as written. The hunk the export created becomes a `TODO after export` line (churn.py --write closes it); the same failure for a
    hunk the checkout already had stays red."""
    from test_c18_covers_the_hunks_of_a_backport import BACKPORT, with_backport
    root = with_backport(tmp_path, rows_for_it=False)
    (violation,) = hook_contract.churn_violations(root)
    failure = export_gate.parse_failure(str(violation.failure))
    assert failure is not None, "check's line for a backport hunk is rebuilt by the gate's reader"
    path = violation.file
    todo = export_gate.tolerated(failure, export_gate.News(set(), {(BACKPORT, path, 1)}, set()))
    assert todo and todo.startswith("TODO after export: %s: C18: the hook `" % path) and "has no churn row in tools/churn.json" in todo, todo
    assert "Fix: %s" % export_gate.CHURN_FIX in todo
    assert export_gate.tolerated(failure, export_gate.News(set(), set(), set())) is None, "a hunk the export did not touch stays red"
