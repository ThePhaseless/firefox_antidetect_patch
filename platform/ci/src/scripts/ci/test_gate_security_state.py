"""Every leg of the gate that runs the wrapper's tests launches with the security state that the wrapper's scripts/ci_lab_security_state.py sets (ci/security-state.pin.json).

The state (intermediates, OneCRL, CRLite filters) is the one the core declares and the engine generates in cert_storage (stillborn/security-state). A leg that launched without it
would be tested against a browser whose state is whatever the environment gave it, and the same suite could pass one day and fail the next. The two jobs
that launch the wrapper (`gate`, the legs of the engine, and `wrapper-e2e`, the suites of the matrix) set the variable (STEALTHFOX_SECURITY_STATE, written by
the script into $GITHUB_ENV) in the step that follows the GeoIP step, run by the same shell in the same directory (the wrapper checked out), before their
first step that installs or runs the wrapper's tests; the jobs that only judge do not.

    python -m pytest scripts/ci/test_gate_security_state.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
COMMAND = "python scripts/ci_lab_security_state.py set --pin ci/security-state.pin.json"
GEOIP = "python scripts/ci_lab_geoip.py build --pin ci/geoip.json"
STEP = "      - name: The security state (set by the repository, same bytes every run)\n"
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


def test_the_legs_that_run_the_wrapper_set_the_state_once_before_they_run_it():
    for name, first_use in JOBS:
        job = _job(name)
        assert job.count(COMMAND) == 1, "%s runs the security state script %d times" % (name, job.count(COMMAND))
        assert job.count(STEP) == 1
        assert job.index("Set up Python") < job.index(STEP), "%s sets the state before Python is set up" % name
        assert job.index(STEP) < job.index(first_use), "%s sets the state after the wrapper is installed or run" % name
        # Before the first line of the job that runs a test of the wrapper.
        for marker in ("python -m pytest", "import invisible_playwright"):
            if marker in job:
                assert job.index(STEP) < job.index(marker), "%s sets the state after %r" % (name, marker)


def test_the_state_is_set_right_after_the_geoip_step_by_the_same_shell_in_the_same_directory():
    for name, _ in JOBS:
        job = _job(name)
        geoip, ours = _step(job, GEOIP_STEP), _step(job, STEP)
        assert job.index(GEOIP_STEP) + len(geoip) + 1 == job.index(STEP), "%s has a step between the GeoIP step and the state" % name
        assert "        shell: bash\n" in geoip and "        shell: bash\n" in ours
        assert "working-directory" not in geoip and "working-directory" not in ours
        assert ours.rstrip().endswith("        run: " + COMMAND)
        assert "        run: " + GEOIP in geoip


def test_the_jobs_that_only_judge_do_not_set_it():
    assert STEP not in _job("host-gate") and STEP not in _job("wrapper-e2e-complete")
    assert GATE.count(STEP) == 2 and GATE.count(COMMAND) == 2


def test_the_gate_runs_both_security_state_tests_on_the_binary_and_the_matrix_has_the_suite_on_both_systems():
    job = _job("gate")
    folder = "stillborn/security-state/src/security/manager/ssl/stealth/test"
    assert "sparse-checkout: " + folder + chr(10) in job
    for script in ("run_stealth_security_state_gate.py", "run_stealth_generate_launch_gate.py"):
        assert job.count("engine-series/" + folder + "/" + script + ' "$FF_EXE"') == 1, script
    assert "stillborn/intermediates" not in GATE
    for leg, runner, kind, os_ in (("linux-x86_64", "ubuntu-24.04", "linux", "linux"), ("win-x86_64", "windows-latest", "win", "windows")):
        row = "- { suite: wrapper.e2e.securitystate, leg: %s, runner: %s, kind: %s, os: %s }" % (leg, runner, kind, os_)
        assert GATE.count(row) == 1, row


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
