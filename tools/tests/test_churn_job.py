"""The job `churn` of checks.yml (port-07, docs/decisions/port-07-quiet-anchors.md): tools/churn.json is what the series and the Mozilla tags give now.

The job is read as YAML, by its keys, and fails when
  (a) it is not a plain job of the checks (an `if`, a `continue-on-error`, a call of another workflow), or it does not wait for the wheelhouse of the tools;
  (b) the nine tags are not fetched and verified before they are read: the cache is restored first, `churn.py --fetch` runs after it (it checks every
      tag against the commit tools/churn.json records, a cached one too), the entry is saved only after a fetch that did not fail, and `--check` and the
      real-series test come after the fetch;
  (c) the cache key is not the commits: it is the output of `churn.py --cache-key`, never a name of a tag or a hash of the workflow;
  (d) the real-series test can be skipped (CHURN_REQUIRE_TAGS) or reads another repository than the one the job fetched into;
  (e) it is a step of `rebuilds` or `tree` (it would wait behind the materialize) or the timing comment is gone;
  (f) the two copies of the workflow differ (platform/ci/src is the source, .github/workflows the export's copy).

    python -m pytest tools/tests/test_churn_job.py
"""
import copy
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "platform" / "ci" / "src" / ".github" / "workflows" / "checks.yml"
COPY = ROOT / ".github" / "workflows" / "checks.yml"
CACHE = "actions/cache/"
REPO = "churn-tags.git"


def _doc(path=COPY):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step(job, needle, key="run"):
    found = [i for i, s in enumerate(job.get("steps") or []) if needle in str(s.get(key, ""))]
    return found[0] if found else None


def problems(doc):
    """What is wrong with the workflow document (a list of sentences); [] when the job is as the decision wants."""
    out = []
    jobs = doc.get("jobs") or {}
    job = jobs.get("churn")
    if job is None:
        return ["checks.yml has no job churn"]
    # (a)
    if "if" in job or job.get("continue-on-error") or "uses" in job:
        out.append("churn: the job can be skipped or passed (if, continue-on-error, uses)")
    if "py-deps-tools" not in ([job["needs"]] if isinstance(job.get("needs"), str) else job.get("needs") or []):
        out.append("churn: the job does not wait for py-deps-tools (pytest comes from its wheelhouse, offline)")
    if any(s.get("continue-on-error") for s in job.get("steps") or []):
        out.append("churn: a step has continue-on-error")
    # (b) restore, then fetch, then save, then the check and the tests
    restore = _step(job, CACHE + "restore", "uses")
    fetch = next((i for i, s in enumerate(job.get("steps") or []) if "--fetch" in str(s.get("run", ""))), None)
    save = _step(job, CACHE + "save", "uses")
    check = next((i for i, s in enumerate(job.get("steps") or []) if re.search(r"churn\.py\b.*--check", str(s.get("run", "")))), None)
    tests = _step(job, "tools/tests/test_churn.py")
    for name, at in (("restore of the cache", restore), ("churn.py --fetch", fetch), ("save of the cache", save),
                     ("churn.py --check", check), ("the real-series test", tests)):
        if at is None:
            out.append("churn: no step for %s" % name)
    if None in (restore, fetch, save, check, tests):
        return out
    if not restore < fetch < save < check < tests:
        out.append("churn: the steps are not in the order restore, fetch, save, check, tests: a tag would be read before it is fetched and "
                   "checked against its commit, or a cache saved from a fetch that failed")
    steps = job["steps"]
    cond = str(steps[save].get("if", ""))
    if "cache-hit" not in cond or "!= 'true'" not in cond:
        out.append("churn: the save runs on a cache hit too, or whatever the restore found (`if: steps.<id>.outputs.cache-hit != 'true'`)")
    if not steps[restore].get("id") or steps[restore]["id"] not in cond:
        out.append("churn: the save's condition does not read the output of the restore step")
    for name, at in (("restore", restore), ("save", save)):
        w = steps[at].get("with") or {}
        if REPO not in str(w.get("path", "")):
            out.append("churn: the %s of the cache is not of the repository %s the job fetches into" % (name, REPO))
    # (c) the key: the commits
    keyed = [i for i, s in enumerate(steps) if "--cache-key" in str(s.get("run", ""))]
    if len(keyed) != 1 or keyed[0] > restore:
        out.append("churn: the key is not made, before the restore, by one step that runs `churn.py --cache-key` (the commits tools/churn.json records)")
    else:
        step_id = steps[keyed[0]].get("id")
        want = "${{ steps.%s.outputs.key }}" % step_id
        for name, at in (("restore", restore), ("save", save)):
            if str((steps[at].get("with") or {}).get("key", "")) != want:
                out.append("churn: the key of the %s is not %s: a cache is keyed on the list of commits, not on tag names or on a file" % (name, want))
    text = yaml.safe_dump(job)
    if re.search(r"FIREFOX_\d|hashFiles", text):
        out.append("churn: the job names a Firefox tag or hashes a file: the key is the commits (churn.py --cache-key)")
    # (d) the real-series test cannot skip, and reads what the job fetched
    env = steps[tests].get("env") or {}
    if str(env.get("CHURN_REQUIRE_TAGS")) != "1":
        out.append("churn: the real-series test can skip (CHURN_REQUIRE_TAGS is not 1): a round without tags would be green")
    if REPO not in str(env.get("CHURN_TAGS_REPO", "")):
        out.append("churn: the real-series test reads CHURN_TAGS_REPO=%r, not the repository the job fetched into" % env.get("CHURN_TAGS_REPO"))
    for name, at in (("fetch", fetch), ("check", check)):
        if REPO not in str(steps[at].get("run", "")):
            out.append("churn: the %s step does not use the repository %s" % (name, REPO))
    # (e) not a step of the jobs that materialize the tree
    for other in ("rebuilds", "tree", "rules"):
        if "churn.py" in "\n".join(str(s.get("run", "")) for s in (jobs.get(other) or {}).get("steps") or []):
            out.append("checks.yml: job %s runs churn.py: it is the job churn's (it needs no tree and would wait behind the materialize)" % other)
    return out


