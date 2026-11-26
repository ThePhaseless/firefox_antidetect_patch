"""The rules job of checks.yml (the one workflow both rounds call) installs every module the repository's tools and tests
import that Python does not ship.

On 2026-11-05 test_node_jobs_find_their_scripts.py started reading the workflows with
yaml, and the job still installed pytest alone: `rules` went red on every push to main
with "No module named 'yaml'", which reads as a broken rule, not a missing package.

    python -m pytest tools/tests

A module nothing imports can still be required: a pytest plugin that a command line asks for. The gate runs `pytest -n auto tools/tests` (pytest-xdist) and the
candidate 45735957970 went red on `rules` because the lock, which had pytest alone, had no xdist (it was installed on the PC that exported): the second test reads
the pytest command lines of tools/ for the flags that need a plugin.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES_YML = ROOT / ".github" / "workflows" / "checks.yml"
# The import name and the name pip installs it by, where they differ.
PIP_NAME = {"yaml": "pyyaml"}
# The flag of a pytest command line and the plugin that reads it (the flag alone is an error without it: "unrecognized arguments").
PYTEST_FLAG_PLUGIN = {"-n": "pytest-xdist", "--numprocesses": "pytest-xdist", "--dist": "pytest-xdist"}


def ours():
    """Everything the repository itself can import: its modules and its packages."""
    paths = [p for p in ROOT.rglob("*") if ".git" not in p.relative_to(ROOT).parts]
    return {p.stem for p in paths if p.suffix == ".py"} | {p.name for p in paths if p.is_dir()}


def imported_from_outside():
    names = set()
    for source in (ROOT / "tools").rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    local = ours()
    return {n for n in names if n not in sys.stdlib_module_names and n not in local}


def rules_job_installs():
    """What the rules job installs, read as text (this test must say what is missing even where yaml itself is the thing missing): it installs
    offline from a py-deps wheelhouse (ci-03), so the names are those of the lock its py-deps call resolves: the `lock:` of the call the job
    needs, read from the series' copy (platform/ci/src/<lock>), one `name==version` per entry."""
    text = SERIES_YML.read_text(encoding="utf-8")
    job = re.search(r"^  rules:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert job, "checks.yml has no rules job"
    needs = re.search(r"needs:\s*\[?([\w, -]+)\]?", job.group(1))
    assert needs, "the rules job of checks.yml needs no py-deps call: it would install from the index (ci-03)"
    installed = set()
    for need in [n.strip() for n in needs.group(1).split(",") if n.strip()]:
        call = re.search(r"^  %s:\n(.*?)(?=^  \S|\Z)" % re.escape(need), text, re.M | re.S)
        lock = call and re.search(r"lock:\s*([\w./-]+)", call.group(1))
        if lock:
            for line in (ROOT / "platform/ci/src" / lock.group(1)).read_text(encoding="utf-8").splitlines():
                entry = re.match(r"^([A-Za-z0-9_.-]+)==", line)
                if entry:
                    installed.add(entry.group(1).lower().replace("_", "-"))
    assert "--no-index" in job.group(1), "the rules job of checks.yml installs from the index, not from its wheelhouse (ci-03)"
    return installed


def test_the_rules_job_installs_every_module_the_tools_import():
    missing = sorted(n for n in imported_from_outside() if PIP_NAME.get(n, n).lower() not in rules_job_installs())
    assert not missing, ("the rules job of checks.yml does not install %s, which tools/ imports: "
                         "add it to the lock the rules job installs (scripts/ci/locks/<name>.in, then py_deps.py lock)" % ", ".join(PIP_NAME.get(n, n) for n in missing))


def pytest_plugins_required():
    """{plugin: where} for every pytest command line a file of tools/ builds: a list literal with "pytest" among its strings and a flag that a plugin reads."""
    found = {}
    for source in (ROOT / "tools").rglob("*.py"):
        if "tests" in source.relative_to(ROOT / "tools").parts:
            continue
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.List, ast.Tuple)):
                words = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if "pytest" in words:
                    for flag, plugin in PYTEST_FLAG_PLUGIN.items():
                        if flag in words:
                            found.setdefault(plugin, "%s (%s)" % (source.relative_to(ROOT).as_posix(), flag))
    return found


def test_the_pytest_plugins_the_tools_command_lines_need_are_in_the_lock():
    required = pytest_plugins_required()
    assert "pytest-xdist" in required, "the gate no longer runs pytest with -n: this test reads that line (tools/export_gate.py); update PYTEST_FLAG_PLUGIN if it changed"
    missing = sorted((p, w) for p, w in required.items() if p not in rules_job_installs())
    assert not missing, ("the rules job of checks.yml does not install %s, which a pytest command line of tools/ needs: add it to scripts/ci/locks/tools.in, then "
                         "py_deps.py lock tools" % ", ".join("%s (%s)" % m for m in missing))
