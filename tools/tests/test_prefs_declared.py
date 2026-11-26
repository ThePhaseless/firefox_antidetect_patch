"""tools/prefs-declared.json: the preference changes a release declares against the latest published engine (the prefs job of xpcshell.yml, `xpcshell_run.py prefs-compare --declared`).

  * the committed file is a list of well-formed rows, each with its reason and the pm who decided it (the judge's own validation, xpcshell_run.declared_problems);
  * it is written by hand: no tool of the series writes it, and its path is a series-own one (a hand commit may touch it, the export never does);
  * the prefs job reads exactly this file, from the series checkout of the run.

The cases of the judge itself (undeclared red, declared green, stale red, wrong value red) are scripts/ci/test_xpcshell_run.py's, in the source.

    python -m pytest -q tools/tests/test_prefs_declared.py
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import export_paths  # noqa: E402

DECLARED = ROOT / "tools" / "prefs-declared.json"
CI = ROOT / "platform" / "ci" / "src" / "scripts" / "ci"


def judge():
    spec = importlib.util.spec_from_file_location("xpcshell_run", CI / "xpcshell_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(CI))
    spec.loader.exec_module(module)
    return module


def test_the_declared_file_is_a_list_of_well_formed_rows_with_a_reason_and_a_decider():
    rows = json.loads(DECLARED.read_text(encoding="utf-8"))
    assert judge().declared_problems(rows) == []
    assert all(r["decided_by"].strip() and r["reason"].strip() for r in rows)


def test_the_declared_file_is_written_by_hand_and_no_tool_of_the_series_writes_it():
    assert export_paths.kind("tools/prefs-declared.json") == export_paths.OWN
    writers = [p.name for p in sorted(TOOLS.glob("*.py")) if "prefs-declared" in p.read_text(encoding="utf-8")]
    assert writers == [], "a tool names the file: it is by hand, rows are read by the pm in the pull request"


def test_the_prefs_job_reads_this_file_from_the_series_checkout_of_the_run():
    text = (ROOT / "platform" / "ci" / "src" / ".github" / "workflows" / "xpcshell.yml").read_text(encoding="utf-8")
    assert "--declared engine-series/tools/prefs-declared.json" in text and "/tools/prefs-declared.json" in text
    assert "there is no list of expected differences" not in text


def test_a_row_the_judge_refuses_is_refused_by_the_validation_of_this_file():
    bad = [{"name": "a", "branch": "default", "type": "int", "value": -1, "reason": "", "decided_by": "pm"}]
    assert judge().declared_problems(bad) != []
