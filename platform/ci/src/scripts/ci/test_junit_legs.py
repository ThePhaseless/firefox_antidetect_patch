#!/usr/bin/env python3
"""The package, xpcshell and cargo legs write the junit the named hook tests judge reads: the artifacts `junit-py`, `junit-xpcshell` and `junit-cargo`.

The judge (scripts/ci/hook_tests_judge.py, main's) downloads `junit-*` of the run and reads the kind of junit from the folder's name: `junit-py`, `junit-xpcshell`,
`junit-cargo`, `junit-node`; a junit in any other `junit-*` folder is a problem and the judge is red. An artifact name is one per run, so a leg that runs on two
systems cannot write the artifact itself: each leg uploads a part named `junitpart-<kind>-<leg>` (which the judge does not read) and a job after the legs puts
the parts together as `junit-<kind>/<leg>/...`. These cases hold the real workflows to that: the names, the uploads that run whatever the tests said, and
that none of it can change a leg's verdict.

    python3 scripts/ci/test_junit_legs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
KINDS = ("junit-py", "junit-xpcshell", "junit-cargo", "junit-node")


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def uploads(job: dict) -> list:
    return [s for s in job.get("steps", []) if str(s.get("uses", "")).startswith("actions/upload-artifact")]


def downloads(job: dict) -> list:
    return [s for s in job.get("steps", []) if str(s.get("uses", "")).startswith("actions/download-artifact")]


def always(step: dict) -> bool:
    return "always()" in str(step.get("if", ""))


def index(steps: list, needle: str) -> int:
    found = [i for i, s in enumerate(steps) if needle in str(s.get("run", "")) or needle in str(s.get("name", ""))]
    return found[0] if found else -1


def cases() -> list:
    out = []

    def add(name, ok):
        out.append(("junit legs: " + name, bool(ok)))

    xpc, cargo, gate = load("xpcshell.yml"), load("cargo-tests.yml"), load("gate.yml")

    # --- the names: a `junit-*` artifact is one of the judge's kinds, and is uploaded once, by a job that is not a matrix
    named = []
    for wf_name in ("xpcshell.yml", "cargo-tests.yml", "gate.yml", "release.yml"):
        for job_id, job in load(wf_name)["jobs"].items():
            for step in uploads(job):
                artifact = str((step.get("with") or {}).get("name", ""))
                if artifact.startswith("junit"):
                    named.append((wf_name, job_id, artifact, "matrix" in (job.get("strategy") or {})))
    junit_names = [n for _w, _j, n, _m in named if n.startswith("junit-")]
    add("every upload named junit-* is one of the judge's kinds (a part is `junitpart-*`, which the judge does not read)",
        junit_names and all(n in KINDS for n in junit_names) and all(n.startswith("junitpart-") for _w, _j, n, _m in named if not n.startswith("junit-")))
    add("each junit-* artifact is uploaded once in these workflows, by a job with no matrix (a name is one per run)",
        len(junit_names) == len(set(junit_names)) and not any(m for _w, _j, n, m in named if n.startswith("junit-")))
    add("the three kinds of this change are all there: junit-py, junit-xpcshell, junit-cargo", {"junit-py", "junit-xpcshell", "junit-cargo"} <= set(junit_names))

    # --- xpcshell
    leg = xpc["jobs"]["xpcshell"]["steps"]
    parts = [s for s in uploads(xpc["jobs"]["xpcshell"]) if str((s.get("with") or {}).get("name", "")).startswith("junitpart-xpcshell-")]
    run_at = index(leg, "xpcshell_run.py run")
    add("xpcshell: each leg uploads its part, junitpart-xpcshell-<leg>, from junit-xpcshell, whatever the tests said (if: always()), after the tests ran",
        len(parts) == 1 and always(parts[0]) and parts[0]["with"]["name"] == "junitpart-xpcshell-${{ matrix.leg }}" and parts[0]["with"]["path"] == "junit-xpcshell"
        and leg.index(parts[0]) > run_at >= 0)
    arrange = [s for s in leg if "junit-xpcshell/${{ matrix.leg }}" in str(s.get("run", ""))]
    add("xpcshell: the leg's files sit under the leg's name, junit-xpcshell/<leg>/<path of the test file>.xml, copied from the runner's junit-xpcshell folder",
        len(arrange) == 1 and always(arrange[0]) and "xpcshell-result/junit-xpcshell" in arrange[0]["run"] and leg.index(arrange[0]) < leg.index(parts[0]))
    collect = xpc["jobs"].get("junit") or {}
    dl, up = downloads(collect), uploads(collect)
    add("xpcshell: the job `junit` runs after the legs whatever they said, downloads every part (merged) and uploads one artifact, junit-xpcshell",
        collect.get("needs") == "xpcshell" and "always()" in str(collect.get("if", "")) and len(dl) == 1 and dl[0]["with"]["pattern"] == "junitpart-xpcshell-*"
        and dl[0]["with"].get("merge-multiple") is True and dl[0]["with"]["path"] == "junit-xpcshell" and dl[0].get("continue-on-error") is True
        and len(up) == 1 and up[0]["with"]["name"] == "junit-xpcshell" and always(up[0]) and up[0]["with"]["path"] == "junit-xpcshell")
    runs = [s for s in leg if "xpcshell_run.py run" in str(s.get("run", ""))]
    add("xpcshell: the verdict of the leg is unchanged: the run step still binds (no continue-on-error, no `|| true`)",
        len(runs) == 1 and "continue-on-error" not in runs[0] and "|| true" not in runs[0]["run"])

    # --- cargo
    steps = cargo["jobs"]["cargo-tests"]["steps"]
    convert = [s for s in steps if "cargo_junit.py" in str(s.get("run", ""))]
    cargo_at, verdict_at = index(steps, "cargo test -p"), index(steps, "cargo_oracles.py verdict")
    parts = [s for s in uploads(cargo["jobs"]["cargo-tests"]) if str((s.get("with") or {}).get("name", "")).startswith("junitpart-cargo-")]
    add("cargo: the log becomes junit in a step that runs whatever cargo said, after cargo and before the verdict, and cannot fail the job",
        len(convert) == 1 and always(convert[0]) and convert[0].get("continue-on-error") is True and cargo_at < steps.index(convert[0]) < verdict_at
        and "gfx/wr/cargo-test.log" in convert[0]["run"] and "--out junit-cargo/${{ matrix.leg }}" in convert[0]["run"])
    cmd = str(steps[cargo_at]["run"]) if cargo_at >= 0 else ""
    mdns_run = [s for s in steps if s.get("id") == "cargo-mdns"]
    packages = [w for w in cmd.split() if w in ("webrender", "wr_glyph_rasterizer")] + (["mdns_service"] if mdns_run else [])
    add("cargo: --packages names the packages cargo ran (-p webrender, and the standalone crate mdns_service), so a crate keeps its package name in the junit",
        len(convert) == 1 and "--packages %s" % ",".join(packages) in convert[0]["run"] and len(packages) == 2)
    add("cargo: each leg uploads its part, junitpart-cargo-<leg>, from junit-cargo, whatever the tests said (if: always())",
        len(parts) == 1 and always(parts[0]) and parts[0]["with"]["name"] == "junitpart-cargo-${{ matrix.leg }}" and parts[0]["with"]["path"] == "junit-cargo"
        and steps.index(parts[0]) > steps.index(convert[0]))
    collect = cargo["jobs"].get("junit") or {}
    dl, up = downloads(collect), uploads(collect)
    add("cargo: the job `junit` runs after the legs whatever they said, downloads every part (merged) and uploads one artifact, junit-cargo",
        collect.get("needs") == "cargo-tests" and "always()" in str(collect.get("if", "")) and len(dl) == 1 and dl[0]["with"]["pattern"] == "junitpart-cargo-*"
        and dl[0]["with"].get("merge-multiple") is True and dl[0].get("continue-on-error") is True and len(up) == 1 and up[0]["with"]["name"] == "junit-cargo"
        and always(up[0]))
    verdict = [s for s in steps if "cargo_oracles.py verdict" in str(s.get("run", ""))]
    add("cargo: the verdict of the leg is unchanged: cargo_oracles.py verdict still reads the log, always(), and cannot be turned off",
        len(verdict) == 1 and always(verdict[0]) and "continue-on-error" not in verdict[0] and "exit \"${PIPESTATUS[0]}\"" in verdict[0]["run"])

    # --- python: two jobs write parts (package-ab: the series' tools/tests; checks: the tests of the tree), one job puts them together
    package = load("package-ab.yml")["jobs"]["package-ab"]["steps"]   # the job lives in the reusable workflow package-ab.yml
    pytest_step = [s for s in package if "pytest" in str(s.get("run", ""))]
    published_at = index(package, "gh release download")
    add("package: the series' python tests run first in the job (before the published engine is fetched), as junit, from the series checkout, and cannot fail the job",
        len(pytest_step) == 1 and package.index(pytest_step[0]) < published_at and pytest_step[0].get("continue-on-error") is True
        and pytest_step[0].get("working-directory") == "engine-series" and "tools/tests" in pytest_step[0]["run"]
        and "--junitxml=../junit-py/package-ab/" in pytest_step[0]["run"] and "--rootdir=." in pytest_step[0]["run"])
    keep = [s for s in package if (s.get("with") or {}).get("name") == "junitpart-py-package-ab"]
    add("package: its part is junitpart-py-package-ab, uploaded whatever happened before (if: always()), right after the tests, from junit-py (files under package-ab/)",
        len(keep) == 1 and always(keep[0]) and keep[0]["with"]["path"] == "junit-py" and package.index(keep[0]) == package.index(pytest_step[0]) + 1)
    ab = [s for s in package if "ab_package.py" in str(s.get("run", "")) and "explain" in str(s.get("run", ""))]
    add("package: the verdict of the job is unchanged: the A/B step still ends with `exit \"$RED\"` and has no continue-on-error",
        len(ab) == 1 and "continue-on-error" not in ab[0] and 'exit "$RED"' in ab[0]["run"])

    release = load("release.yml")
    checks = release["jobs"]["checks"]["steps"]
    tree_tests = [s for s in checks if "pytest" in str(s.get("run", ""))]
    materialize_at = index(checks, "engine.py materialize")
    add("checks: the python tests of OURS in the tree run right after the materialize (before every other step), through py_junit.py's list, as junit, and cannot fail the job",
        len(tree_tests) == 1 and checks.index(tree_tests[0]) == materialize_at + 1 and tree_tests[0].get("continue-on-error") is True
        and "scripts/ci/py_junit.py list --series .series --tree ." in tree_tests[0]["run"] and "--rootdir=." in tree_tests[0]["run"]
        and "--junitxml=junit-py/checks/" in tree_tests[0]["run"])
    keep = [s for s in checks if (s.get("with") or {}).get("name") == "junitpart-py-checks"]
    add("checks: its part is junitpart-py-checks, uploaded whatever happened (if: always()), after the tests and the `ran` step, from junit-py (files under checks/)",
        len(keep) == 1 and always(keep[0]) and keep[0]["with"]["path"] == "junit-py" and checks.index(keep[0]) == checks.index(tree_tests[0]) + 2)
    ran_step = [s for s in checks if "py_junit.py ran junit-py/checks/tree-tests.xml" in str(s.get("run", ""))]
    add("checks: a junit with no test that ran is a red step: `py_junit.py ran` on tree-tests.xml, right after the pytest step, before the upload, "
        "not continue-on-error (the upload is if: always(), so the junit is kept)",
        len(ran_step) == 1 and checks.index(ran_step[0]) == checks.index(tree_tests[0]) + 1 and checks.index(ran_step[0]) < checks.index(keep[0])
        and "continue-on-error" not in ran_step[0] and not ran_step[0].get("if"))
    add("checks: fonttools is pinned to one exact version, written once, in the pytest step (the tree and the CI pin none)",
        len(tree_tests) == 1 and tree_tests[0]["run"].count("fonttools==4.51.0") == 1
        and sum(str(s.get("run", "")).count("fonttools") for s in checks) == 1)
    parts_py = [str((s.get("with") or {}).get("name", "")) for wf in (gate, release, load("package-ab.yml")) for job in wf["jobs"].values() for s in uploads(job)
                if str((s.get("with") or {}).get("name", "")).startswith("junitpart-py-")]
    add("python parts: one per job and named by it (junitpart-py-<job>), the three there are, none twice: checks, package-ab, and the gate's "
        "security-state step, one per leg (junitpart-py-security-state-<leg>)",
        sorted(parts_py) == ["junitpart-py-checks", "junitpart-py-package-ab", "junitpart-py-security-state-${{ matrix.leg }}"])
    add("checks: pytest does not stop at a file that cannot be imported (--continue-on-collection-errors: run 45025164169 had one collection error, "
        "fontTools missing for scripts/test_gen_bundle_font_manifest.py, and no test of the tree wrote a result), and the step installs fonttools",
        len(tree_tests) == 1 and "--continue-on-collection-errors" in tree_tests[0]["run"] and "fonttools" in tree_tests[0]["run"])
    plan = release["jobs"]["plan"]["steps"]
    plain = ("scripts/ci/test_ci.py", "scripts/ci/test_stealth_download_watchdog.py", "scripts/ci/test_objects_first.py", "scripts/ci/test_stealth_build_tools.py",
             "scripts/test_release_plan.py")
    bare = {n: [s for s in plan if "python3 " + n in str(s.get("run", ""))] for n in plain}
    add("plan: no pip install and no junit step (nothing in the plan installs), and the verdict is unchanged: test_ci.py, the watchdog, objects_first, build_tools and "
        "test_release_plan.py still run as plain scripts, once each, with no continue-on-error",
        not any("pip" in str(s.get("run", "")) or "pytest" in str(s.get("run", "")) or "junit" in str(s.get("name", "")).lower() for s in plan)
        and all(len(v) == 1 and "continue-on-error" not in v[0] for v in bare.values()))
    add("checks: the pytest line names the plan's four tests that hooks name (scripts/ci/ is left out of py_junit's list), in the same session as the tree's tests",
        len(tree_tests) == 1 and all(n in tree_tests[0]["run"] for n in ("scripts/ci/test_stealth_build_tools.py", "scripts/ci/test_stealth_download_watchdog.py",
                                                                      "scripts/ci/test_objects_first.py", "scripts/test_release_plan.py"))
        and tree_tests[0]["run"].index("scripts/ci/test_stealth_build_tools.py") < tree_tests[0]["run"].index("python3 -m pytest $FILES"))
    merge = release["jobs"].get("junit-py") or {}
    dl, up = downloads(merge), uploads(merge)
    add("junit-py: one job puts every junitpart-py-* together (merged) after checks and both gates, whatever they said, and uploads the one artifact junit-py",
        {"checks", "gate", "gate-reuse"} <= set(merge.get("needs", [])) and "always()" in str(merge.get("if", "")) and len(dl) == 1
        and dl[0]["with"]["pattern"] == "junitpart-py-*" and dl[0]["with"].get("merge-multiple") is True and dl[0]["with"]["path"] == "junit-py"
        and dl[0].get("continue-on-error") is True and len(up) == 1 and up[0]["with"]["name"] == "junit-py" and always(up[0]) and up[0]["with"]["path"] == "junit-py")
    add("junit-py: no other job uploads an artifact named junit-py (a second upload of a name fails)",
        sum(1 for wf in (gate, release, xpc, cargo) for job in wf["jobs"].values() for s in uploads(job) if (s.get("with") or {}).get("name") == "junit-py") == 1)
    return out


if __name__ == "__main__":
    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
