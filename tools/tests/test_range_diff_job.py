"""The job `range-diff` of checks.yml (series-02, docs/decisions/series-02-every-folder-states-its-relation-to-mozilla.md): on a port, ports/range-diff.txt
is what main's series and this one give; on any other run the job decides that, says so in its log, and is green.

The job is read as YAML, by its keys, and fails when
  (a) it is not a plain job of the checks (an `if`, a `continue-on-error`, a call of another workflow);
  (b) the old series is not main's, fetched before the decision and named `origin/main` in both commands (never the branch's own files);
  (c) the decision is not made first, by `range-diff --decide`, with its two lines going to $GITHUB_OUTPUT (and so to the log) through `tee`;
  (d) the fetch and the check are not ONE step that runs only when the decision says port, from a repository of its own under RUNNER_TEMP, with --check;
  (e) a step that does work runs on a run that is not a port, or the run that is not a port says nothing;
  (f) it is a step of another job, or the timing comment is gone;
  (g) the two copies of the workflow differ (platform/ci/src is the source, .github/workflows the export's copy).
It also runs the decision as the job does, on the series itself.

    python -m pytest tools/tests/test_range_diff_job.py
"""
import copy
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "platform" / "ci" / "src" / ".github" / "workflows" / "checks.yml"
COPY = ROOT / ".github" / "workflows" / "checks.yml"
DECIDE = "tools/engine.py range-diff --decide --old-series origin/main"
CHECK = "tools/engine.py range-diff --source"


def _doc(path=COPY):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _find(job, needle, key="run"):
    return [i for i, s in enumerate(job.get("steps") or []) if needle in str(s.get(key, ""))]


def problems(doc):
    """What is wrong with the workflow document (a list of sentences); [] when the job is as the decision wants."""
    out = []
    jobs = doc.get("jobs") or {}
    job = jobs.get("range-diff")
    if job is None:
        return ["checks.yml has no job range-diff"]
    steps = job.get("steps") or []
    # (a)
    if "if" in job or job.get("continue-on-error") or "uses" in job:
        out.append("range-diff: the job can be skipped or passed (if, continue-on-error, uses)")
    if any(s.get("continue-on-error") for s in steps):
        out.append("range-diff: a step has continue-on-error")
    # (b) main's series, fetched, before the decision
    fetch_main = [i for i in _find(job, "refs/remotes/origin/main")]
    decide = _find(job, "range-diff --decide")
    check = _find(job, CHECK)
    if len(fetch_main) != 1 or "git fetch" not in str(steps[fetch_main[0]].get("run", "")):
        out.append("range-diff: main's series is not fetched by one step (`git fetch ... +refs/heads/main:refs/remotes/origin/main`)")
    # (c) the decision
    if len(decide) != 1:
        out.append("range-diff: the decision is not made by exactly one step that runs `range-diff --decide`")
    if len(check) != 1:
        out.append("range-diff: the check is not exactly one step that runs `range-diff --source`")
    if len(decide) != 1 or len(check) != 1 or len(fetch_main) != 1:
        return out
    d, c, m = steps[decide[0]], steps[check[0]], fetch_main[0]
    if not m < decide[0] < check[0]:
        out.append("range-diff: the steps are not in the order main's series, the decision, the check")
    if not d.get("id"):
        out.append("range-diff: the decision step has no id, so nothing can read its output")
    if "$GITHUB_OUTPUT" not in str(d.get("run", "")) or "tee" not in str(d.get("run", "")):
        out.append("range-diff: the decision does not go to $GITHUB_OUTPUT through tee: its steps cannot read it, or the log does not show it")
    if "--old-series origin/main" not in str(d.get("run", "")) or "--old-series origin/main" not in str(c.get("run", "")):
        out.append("range-diff: a command does not name `--old-series origin/main`: the old series is main's, from git, never the branch's files")
    # (d) the check: one step, only on a port, --fetch and --check, a repository of its own
    run = str(c.get("run", ""))
    for flag in ("--fetch", "--check"):
        if flag not in run:
            out.append("range-diff: the check step lacks %s" % flag)
    if "--write" in run:
        out.append("range-diff: the check step writes the file: it compares it")
    if "RUNNER_TEMP" not in run:
        out.append("range-diff: the repository of the tags is not under RUNNER_TEMP (--fetch would fill the workspace's)")
    want = "steps.%s.outputs.port == 'true'" % d.get("id")
    if str(c.get("if", "")).strip() != want:
        out.append("range-diff: the check step's condition is %r, not %r" % (c.get("if"), want))
    # (e) nothing that works runs on a run that is not a port, and that run says so
    for i, s in enumerate(steps):
        if i > decide[0] and i != check[0] and "range-diff" in str(s.get("run", "")) and "echo" not in str(s.get("run", "")):
            out.append("range-diff: step %d runs range-diff and is not the check" % i)
    quiet = [s for i, s in enumerate(steps) if i > decide[0] and str(s.get("if", "")).strip() == "steps.%s.outputs.port != 'true'" % d.get("id")]
    if len(quiet) != 1 or "echo" not in str(quiet[0].get("run", "")) or "not a port" not in str(quiet[0].get("run", "")).lower():
        out.append("range-diff: the run that is not a port has not one step that says so (`if: steps.<id>.outputs.port != 'true'`, an echo)")
    # (f) not a step of another job
    for other, body in jobs.items():
        if other != "range-diff" and "range-diff" in "\n".join(str(s.get("run", "")) for s in body.get("steps") or []):
            out.append("checks.yml: job %s runs range-diff: it is the job range-diff's" % other)
    return out


