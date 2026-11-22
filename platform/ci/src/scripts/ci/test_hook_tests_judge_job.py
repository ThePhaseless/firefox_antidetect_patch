#!/usr/bin/env python3
"""The job that runs the named hook tests judge (.github/workflows/hook-tests-judge.yml, called by release.yml) binds: it comes after the gate and the gtests, the
publish needs it, its judge is MAIN's (`.series-main/tools/hook_tests_judge.py`, the second checkout at ref main) and a main without it fails closed, and the
`checks` job keeps the junit of Juggler's tests that the judge reads. The judge and its own cases are the series' (tools/hook_tests_judge.py,
tools/tests/test_hook_tests_judge.py).

    python3 scripts/ci/test_hook_tests_judge_job.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def cases() -> list:
    import yaml

    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    release = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    jobs = release["jobs"]
    call, reuse = jobs.get("hook-tests-judge", {}), jobs.get("hook-tests-judge-reuse", {})
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "hook-tests-judge.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["judge"]
    steps = {s.get("name", ""): s for s in job["steps"]}
    run = next((s["run"] for s in job["steps"] if "hook_tests_judge.py" in s.get("run", "")), "")
    add("hook-tests-judge: the job comes after the plan, the checks, the build, the gate and the gtests of both legs",
        all(n in call.get("needs", []) for n in ("plan", "checks", "build", "gate", "gtest-cross", "gtest-linux")))
    # The junit the judge reads is written by merge jobs of the branch ci/legs-junit: `junit-py` (release.yml; after checks, gate and gate-reuse) and the
    # `junit` jobs of xpcshell.yml and cargo-tests.yml, which the gate calls. The judge waits for `junit-py` and for the gate: this file is valid only with them.
    add("hook-tests-judge: both calls wait for junit-py (and, through the gate, for the xpcshell and cargo junit) before they read the artifacts",
        "junit-py" in call.get("needs", []) and "junit-py" in reuse.get("needs", []) and "gate" in call.get("needs", []) and "gate-reuse" in reuse.get("needs", []))
    if "junit-py" in jobs:  # both branches applied: junit-py is after the checks and both gates, whatever they said, and the junit jobs are in the workflows the gate calls
        wf_dir = ROOT / ".github" / "workflows"
        junit_py = jobs["junit-py"]
        gate_wfs = {n: yaml.safe_load((wf_dir / n).read_text(encoding="utf-8")) for n in ("xpcshell.yml", "cargo-tests.yml") if (wf_dir / n).is_file()}
        add("hook-tests-judge: with ci/legs-junit, junit-py is after the checks, the gate and the reuse gate and runs whatever they said; the xpcshell and cargo "
            "workflows have their merge job `junit`",
            all(n in junit_py.get("needs", []) for n in ("checks", "gate", "gate-reuse")) and str(junit_py.get("if", "")).startswith("always()")
            and set(gate_wfs) == {"xpcshell.yml", "cargo-tests.yml"} and all("junit" in w["jobs"] for w in gate_wfs.values()))
    # junit-py is after the reuse gate, which a run that builds skips: a skipped ancestor skips the publish (actions/runner#2205) unless it names its needs' results
    pub_if = str(jobs["publish"].get("if", ""))
    add("hook-tests-judge: the publish does not rely on the implicit success() (a skipped ancestor, the reuse gate behind junit-py, would skip it): it names the result of each need",
        pub_if.startswith("!cancelled()") and all(("needs.%s.result == 'success'" % n) in pub_if for n in jobs["publish"]["needs"] if n != "plan")
        and "needs.plan.result == 'success'" in pub_if)
    add("hook-tests-judge: it runs whatever the gate and the gtests said (always()), never on a compile-only run or a failed build",
        str(call.get("if", "")).startswith("always()") and "stop_after != 'objects'" in str(call.get("if", "")) and "needs.build.result == 'success'" in str(call.get("if", "")))
    add("hook-tests-judge: the publish needs it, and the reuse gate is NOT among its needs (a skipped ancestor would skip the publish: actions/runner#2205)",
        "hook-tests-judge" in jobs["publish"]["needs"] and "gate-reuse" not in call["needs"] and "hook-tests-judge-reuse" not in jobs["publish"]["needs"])
    add("hook-tests-judge: a run that reused a green build is judged too, after the reuse gate, on the gtest reports of the run it found",
        reuse.get("needs") == ["plan", "checks", "gate-reuse", "junit-py"] and "reuse_run_id != ''" in str(reuse.get("if", ""))
        and reuse["with"]["reuse_run_id"] == "${{ needs.plan.outputs.reuse_run_id }}" and call["with"]["reuse_run_id"] == ""
        and call["uses"] == reuse["uses"] == "./.github/workflows/hook-tests-judge.yml")
    add("hook-tests-judge: both calls hand over the plan's gtests and filter, and ask for read access to actions only",
        all(c["with"]["gtests"] == "${{ needs.plan.outputs.gtests }}" and c["with"]["gtest_filter"] == "${{ needs.plan.outputs.gtest_filter }}"
            and c["permissions"] == {"actions": "read", "contents": "read"} for c in (call, reuse)))
    checkouts = [s["with"] for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    main = [w for w in checkouts if w.get("ref") == "main"]
    add("hook-tests-judge: the judge is main's (a checkout of this repository at main), the list is the candidate's",
        len(checkouts) == 2 and len(main) == 1 and main[0].get("repository") == "${{ github.repository }}" and main[0].get("path") == ".series-main" and main[0].get("sparse-checkout") == "tools"
        and ".series-main/tools/hook_tests_judge.py" in run and "--series .series " in run)
    add("hook-tests-judge: a main without the judge fails closed (an error and exit 1), and the candidate's copy never runs in its place",
        '[ ! -f "$JUDGE" ]' in run and "::error::" in run and 0 <= run.find("exit 1") < run.find("python3 ")
        and ".series/tools/hook_tests_judge.py" not in run.replace(".series-main/tools", ""))
    add("hook-tests-judge: it binds (no continue-on-error, no `|| true`, no `if` on its steps)",
        "continue-on-error" not in str(job) and "|| true" not in run and not any("if" in s for s in job["steps"]))
    dl = [s["with"] for s in job["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact")]
    add("hook-tests-judge: it downloads the wrapper results, the gtest reports (of the run a reuse found, else this one) and the junit of the run",
        [w["pattern"] for w in dl] == ["result-*", "gtest-reports-*", "junit-*"] and "inputs.reuse_run_id || github.run_id" in str(dl[1].get("run-id", ""))
        and job.get("permissions", {}).get("actions") == "read")
    add("hook-tests-judge: the judge is handed the plan's filter and gtests, and the table of platform-only suites of the candidate's gtest_run.py",
        steps["Every named test exists in this run and passed"]["env"] == {"GTESTS": "${{ inputs.gtests }}", "GTEST_FILTER_INPUT": "${{ inputs.gtest_filter }}"}
        and '--gtest-filter "$GTEST_FILTER_INPUT"' in run and '--gtests "$GTESTS"' in run
        and "--gtest-run .series/platform/ci/src/scripts/ci/gtest_run.py" in run)
    node = next((s for s in jobs["checks"]["steps"] if s.get("name") == "Juggler's tests without a browser"), {})
    names = [s.get("name") for s in jobs["checks"]["steps"]]
    keep = next((s for s in jobs["checks"]["steps"] if s.get("name") == "Keep the junit of Juggler's tests"), {})
    add("checks: Juggler's tests run one file at a time with a junit each at junit-node/<tree path>.xml, and a red file is a red step",
        "juggler/tests/*.test.mjs" in node.get("run", "") and "--test-reporter=junit" in node["run"] and 'junit-node/$f.xml' in node["run"]
        and "|| rc=1" in node["run"] and node["run"].rstrip().endswith('exit "$rc"') and "if" not in node and "continue-on-error" not in node)
    add("checks: the junit is kept whatever the tests said (always) as junit-node, before the guard, which stays the last step",
        keep.get("if") == "always()" and keep.get("with", {}).get("name") == "junit-node" and keep["with"].get("path") == "junit-node"
        and names.index("Keep the junit of Juggler's tests") > names.index("Juggler's tests without a browser") and names[-1] == "Still the head of the branch")
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
