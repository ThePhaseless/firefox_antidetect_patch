r"""The wrapper's list of required suites and the matrix of gate.yml agree before the node is turned on, and the fake web's suite has its legs and its control.

Run 44834434976 was red only on `wrapper-e2e-complete`: the list had `wrapper.e2e.fakeweb` on Linux and Windows and the hand-written matrix of `wrapper-e2e` had
no leg for it, which the run learned 40 minutes in, after the engine build. `scripts/ci/gate_legs.py` reads the two files and says it in the `checks` job of
release.yml; these cases hold that script to its known-bad inputs, and hold the real gate.yml to the legs and the control that the suite needs.

    python3 scripts/ci/test_gate_legs.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_legs  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
FAKEWEB = "wrapper.e2e.fakeweb"
SUITE_STEP = "The suite - every listed test runs and passes"
VERDICT_STEP = "Verdict - required suite"
KEEP_STEP = "Keep the result"


def _gate(*pairs) -> dict:
    return {"jobs": {"wrapper-e2e": {"strategy": {"matrix": {"include": [{"suite": s, "os": o} for s, o in pairs]}}}}}


def _row(suite_id, os_list=("linux", "windows")) -> dict:
    return {"id": suite_id, "os": list(os_list), "min_tests": 1, "tests": ["tests/x.py"]}


def _cli(required: Path, gate: Path):
    return subprocess.run([sys.executable, str(Path(gate_legs.__file__)), "--required", str(required), "--gate", str(gate)], capture_output=True, text=True)


def cases() -> list:
    import yaml

    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    # the known bad: the run that taught this
    want = FAKEWEB + "/linux has no leg in gate.yml's wrapper-e2e matrix"
    lines = gate_legs.missing([_row("a"), _row(FAKEWEB)], _gate(("a", "linux"), ("a", "windows"), (FAKEWEB, "windows")))
    add("gate legs: a suite whose Linux leg is missing is reported (run 44834434976)%s" % ("" if lines == [want] else ": %s" % lines), lines == [want])
    lines = gate_legs.missing([_row("a"), _row(FAKEWEB)], _gate(("a", "linux"), ("a", "windows"), (FAKEWEB, "linux")))
    add("gate legs: a suite whose Windows leg is missing is reported%s" % ("" if len(lines) == 1 else ": %s" % lines),
        len(lines) == 1 and lines[0].startswith(FAKEWEB + "/windows "))
    lines = gate_legs.missing([_row("a"), _row(FAKEWEB)], _gate(("a", "linux"), ("a", "windows")))
    add("gate legs: a suite with no leg at all is reported once per system", len(lines) == 2)
    add("gate legs: every leg present is no problem",
        gate_legs.missing([_row("a"), _row("b", ["linux"])], _gate(("a", "linux"), ("a", "windows"), ("b", "linux"))) == [])
    add("gate legs: a Linux-only row needs no Windows leg", gate_legs.missing([_row("b", ["linux"])], _gate(("b", "linux"))) == [])
    stray = _gate(("a", "linux"), ("a", "windows"), ("stray", "linux"))
    lines = gate_legs.unlisted([_row("a")], stray)
    add("gate legs: a leg whose suite is not in the list is said%s" % ("" if len(lines) == 1 else ": %s" % lines), len(lines) == 1 and "stray" in lines[0])
    add("gate legs: a leg whose suite is not in the list does not fail the check (the series reaches main before the wrapper lists the suite)",
        gate_legs.missing([_row("a")], stray) == [])
    add("gate legs: a gate with no wrapper-e2e job reports every leg of the list", len(gate_legs.missing([_row("a")], {"jobs": {}})) == 2)

    # the real gate.yml: the legs
    gate = yaml.safe_load((WORKFLOWS / "gate.yml").read_text(encoding="utf-8"))
    have = {(r.get("suite"), r.get("os")) for r in gate_legs.legs(gate)}
    add("gate legs: the real gate.yml has a %s leg on Linux" % FAKEWEB, (FAKEWEB, "linux") in have)
    add("gate legs: the real gate.yml has a %s leg on Windows" % FAKEWEB, (FAKEWEB, "windows") in have)

    # the real gate.yml: the control of the fake web
    steps = gate["jobs"]["wrapper-e2e"]["steps"]
    names = [s.get("name", "") for s in steps]
    ctl = [i for i, s in enumerate(steps) if "run_fakeweb.py" in (s.get("run") or "")]
    run = [steps[i]["run"] for i in ctl]
    add("gate legs: the fake web's control has three steps (P2, P4 journey, P4 trace)%s" % ("" if len(ctl) == 3 else ": %d" % len(ctl)), len(ctl) == 3)
    add("gate legs: every control step runs on the candidate's binary and only for the fake web's suite, even after a red suite",
        bool(ctl) and all('--binary "$FF_EXE"' in steps[i]["run"] and "matrix.suite == 'wrapper.e2e.fakeweb'" in steps[i].get("if", "")
                          and "always()" in steps[i].get("if", "") for i in ctl))
    add("gate legs: the control runs P2, the P4 journey and a traced P4 walk",
        any("--profile p2" in r for r in run) and sum("--profile p4" in r for r in run) == 2 and any("--trace" in r for r in run))
    add("gate legs: the control judges the journey and the trace with the wrapper's report",
        any("fakeweb_p4_report.py journey" in r for r in run) and any("fakeweb_p4_report.py trace" in r for r in run))
    verdict = names.index(VERDICT_STEP) if VERDICT_STEP in names else -1
    keep = names.index(KEEP_STEP) if KEEP_STEP in names else -1
    add("gate legs: the control runs after the verdict and before the result is kept", verdict >= 0 and keep >= 0 and bool(ctl) and all(verdict < i < keep for i in ctl))
    # The fake web's reports go to fakeweb/ and an artifact of their own: result/ is what the completeness judge reads, and it takes every JSON
    # file there for a verdict (candidate 44865995733 was red on the three reports alone).
    add("gate legs: the control writes under fakeweb/, never under result/",
        bool(run) and all("fakeweb/fakeweb-" in r and "result/fakeweb" not in r for r in run))
    kept = [s for s in steps if (s.get("with") or {}).get("path") == "fakeweb"]
    add("gate legs: what the fake web wrote is kept in an artifact of its own, only for the fake web's suite",
        len(kept) == 1 and "matrix.suite == 'wrapper.e2e.fakeweb'" in kept[0].get("if", "") and "always()" in kept[0].get("if", "")
        and not str(kept[0]["with"].get("name", "")).startswith("result-"))
    add("gate legs: the control steps set the environment of the suite step",
        bool(run) and all("INVISIBLE_CORE_AUTOFIX=off INVISIBLE_CORE_PIN=allow" in r and 'INVISIBLE_SEAL_FILE="$PWD/gate.seal.json"' in r
                          and 'INVPW_BINARY_PATH="$FF_EXE"' in r and 'STEALTHFOX_E2E_BINARY="$FF_EXE"' in r for r in run))
    browser = [i for i, s in enumerate(steps) if "playwright install firefox" in (s.get("run") or "")]
    suite = names.index(SUITE_STEP) if SUITE_STEP in names else -1
    add("gate legs: Playwright's own Firefox is installed for the fake web only, before the suite",
        len(browser) == 1 and "matrix.suite == 'wrapper.e2e.fakeweb'" in steps[browser[0]].get("if", "") and 0 <= browser[0] < suite)

    # the A/B oracles (published engine against the candidate: page, network, host): their legs, their longer budget, and their files kept
    ORACLES = ("wrapper.e2e.ab_oracle", "wrapper.e2e.ab_network", "wrapper.e2e.ab_host")
    for ORACLE in ORACLES:
        add("gate legs: the real gate.yml has a %s leg on Linux and on Windows" % ORACLE, {(ORACLE, "linux"), (ORACLE, "windows")} <= have)
    oracle_rows = [r for r in gate_legs.legs(gate) if r.get("suite") in ORACLES]
    add("gate legs: the oracles' legs have more than the default 25 minutes, and the job reads its budget from the leg",
        len(oracle_rows) == 2 * len(ORACLES) and all(int(r.get("timeout", 0)) > 25 for r in oracle_rows)
        and str(gate["jobs"]["wrapper-e2e"].get("timeout-minutes", "")).replace(" ", "") == "${{matrix.timeout||25}}")
    suite_run = steps[suite]["run"] if suite >= 0 else ""
    add("gate legs: the suite step gives the oracles' tests a folder of their own outside result/ (the completeness judge reads every JSON in result/)",
        'export AB_ORACLE_OUT="$PWD/ab-oracle"' in suite_run and "mkdir -p ab-oracle" in suite_run and "result/ab-oracle" not in suite_run)
    oracle_kept = [s for s in steps if (s.get("with") or {}).get("path") == "ab-oracle"]
    add("gate legs: the oracles' dumps and diffs are kept in an artifact of their own per suite and system, after a red suite too, for the oracles' suites only",
        len(oracle_kept) == 1 and all("matrix.suite == '%s'" % o in oracle_kept[0].get("if", "") for o in ORACLES) and "always()" in oracle_kept[0].get("if", "")
        and str(oracle_kept[0]["with"].get("name")).endswith("-${{ matrix.os }}") and "result-" not in str(oracle_kept[0]["with"]["name"]))
    add("gate legs: the oracles' artifact is kept before the result",
        len(oracle_kept) == 1 and keep >= 0 and steps.index(oracle_kept[0]) < keep and steps.index(oracle_kept[0]) > verdict >= 0)

    # a leg first, its row second: a suite the wrapper's list does not have yet is said, not failed, and nothing else is skipped
    listed = [i for i, s in enumerate(steps) if "LISTED=1" in str(s.get("run", ""))]
    guard = '[ "$LISTED" = 1 ] || {'
    guarded = [s.get("name", "") for s in steps if str(s.get("run", "")).lstrip().startswith(guard)]
    add("gate legs: a leg whose suite is not in the wrapper's list is said before the suite, and only the suite, the GeoIP check and the verdict wait for the row",
        len(listed) == 1 and 0 <= listed[0] < suite
        and sorted(guarded) == sorted(["The suite - every listed test runs and passes", "The leg ran with the pinned GeoIP database", "Verdict - required suite"]))

    # ... and a suite that IS listed and reports nothing stays red: the completeness job runs whatever the legs did, on the candidate's list
    comp = gate["jobs"].get("wrapper-e2e-complete", {})
    comp_run = " ".join(str(s.get("run", "")) for s in comp.get("steps", []))
    listed_run = steps[listed[0]]["run"] if len(listed) == 1 else ""
    add("gate legs: a listed suite with no result is red (wrapper-e2e-complete runs always, after the legs, `complete` on the candidate's list), "
        "and a list the leg cannot read is red, never 'not listed'",
        comp.get("needs") in ("wrapper-e2e", ["wrapper-e2e"]) and "always()" in str(comp.get("if", ""))
        and "complete --required ci/required-suites.json" in comp_run
        and "3) " in listed_run and "*) " in listed_run and "exit 1" in listed_run.split("*) ", 1)[-1])

    # the xpcshell leg: our xpcshell tests on the candidate's packaged binary, called from the gate
    xjob = gate["jobs"].get("xpcshell") or {}
    xdoc = yaml.safe_load((WORKFLOWS / "xpcshell.yml").read_text(encoding="utf-8"))
    xlegs = {(l["runner"], l["kind"]) for l in xdoc["jobs"]["xpcshell"]["strategy"]["matrix"]["include"]}
    add("gate legs: the real gate.yml has an xpcshell job that calls xpcshell.yml with the gate's build_run_id (the candidate's artifacts)",
        xjob.get("uses") == "./.github/workflows/xpcshell.yml" and xjob.get("with", {}).get("build_run_id") == "${{ inputs.build_run_id }}"
        and "published_tag" not in xjob.get("with", {}))
    add("gate legs: the xpcshell job runs on Linux and on Windows, 15 minutes each, and has the read permissions the called workflow needs",
        xlegs == {("ubuntu-24.04", "linux"), ("windows-latest", "win")} and xdoc["jobs"]["xpcshell"]["timeout-minutes"] == 15
        and xjob.get("permissions") == {"actions": "read", "contents": "read"})
    add("gate legs: the xpcshell job binds the gate (no continue-on-error, no `if` that skips it)", "continue-on-error" not in xjob and "if" not in xjob)

    # the real release.yml: the check runs before the node
    release = yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))
    rsteps = release["jobs"]["checks"]["steps"]
    check = [i for i, s in enumerate(rsteps) if "gate_legs.py" in (s.get("run") or "")]
    add("gate legs: the checks job of release.yml runs gate_legs.py on the wrapper's list",
        len(check) == 1 and "--required .wrapper/ci/required-suites.json" in rsteps[check[0]]["run"])
    co = [i for i, s in enumerate(rsteps) if (s.get("with") or {}).get("path") == ".wrapper"]
    w = rsteps[co[0]]["with"] if len(co) == 1 else {}
    add("gate legs: the checks job checks out the wrapper's list at wrapper_ref (main by default) before the check",
        len(co) == 1 and len(check) == 1 and co[0] < check[0] and w.get("repository") == "oss-invisible/playwright"
        and "inputs.wrapper_ref || 'main'" in w.get("ref", "") and "ci/required-suites.json" in w.get("sparse-checkout", ""))
    add("gate legs: the node waits for the checks job", "checks" in (release["jobs"]["node"].get("needs") or []))

    # the command, on a gate without the fake web's legs (what the commit before this one had): red there, green with them
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "required.json"
        req.write_text(json.dumps([_row("a"), _row(FAKEWEB)]), encoding="utf-8")
        old = Path(tmp) / "gate-old.yml"
        old.write_text(yaml.safe_dump(_gate(("a", "linux"), ("a", "windows"))), encoding="utf-8")
        res = _cli(req, old)
        add("gate legs: the command exits 1 and names the two missing legs on a gate without them", res.returncode == 1 and res.stdout.count(FAKEWEB) == 2)
        new = Path(tmp) / "gate-new.yml"
        new.write_text(yaml.safe_dump(_gate(("a", "linux"), ("a", "windows"), (FAKEWEB, "linux"), (FAKEWEB, "windows"))), encoding="utf-8")
        res = _cli(req, new)
        add("gate legs: the command exits 0 and says ok on a gate with them", res.returncode == 0 and res.stdout.startswith("ok:"))
    return out


def main() -> int:
    failures = 0
    found = cases()
    for name, ok in found:
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok
    print("%d/%d cases as expected" % (len(found) - failures, len(found)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