def test_the_job_is_as_the_decision_wants():
    assert problems(_doc()) == []


def test_the_two_copies_of_the_workflow_are_the_same_file():
    assert SOURCE.read_bytes() == COPY.read_bytes(), "platform/ci/src is the source; `engine.py export` copies it to .github/workflows"


def test_the_timing_is_a_comment_of_the_workflow():
    text = SOURCE.read_text(encoding="utf-8")
    comment = "\n".join(l for l in text.splitlines() if l.lstrip().startswith("#"))
    assert "TIMING" in comment and "8 minutes" in comment and "first 3 minutes" in comment
    assert "cold cache" in comment.lower() and "warm cache" in comment.lower()


def test_the_decision_names_the_job_and_the_commands():
    decision = (ROOT / "docs" / "decisions" / "port-07-quiet-anchors.md").read_text(encoding="utf-8")
    for needle in ("checks.yml", "--check", "--fetch", "test_churn_job.py"):
        assert needle in decision, needle


# ------------------------------------------------------------------------------------------------------------------ red on what was
def _change(fn):
    doc = copy.deepcopy(_doc())
    fn(doc["jobs"]["churn"], doc)
    return problems(doc)


def _drop(job, needle):
    job["steps"] = [s for s in job["steps"] if needle not in str(s.get("run", "")) and needle not in str(s.get("uses", ""))]


def test_a_job_that_can_be_skipped_is_red():
    assert any("can be skipped" in p for p in _change(lambda j, d: j.__setitem__("if", "github.event_name == 'pull_request'")))
    assert any("can be skipped" in p for p in _change(lambda j, d: j.__setitem__("continue-on-error", True)))
    assert any("does not wait for py-deps-tools" in p for p in _change(lambda j, d: j.pop("needs")))


def test_a_missing_step_is_red():
    assert any("no step for churn.py --check" in p for p in _change(lambda j, d: _drop(j, "--check")))
    assert any("no step for churn.py --fetch" in p for p in _change(lambda j, d: _drop(j, "--fetch")))
    assert any("no step for the real-series test" in p for p in _change(lambda j, d: _drop(j, "tools/tests/test_churn.py")))
    assert any("no step for save of the cache" in p for p in _change(lambda j, d: _drop(j, CACHE + "save")))
    assert any("no step for restore of the cache" in p for p in _change(lambda j, d: _drop(j, CACHE + "restore")))


def test_a_check_before_the_fetch_is_red():
    def swap(j, d):
        s = j["steps"]
        a = next(i for i, x in enumerate(s) if "--fetch" in str(x.get("run", "")))
        b = next(i for i, x in enumerate(s) if "--check" in str(x.get("run", "")))
        s[a], s[b] = s[b], s[a]
    assert any("not in the order" in p for p in _change(swap))


def test_a_cache_saved_on_a_hit_is_red():
    def always(j, d):
        next(s for s in j["steps"] if CACHE + "save" in str(s.get("uses", ""))).pop("if")
    assert any("runs on a cache hit too" in p for p in _change(always))


def test_a_key_that_is_not_the_commits_is_red():
    def by_tags(j, d):
        for s in j["steps"]:
            if CACHE in str(s.get("uses", "")):
                s["with"]["key"] = "churn-tags-FIREFOX_151_0_RELEASE-FIREFOX_159_0_RELEASE"
    found = _change(by_tags)
    assert any("not ${{ steps.tags.outputs.key }}" in p for p in found) and any("names a Firefox tag" in p for p in found)

    def by_file(j, d):
        for s in j["steps"]:
            if CACHE in str(s.get("uses", "")):
                s["with"]["key"] = "churn-${{ hashFiles('tools/churn.json') }}"
    assert any("hashes a file" in p or "not ${{ steps.tags.outputs.key }}" in p for p in _change(by_file))
    assert any("one step that runs `churn.py --cache-key`" in p for p in _change(lambda j, d: _drop(j, "--cache-key")))


def test_a_real_series_test_that_can_skip_is_red():
    def lax(j, d):
        next(s for s in j["steps"] if "test_churn.py" in str(s.get("run", "")))["env"].pop("CHURN_REQUIRE_TAGS")
    assert any("can skip" in p for p in _change(lax))

    def other_repo(j, d):
        next(s for s in j["steps"] if "test_churn.py" in str(s.get("run", "")))["env"]["CHURN_TAGS_REPO"] = "/elsewhere"
    assert any("not the repository the job fetched into" in p for p in _change(other_repo))


def test_churn_as_a_step_of_rebuilds_is_red():
    def inside(j, d):
        d["jobs"]["rebuilds"]["steps"].append({"run": "python .series/tools/churn.py --check"})
    assert any("job rebuilds runs churn.py" in p for p in _change(inside))


def test_a_workflow_without_the_job_is_red():
    doc = _doc()
    del doc["jobs"]["churn"]
    assert problems(doc) == ["checks.yml has no job churn"]
