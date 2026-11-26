"""repo-04 (docs/decisions/repo-04-every-failure-says-where-what-fix-rule.md): every producer of a problem returns a `Failure`, and
`engine.py check` prints each one as it is: no line starts with `FAIL FAIL`, and none gets a prefix the failure already has.

The fixture breaks the series in five places at once, one per producer that returns a list of problems (the budget of the series,
the FOLDER.json of a folder, the birth ledger, the hook-debt list, the backport record), runs the real `check` and reads what it prints.

    python -m pytest tools/tests/test_no_double_fail.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backport_replay  # noqa: E402
import births  # noqa: E402
import engine  # noqa: E402
import folders  # noqa: E402
import hook_contract  # noqa: E402
from failure import Failure  # noqa: E402
from test_folders import series  # noqa: E402


def _violation():
    return hook_contract.Violation("C4", "f/x", "a.cpp", "void F() {", "// three",
                                   hook_contract._key("C4", "f/x", "a.cpp", "void F() {", "// three"))


def _every_producer(tmp_path, monkeypatch):
    """-> {producer: its list of problems}, with the series of this checkout broken in each one."""
    budget = json.loads(engine.BUDGET.read_text(encoding="utf-8"))
    budget[next(k for k in sorted(budget) if k.split("|")[0] == "browser/components/moz.build")] -= 1
    path = tmp_path / "hook-budget.json"
    path.write_text(json.dumps(budget), encoding="utf-8")
    monkeypatch.setattr(engine, "BUDGET", path)
    ledger = json.loads(births.LEDGER.read_text(encoding="utf-8"))
    ledger["tag"] = "FIREFOX_1_0_RELEASE"
    return {
        "engine.problems": engine.problems(),
        "folders.problems": folders.problems(series(tmp_path, {"fingerprint/a": '{"relation": "x"}', "fingerprint/b": "not json"})),
        "births.ledger_problems": births.ledger_problems(ledger),
        "hook_contract.debt_problems": hook_contract.debt_problems([_violation()], [], None),
        "backport_replay.record_problems": backport_replay.record_problems(tmp_path, {"commits": "none"}),
    }


def test_every_producer_returns_failures(tmp_path, monkeypatch):
    for producer, found in _every_producer(tmp_path, monkeypatch).items():
        assert found, "%s found nothing in the fixture that breaks it" % producer
        bad = [p for p in found if not isinstance(p, Failure)]
        assert not bad, "%s returns something that is not a Failure: %r" % (producer, bad[0])


def test_check_prints_each_failure_as_it_is(tmp_path, monkeypatch, capsys):
    _every_producer(tmp_path, monkeypatch)       # the budget is broken, the file is the one `check` reads
    broken = folders.problems(series(tmp_path, {"fingerprint/a": "not json"}))
    monkeypatch.setattr(engine.folders, "problems", lambda root: broken)
    monkeypatch.setattr(hook_contract, "contract_violations", lambda root: [_violation()])      # one that is not in the debt
    assert engine.check() == 1
    lines = [l for l in capsys.readouterr().out.splitlines() if "FAIL" in l]
    assert lines, "check printed no FAIL line"
    assert not [l for l in lines if l.startswith("FAIL FAIL")], lines
    assert all(l.startswith("FAIL ") for l in lines if l.split(":")[0].startswith("FAIL")), lines
    # one line per problem, printed whole: the budget one and the folder one are both there
    assert any("moz.build" in l and "budget" in l for l in lines)
    assert any("FOLDER.json" in l and "not JSON" in l for l in lines)
