"""Every leg of the gate that runs the wrapper's tests launches with the list of intermediate certificates that the wrapper's scripts/ci_lab_intermediates.py sets (ci/intermediates.pin.json).

The list is the one the core declares and the engine writes to cert_storage before any window (stillborn/intermediates). A leg that launched without it
would be tested against a browser whose list is whatever the environment gave it, and the same suite could pass one day and fail the next. The two jobs
that launch the wrapper (`gate`, the legs of the engine, and `wrapper-e2e`, the suites of the list) set the variable (STEALTHFOX_INTERMEDIATES, written by
the script into $GITHUB_ENV) in the step that follows the GeoIP step, run by the same shell in the same directory (the wrapper checked out), before their
first step that installs or runs the wrapper's tests; the jobs that only judge do not.

    python -m pytest scripts/ci/test_gate_intermediates.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
COMMAND = "python scripts/ci_lab_intermediates.py set --pin ci/intermediates.pin.json"
GEOIP = "python scripts/ci_lab_geoip.py build --pin ci/geoip.json"
STEP = "      - name: The intermediates list (set by the repository, same bytes every run)\n"
GEOIP_STEP = "      - name: The GeoIP database (made by the repository, same bytes every run)\n"
JOBS = (("gate", "      - name: Install Playwright driver"), ("wrapper-e2e", "      - name: Linux system deps"))


def _job(name):
    start = GATE.index("\n  %s:\n" % name)
    ends = [GATE.find("\n  %s:\n" % other, start + 1) for other in ("wrapper-e2e", "wrapper-e2e-complete", "host-gate")]
    ends = [e for e in ends if e > start]
    return GATE[start:min(ends)] if ends else GATE[start:]


def _step(job, header):
    """The text of one step: from its header to the next step."""
    start = job.index(header)
    end = job.find("\n      - name: ", start + 1)
    return job[start:end if end > 0 else len(job)]


def test_the_legs_that_run_the_wrapper_set_the_list_once_before_they_run_it():
    for name, first_use in JOBS:
        job = _job(name)
        assert job.count(COMMAND) == 1, "%s runs the intermediates script %d times" % (name, job.count(COMMAND))
        assert job.count(STEP) == 1
        assert job.index("Set up Python") < job.index(STEP), "%s sets the list before Python is set up" % name
        assert job.index(STEP) < job.index(first_use), "%s sets the list after the wrapper is installed or run" % name
        # Before the first line of the job that runs a test of the wrapper.
        for marker in ("python -m pytest", "import invisible_playwright"):
            if marker in job:
                assert job.index(STEP) < job.index(marker), "%s sets the list after %r" % (name, marker)


def test_the_list_is_set_right_after_the_geoip_step_by_the_same_shell_in_the_same_directory():
    for name, _ in JOBS:
        job = _job(name)
        geoip, ours = _step(job, GEOIP_STEP), _step(job, STEP)
        assert job.index(GEOIP_STEP) + len(geoip) + 1 == job.index(STEP), "%s has a step between the GeoIP step and the list" % name
        assert "        shell: bash\n" in geoip and "        shell: bash\n" in ours
        assert "working-directory" not in geoip and "working-directory" not in ours
        assert ours.rstrip().endswith("        run: " + COMMAND)
        assert "        run: " + GEOIP in geoip


def test_the_jobs_that_only_judge_do_not_set_it():
    assert STEP not in _job("host-gate") and STEP not in _job("wrapper-e2e-complete")
    assert GATE.count(STEP) == 2 and GATE.count(COMMAND) == 2


def cases() -> list:
    """The tests above as (name, ok) pairs, for scripts/ci/test_ci.py, which the plan job runs (a test that no job runs is deleted)."""
    found = []
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                ok = True
            except (AssertionError, ValueError):
                ok = False
            found.append(("gate: " + name[len("test_"):].replace("_", " "), ok))
    return found


if __name__ == "__main__":
    import sys

    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