def _outputs_run(doc, port):
    """The names of the steps of the job that run when the decision says `port`: the conditions are read as the job writes them."""
    job = doc["jobs"]["range-diff"]
    decide_id = next(s["id"] for s in job["steps"] if "range-diff --decide" in str(s.get("run", "")))
    ran = []
    for s in job["steps"]:
        cond = str(s.get("if", "")).strip()
        if cond == "steps.%s.outputs.port == 'true'" % decide_id:
            ok = port
        elif cond == "steps.%s.outputs.port != 'true'" % decide_id:
            ok = not port
        else:
            assert not cond, "a condition this test does not read: %r" % cond
            ok = True
        if ok:
            ran.append(s.get("name") or s.get("uses"))
    return ran


def test_the_job_is_as_the_decision_wants():
    assert problems(_doc()) == []


def test_the_two_copies_of_the_workflow_are_the_same_file():
    assert SOURCE.read_bytes() == COPY.read_bytes(), "platform/ci/src is the source; `engine.py export` copies it to .github/workflows"


def test_the_timing_is_a_comment_of_the_workflow():
    text = SOURCE.read_text(encoding="utf-8")
    comment = "\n".join(l for l in text.splitlines() if l.lstrip().startswith("#"))
    assert "TIMING (to be measured on the first port PR" in comment and "8 minutes" in comment and "first 3 minutes" in comment


def test_the_decision_names_the_job_and_the_commands():
    decision = (ROOT / "docs" / "decisions" / "series-02-every-folder-states-its-relation-to-mozilla.md").read_text(encoding="utf-8")
    for needle in ("checks.yml", "range-diff --decide", "--check", "--fetch", "test_range_diff_job.py", "ports/range-diff.txt"):
        assert needle in decision, needle


# ------------------------------------------------------------------------------------------------------------------ a run that is not a port
def test_a_pull_request_that_is_not_a_port_runs_the_decision_and_nothing_else_and_is_green():
    ran = _outputs_run(_doc(), port=False)
    assert "Is this a port (mozilla_tag moved away from main's)?" in ran and "Not a port, nothing to compare" in ran
    assert not any("tags" in str(n) for n in ran), "no fetch of Mozilla's repository"
    assert len(ran) == 5, ran


def test_a_port_runs_the_fetch_and_the_check():
    ran = _outputs_run(_doc(), port=True)
    assert any("ports/range-diff.txt is what they give" in str(n) for n in ran) and "Not a port, nothing to compare" not in ran


@pytest.mark.skipif(subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "origin/main"], capture_output=True).returncode != 0,
                    reason="no origin/main here (the job fetches it first)")
def test_the_decision_command_of_the_job_says_port_and_why():
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "engine.py"), "range-diff", "--decide", "--old-series", "origin/main"],
                          capture_output=True, cwd=ROOT, env=dict(os.environ))
    lines = done.stdout.decode().splitlines()
    assert done.returncode == 0 and len(lines) == 2, done.stderr.decode()
    assert re.fullmatch(r"port=(true|false)", lines[0]) and lines[1].startswith("decision=") and ("not a port" in lines[1] or "a port: mozilla_tag moves" in lines[1])


