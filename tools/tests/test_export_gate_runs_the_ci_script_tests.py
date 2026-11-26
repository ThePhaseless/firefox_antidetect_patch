"""The export gate runs the CI scripts' own tests on the series it writes, when it writes a file of platform/ci or .github.

PR 79 (folders): folders/ci added the job `range-diff` to checks.yml, and the two cases that hold checks.yml's job list by name
(scripts/ci/test_release_checks.py, test_release_builder.py) were not changed. The gate ran tools/tests and the engine tree's tests,
and the CI scripts' tests ran only in the job `tree`, after the push. The gate now runs those two modules on the scratch tree.

  * a job added to checks.yml without its name in the two lists is a refused export, named by the case that holds the list;
  * the same series without the added job passes, and so does an export that writes no CI file (the step does not run);
  * the gate calls the step: the case of the first test, run through `gate()`, is red on a gate without the step.

    python -m pytest -q tools/tests/test_export_gate_runs_the_ci_script_tests.py
"""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_gate  # noqa: E402
from test_export_gate_tests_what_it_writes import no_engine_tree, snapshot, world  # noqa: E402,F401  (fixtures)

REAL = Path(__file__).resolve().parents[2]
CHECKS = ("platform/ci/src/.github/workflows/checks.yml", ".github/workflows/checks.yml")
EXTRA_JOB = """
  an-extra-job:
    name: an-extra-job
    runs-on: ubuntu-24.04
    steps:
      - run: "true"
"""


def real_ci_tree(root: Path) -> Path:
    """What the step reads of a series: platform/ci/src, the workflows of the root, tools, UPSTREAM.json and SERIES: the real ones."""
    for part in ("platform/ci/src", ".github", "tools"):
        shutil.copytree(REAL / part, root / part, ignore=shutil.ignore_patterns("__pycache__", "tests"), dirs_exist_ok=True)
    for part in ("UPSTREAM.json", "SERIES"):
        shutil.copyfile(REAL / part, root / part)
    return root


def add_a_job(root: Path) -> None:
    for rel in CHECKS:
        path = root / rel
        path.write_text(path.read_text(encoding="utf-8").rstrip("\n") + "\n" + EXTRA_JOB, encoding="utf-8", newline="\n")


def test_the_real_series_passes_the_step(tmp_path):
    tree = real_ci_tree(tmp_path / "s")
    assert export_gate.run_ci_script_tests(tree, [CHECKS[0]], []) == []


def test_a_job_added_to_checks_yml_without_its_name_in_the_release_checks_is_refused(tmp_path):
    tree = real_ci_tree(tmp_path / "s")
    add_a_job(tree)
    found = export_gate.run_ci_script_tests(tree, list(CHECKS), [])
    text = "\n".join(str(f) for f in found)
    assert found and "the jobs the two rounds share, by name" in text and "named in test_release_checks.py" in text, text
    assert text.startswith("FAIL scripts/ci") and "Rule: docs/decisions/series-01-export-is-the-only-writer.md" in text


def test_an_export_that_writes_no_ci_file_does_not_run_the_step(tmp_path, capsys):
    tree = real_ci_tree(tmp_path / "s")
    add_a_job(tree)                                  # red if the step ran: it does not, nothing of platform/ci or .github was written
    assert export_gate.run_ci_script_tests(tree, ["automation/input/MANIFEST.json"], []) == []
    assert "not run" in capsys.readouterr().out


def test_the_gate_refuses_the_export_that_adds_a_job_and_leaves_the_checkout_as_it_was(world, monkeypatch):
    series, source, head = world
    real_ci_tree(series)
    monkeypatch.setattr(export_gate, "run_series_check", lambda tree: [])        # the subject is the step, not check or tools/tests
    monkeypatch.setattr(export_gate, "run_series_tests", lambda tree: [])
    before = snapshot(series)

    def write(scratch):
        add_a_job(scratch)

    with pytest.raises(SystemExit) as stopped:
        export_gate.gate(source, head, write, series)
    message = str(stopped.value)
    assert "the jobs the two rounds share, by name" in message and "\nnext: " in message, message
    assert snapshot(series) == before
