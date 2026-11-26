"""Every leg of the gate that runs the wrapper's tests launches with the security state that the wrapper's scripts/ci_lab_security_state.py sets (ci/security-state.pin.json).

The state (intermediates, OneCRL, CRLite filters) is the one the core declares and the engine generates in cert_storage (stillborn/security-state). A leg that launched without it
would be tested against a browser whose state is whatever the environment gave it, and the same suite could pass one day and fail the next. The two jobs
that launch the wrapper (`gate`, the legs of the engine, and `wrapper-e2e`, the suites of the matrix) set the variable (STEALTHFOX_SECURITY_STATE, written by
the script into $GITHUB_ENV) in the step that follows the GeoIP step, run by the same shell in the same directory (the wrapper checked out), before their
first step that installs or runs the wrapper's tests; the jobs that only judge do not.

    python -m pytest scripts/ci/test_gate_security_state.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
COMMAND = "python scripts/ci_lab_security_state.py set --pin ci/security-state.pin.json"
GEOIP = "python scripts/ci_lab_geoip.py build --pin ci/geoip.json"
STEP = "      - name: The security state (set by the repository, same bytes every run)\n"
GEOIP_STEP = "      - name: The GeoIP database (made by the repository, same bytes every run)\n"
JOBS = (("gate", "      - name: The wheelhouse of the run's py-deps-gate job"), ("wrapper-e2e", "      - name: Linux system deps"))


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


GATE_SCRIPT = ROOT / "security" / "manager" / "ssl" / "stealth" / "test" / "run_stealth_security_state_gate.py"
JUNIT_STEP = "      - name: THE DECLARED SECURITY STATE - the engine generates it from the files, makes no request for the collections\n"
KEEP_JUNIT_STEP = "      - name: THE DECLARED SECURITY STATE - keep the junit (the part of this leg)\n"
HOST_COMPARE = "        run: python scripts/ci_host_gate.py compare host-dump --junit gate-junit/host-gate.xml\n"
SCRIPT_RUN = (
    'engine-series/stillborn/security-state/src/security/manager/ssl/stealth/test/run_stealth_security_state_gate.py "$FF_EXE" '
    "--junit junit-py/security-state-${{ matrix.leg }}/run_stealth_security_state_gate.xml\n"
)


def test_the_security_state_step_writes_a_junit_per_leg_and_the_part_is_kept_whatever_the_step_said():
    job = _job("gate")
    step = _step(job, JUNIT_STEP)
    assert step.count(SCRIPT_RUN) == 1
    keep = _step(job, KEEP_JUNIT_STEP)
    assert job.index(JUNIT_STEP) + len(step) + 1 == job.index(KEEP_JUNIT_STEP), "the upload is not the step right after the gate script"
    for line in ("        if: always()\n", "          name: junitpart-py-security-state-${{ matrix.leg }}\n", "          path: junit-py\n"):
        assert line in keep, line
    # a part (junitpart-*), never junit-*: the artifact name junit-py is one per run, put together by the job that follows the legs
    assert "name: junit-py\n" not in keep


def test_the_host_gate_writes_the_junit_of_its_comparison_and_keeps_it_as_a_result_artifact_without_json():
    job = _job("host-gate")
    assert job.count(HOST_COMPARE) == 1
    keep = _step(job, "      - name: HOST GATE - keep the junit\n")
    assert job.index(HOST_COMPARE) < job.index("HOST GATE - keep the junit")
    for line in ("        if: always()\n", "          name: result-host-gate\n", "          path: gate-junit\n"):
        assert line in keep, line
    assert "result/" not in keep and ".json" not in keep


def _load_gate_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_stealth_security_state_gate_under_test", str(GATE_SCRIPT))
    module = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return module


def _run_script(args, failing=(), unrun=()):
    """main() of the script with no engine: every case passes, except the composite ones in `failing` (a problem) and the cases in `unrun` (no answer).
    -> (exit status, {testcase name: (classname, outcome, message)}), the junit read back."""
    import tempfile
    import xml.etree.ElementTree as ET

    module = _load_gate_script()
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "fixture.json"
        fixture.write_text("{}", encoding="utf-8")
        junit = Path(tmp) / "out" / "gate.xml"

        def run_case(firefox, case, *_a, **_k):
            if case in unrun:
                return None, "no answer", "log"
            return {"ok": True, "detail": "d"}, None, ""

        def composite(name):
            def run(*_a, **_k):
                verdict = module.Verdict(name)
                if name in failing:
                    verdict.problems.append("%s went wrong" % name)
                else:
                    verdict.notes.append("fine")
                return verdict

            return run

        module.make_fixture = lambda *_a, **_k: str(fixture)
        module.crlite_data_dir = lambda *_a, **_k: None
        module.run_case = run_case
        module.case_generate = composite("generate")
        for name in list(module.COMPOSITE):
            module.COMPOSITE[name] = composite(name)
        status = module.main(["firefox"] + args + ["--junit", str(junit)])
        found = {}
        for tc in ET.parse(str(junit)).getroot().iter("testcase"):
            outcome, message = "passed", ""
            for tag, name in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
                node = tc.find(tag)
                if node is not None:
                    outcome, message = name, node.get("message", "")
            found[tc.get("name")] = (tc.get("classname"), outcome, message)
        return status, found


def test_the_junit_has_a_testcase_per_case_named_as_the_hooks_spell_them_and_the_classname_is_the_script_path():
    module = _load_gate_script()
    status, found = _run_script([])
    assert status == 0
    assert set(found) == {"case:" + c for c in module.ALL_CASES}
    assert {"case:poller", "case:never_asked"} <= set(found)
    assert {v[1] for v in found.values()} == {"passed"}
    assert {v[0].replace(".", "/") + ".py" for v in found.values()} == {"security/manager/ssl/stealth/test/run_stealth_security_state_gate.py"}


def test_a_case_that_failed_is_a_failure_one_that_did_not_run_an_error_and_the_exit_status_is_the_gate_s_own():
    status, found = _run_script([], failing=("poller",))
    assert status == 1 and found["case:poller"][1] == "failed" and "poller went wrong" in found["case:poller"][2]
    assert found["case:never_asked"][1] == "passed"
    status, found = _run_script([], unrun=("never_asked",))
    assert status == 2 and found["case:never_asked"][1] == "error" and "no answer" in found["case:never_asked"][2]
    assert found["case:poller"][1] == "passed"


def test_a_case_the_run_did_not_select_is_skipped_never_a_pass():
    status, found = _run_script(["--cases", "poller"])
    assert status == 0
    assert found["case:poller"][1] == "passed"
    assert {n for n, v in found.items() if v[1] == "skipped"} == set(found) - {"case:poller"}
    assert found["case:never_asked"][1] == "skipped"


def test_a_run_that_stops_before_a_selected_case_leaves_it_an_error_not_a_pass():
    import tempfile
    import xml.etree.ElementTree as ET

    module = _load_gate_script()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "gate.xml"
        module.write_junit(str(out), {"generate": ("passed", "ok")}, ["generate", "poller"])
        rows = {tc.get("name"): [k.tag for k in tc] for tc in ET.parse(str(out)).getroot().iter("testcase")}
    assert rows["case:generate"] == [] and rows["case:poller"] == ["error"] and rows["case:never_asked"] == ["skipped"]


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