# ------------------------------------------------------------------------------------------------------------------ red on what was
def _change(fn):
    doc = copy.deepcopy(_doc())
    fn(doc["jobs"]["range-diff"], doc)
    return problems(doc)


def _drop(job, needle):
    job["steps"] = [s for s in job["steps"] if needle not in str(s.get("run", "")) and needle not in str(s.get("uses", ""))]


def test_a_job_that_can_be_skipped_is_red():
    assert any("can be skipped" in p for p in _change(lambda j, d: j.__setitem__("if", "github.event_name == 'pull_request'")))
    assert any("can be skipped" in p for p in _change(lambda j, d: j.__setitem__("continue-on-error", True)))
    assert any("a step has continue-on-error" in p for p in _change(lambda j, d: j["steps"][-1].__setitem__("continue-on-error", True)))


def test_a_missing_step_is_red():
    assert any("exactly one step that runs `range-diff --decide`" in p for p in _change(lambda j, d: _drop(j, "range-diff --decide")))
    assert any("exactly one step that runs `range-diff --source`" in p for p in _change(lambda j, d: _drop(j, "range-diff --source")))
    assert any("main's series is not fetched" in p for p in _change(lambda j, d: _drop(j, "refs/remotes/origin/main")))


def test_a_check_that_runs_on_every_pull_request_is_red():
    def always(j, d):
        next(s for s in j["steps"] if "range-diff --source" in str(s.get("run", ""))).pop("if")
    assert any("the check step's condition is None" in p for p in _change(always))

    def inverted(j, d):
        next(s for s in j["steps"] if "range-diff --source" in str(s.get("run", "")))["if"] = "steps.decide.outputs.port != 'true'"
    assert any("the check step's condition" in p for p in _change(inverted))


def test_a_run_that_is_not_a_port_and_says_nothing_is_red():
    assert any("has not one step that says so" in p for p in _change(lambda j, d: _drop(j, "not a port, this run")))


def test_the_old_series_from_the_branch_is_red():
    def branch(j, d):
        for s in j["steps"]:
            s["run"] = str(s.get("run", "")).replace("--old-series origin/main", "--old-series HEAD")
    assert any("the old series is main's, from git" in p for p in _change(branch))


def test_a_decision_that_is_not_in_the_log_or_not_readable_is_red():
    def silent(j, d):
        next(s for s in j["steps"] if "range-diff --decide" in str(s.get("run", "")))["run"] = "python tools/engine.py range-diff --decide --old-series origin/main"
    assert any("through tee" in p for p in _change(silent))

    def anonymous(j, d):
        next(s for s in j["steps"] if "range-diff --decide" in str(s.get("run", ""))).pop("id")
    assert any("has no id" in p for p in _change(anonymous))


def test_a_check_that_writes_or_fills_the_workspace_is_red():
    def writes(j, d):
        next(s for s in j["steps"] if "range-diff --source" in str(s.get("run", "")))["run"] += " --write"
    assert any("writes the file" in p for p in _change(writes))

    def workspace(j, d):
        s = next(s for s in j["steps"] if "range-diff --source" in str(s.get("run", "")))
        s["run"] = s["run"].replace("$RUNNER_TEMP", "$GITHUB_WORKSPACE")
    assert any("not under RUNNER_TEMP" in p for p in _change(workspace))


def test_the_check_before_the_decision_is_red():
    def swap(j, d):
        s = j["steps"]
        a = next(i for i, x in enumerate(s) if "range-diff --decide" in str(x.get("run", "")))
        b = next(i for i, x in enumerate(s) if "range-diff --source" in str(x.get("run", "")))
        s[a], s[b] = s[b], s[a]
    assert any("not in the order" in p for p in _change(swap))


def test_range_diff_as_a_step_of_another_job_is_red():
    def inside(j, d):
        d["jobs"]["rules"]["steps"].append({"run": "python tools/engine.py range-diff --source x"})
    assert any("job rules runs range-diff" in p for p in _change(inside))


def test_a_workflow_without_the_job_is_red():
    doc = _doc()
    del doc["jobs"]["range-diff"]
    assert problems(doc) == ["checks.yml has no job range-diff"]
