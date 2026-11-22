r"""The wrapper's list of required suites and the matrix of gate.yml agree before the node is turned on, and the fake web's suite has its legs and its control.

Run 44834434976 was red only on `wrapper-e2e-complete`: the list had `wrapper.e2e.fakeweb` on Linux and Windows and the hand-written matrix of `wrapper-e2e` had
no leg for it, which the run learned 40 minutes in, after the engine build. `scripts/ci/gate_legs.py` reads the two files and says it in the `checks` job of
release.yml; these cases hold that script to its known-bad inputs, and hold the real gate.yml to the legs and the control that the suite needs.

    python3 scripts/ci/test_gate_legs.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cargo_oracles  # noqa: E402
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
    # the cargo job: the unit tests of OUR Rust in WebRender run on a GitHub runner, and a run in which none of ours ran is red
    out.extend(cargo_cases(gate))
    # the package manifest A/B: the published engine's archives against a build's, a reusable workflow like the cargo one
    out.extend(package_cases(gate))
    return out


def _log(*rows) -> str:
    """What libtest prints for a run: one line per test and the closing line, whose counts follow the rows."""
    passed = sum(1 for _, how in rows if how == "ok")
    failed = sum(1 for _, how in rows if how == "FAILED")
    ignored = sum(1 for _, how in rows if how == "ignored")
    lines = ["running %d tests" % len(rows)] + ["test %s ... %s" % row for row in rows]
    status = "FAILED" if failed else "ok"
    return "\n".join(lines + ["", "test result: %s. %d passed; %d failed; %d ignored; 0 measured; 0 filtered out; finished in 0.00s" % (status, passed, failed, ignored)]) + "\n"


def cargo_cases(gate: dict) -> list:
    import yaml

    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    mod_b = "render_backend::stealth_shared_fonts::tests::"
    mdns = "stealth_tests::"
    assert set(cargo_oracles.OURS) == {mod_b, mdns}
    floor = cargo_oracles.OURS
    rows = [(mod_b + "t%d" % i, "ok") for i in range(floor[mod_b])] + [(mdns + "t%d" % i, "ok") for i in range(floor[mdns])]
    add("cargo: a log with every module of ours at its floor is green", cargo_oracles.judge(_log(*rows)) == [])
    add("cargo: a log with no test of ours is red (cargo itself is green on `0 passed`)", len(cargo_oracles.judge(_log(("tests::other", "ok")))) == len(cargo_oracles.OURS))
    short = [r for r in rows if r != (mod_b + "t0", "ok")]
    add("cargo: a module one test below its floor is red and names the module", any(mod_b in r for r in cargo_oracles.judge(_log(*short))))
    add("cargo: a log without the test of mdns_service (a tree that does not have it: cargo says `0 passed`) is red and names it",
        any(mdns in r for r in cargo_oracles.judge(_log(*[r for r in rows if not r[0].startswith(mdns)]))))
    add("cargo: the test of mdns_service that failed is red", any("FAILED" in r for r in cargo_oracles.judge(_log(*rows[:-1], (mdns + "t0", "FAILED")))))
    failing = [(rows[0][0], "FAILED")] + rows[1:]
    add("cargo: a test of ours that failed is red", any("FAILED" in r for r in cargo_oracles.judge(_log(*failing))))
    ignored = [(rows[0][0], "ignored")] + rows[1:]
    add("cargo: an ignored test of ours is red, not a smaller green", cargo_oracles.judge(_log(*ignored)) != [])
    add("cargo: a binary that ended FAILED is red even when no line of ours failed",
        cargo_oracles.judge(_log(*rows, ("tests::other", "FAILED"))) != [])
    add("cargo: a log with no `test result:` line (the build died) is red", cargo_oracles.judge("error: could not compile `webrender`\n") != [])
    # the floors are what the sources have: a test added to a module of ours raises the floor, never silently runs unjudged
    wr = ROOT / "gfx" / "wr"
    for mod, rel, head in ((mod_b, "webrender/src/render_backend/stealth_shared_fonts.rs", "mod tests"),):
        text = (wr / rel).read_text(encoding="utf-8")
        body = text.split(head, 1)[1] if head in text else ""
        add("cargo: the floor of %s is the number of #[test] in %s (%d)" % (mod, rel, floor[mod]), body.count("#[test]") == floor[mod])
    # mdns_service: src/stealth_tests.rs is a file of ours (declared in lib.rs by `#[cfg(test)] mod stealth_tests;`), so its floor is held to its count of #[test] too.
    # Where the tree does not have the file (a tree without hooks/fingerprint__webrtc__declared-network) there is nothing to count here, and the job is red (`0 passed`).
    ms = ROOT / "dom" / "media" / "webrtc" / "transport" / "mdns_service" / "src"
    two = "#[test]\nfn a() {}\n#[test]\nfn b() {}\n"
    add("cargo: a stealth_tests.rs with a second #[test] does not match the floor (the count check below is red on it)", two.count("#[test]") != floor[mdns])
    if (ms / "stealth_tests.rs").exists():
        body = (ms / "stealth_tests.rs").read_text(encoding="utf-8")
        add("cargo: the floor of %s is the number of #[test] in mdns_service/src/stealth_tests.rs (%d)" % (mdns, floor[mdns]), body.count("#[test]") == floor[mdns])
        # the registration form: one line, `#[cfg(test)] mod stealth_tests;` with its marker; without #[cfg(test)] the module would build into the product
        decl = re.compile(r"^#\[cfg\(test\)\] mod stealth_tests;  // STEALTH-HOOK\([\w/\-]+\)$", re.M)
        add("cargo: the registration line is recognised, and the same line without #[cfg(test)] or without its marker is not",
            bool(decl.search("#[cfg(test)] mod stealth_tests;  // STEALTH-HOOK(fingerprint/webrtc/declared-network)\n"))
            and not decl.search("mod stealth_tests;  // STEALTH-HOOK(fingerprint/webrtc/declared-network)\n")
            and not decl.search("#[cfg(test)] mod stealth_tests;\n"))
        add("cargo: lib.rs of mdns_service declares the module of ours, for the tests only, on one registration line (`#[cfg(test)] mod stealth_tests;` and its marker)",
            bool(decl.search((ms / "lib.rs").read_text(encoding="utf-8").replace("\r\n", "\n"))))
    wb = (wr / "webrender" / "Cargo.toml").read_text(encoding="utf-8")
    gr = (wr / "wr_glyph_rasterizer" / "Cargo.toml").read_text(encoding="utf-8")
    add("cargo: the dev-dependencies the job drops are in the manifests (mozangle once; glutin, glutin-winit, winit)",
        wb.count("\nmozangle = ") == 1 and all(gr.count("\n%s = " % d) == 1 for d in ("glutin", "glutin-winit", "winit")))

    # the real workflows
    text = (WORKFLOWS / "cargo-tests.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True)) or {}
    job = wf["jobs"]["cargo-tests"]
    steps = job["steps"]
    run = {s.get("name", ""): str(s.get("run", "")) for s in steps}
    call = gate["jobs"].get("cargo-tests") or {}
    add("cargo: gate.yml has one job that calls cargo-tests.yml, with no `needs` (beside the rest of the gate, never after it)",
        call.get("uses") == "./.github/workflows/cargo-tests.yml" and "needs" not in call and "runs-on" not in call
        and sum(1 for j in gate["jobs"].values() if "cargo-tests.yml" in str(j.get("uses", ""))) == 1)
    add("cargo: cargo-tests.yml is a reusable workflow, and runs on its own only for a push to latitude/*-oracles",
        set(on) == {"workflow_call", "push"} and on["push"].get("branches") == ["latitude/*-oracles"])
    add("cargo: the job has 15 minutes a leg, on a GitHub runner of each system (the Latitude node is for compiling)",
        job.get("timeout-minutes") == 15 and {r["runner"] for r in job["strategy"]["matrix"]["include"]} == {"ubuntu-24.04", "windows-latest"}
        and "latitude-" not in str(job.get("runs-on")) and "self-hosted" not in text)
    add("cargo: no cache is written (a target/ entry would evict release.yml's compile cache) and none is restored",
        "actions/cache" not in text and "Swatinem" not in text and "SCCACHE" not in text)
    tree = [n for n in run if "engine.py materialize" in run[n]]
    add("cargo: the tree is the materialized series (checked against UPSTREAM.json) into a repository whose sparse checkout, gfx/wr and the scripts, is set before",
        len(tree) == 1 and run[tree[0]].index("git sparse-checkout set --no-cone") < run[tree[0]].index("engine.py materialize --into .")
        and "'/gfx/wr/'" in run[tree[0]] and job["env"].get("MSYS_NO_PATHCONV") == "1")
    rust = [n for n in run if "upstream_toolchain.py" in run[n]]
    add("cargo: the Rust is the retail's release for this tree (the build's own script), not the runner's",
        len(rust) == 1 and "rust-version" in run[rust[0]] and "rustup default" in run[rust[0]])
    test = [s for s in steps if "cargo test -p" in str(s.get("run", ""))]
    cmd = str(test[0]["run"]) if len(test) == 1 else ""
    add("cargo: one cargo test, on the lib tests of webrender, filtered to our module and to nothing else, failing with cargo's own exit code",
        len(test) == 1 and "-p webrender --lib" in cmd and "wr_glyph_rasterizer" not in cmd and "set -o pipefail" in cmd
        and cmd.split(" -- ", 1)[-1].split(" 2>&1")[0].split() == list(cargo_oracles.FILTERS)
        and "continue-on-error" not in test[0] and "if" not in test[0] and "--no-fail-fast" not in cmd and "--workspace" not in cmd)
    verdict = [s for s in steps if "cargo_oracles.py verdict" in str(s.get("run", ""))]
    add("cargo: the verdict reads the log after the tests, even when cargo failed, and cannot be turned off",
        len(verdict) == 1 and len(test) == 1 and steps.index(verdict[0]) > steps.index(test[0]) and "always()" in str(verdict[0].get("if", ""))
        and "continue-on-error" not in verdict[0] and "|| true" not in verdict[0]["run"] and "set +e" not in verdict[0]["run"]
        and "gfx/wr/cargo-test.log" in verdict[0]["run"])
    second = [s for s in steps if "cargo test --lib" in str(s.get("run", ""))]
    scmd = str(second[0]["run"]) if len(second) == 1 else ""
    add("cargo: the test of mdns_service has its own cargo run (`--lib`, in its directory, standalone: [workspace], no gecko-profiler), after WebRender's, even if that was red",
        len(second) == 1 and len(test) == 1 and steps.index(second[0]) > steps.index(test[0]) and "if" in second[0] and "!cancelled()" in str(second[0]["if"])
        and second[0].get("working-directory") == "dom/media/webrtc/transport/mdns_service" and "set -eo pipefail" in scmd
        and "[workspace]" in scmd and "gecko-profiler" in scmd and "Cargo.lock" in scmd and "continue-on-error" not in second[0]
        and scmd.split(" -- ", 1)[-1].split(" 2>&1")[0].split() == list(cargo_oracles.MDNS_FILTERS)
        and "-p " not in scmd and "--workspace" not in scmd and "--no-fail-fast" not in scmd)
    add("cargo: the second run appends to the log of the first (one verdict reads both), and the verdict runs after it",
        len(second) == 1 and "tee -a" in scmd and "gfx/wr/cargo-test.log" in scmd and len(verdict) == 1 and steps.index(verdict[0]) > steps.index(second[0]))
    add("cargo: the sparse tree has the root Cargo.lock and the directory of mdns_service",
        len(tree) == 1 and "'/Cargo.lock'" in run[tree[0]] and "'/dom/media/webrtc/transport/mdns_service/'" in run[tree[0]])
    drop = [i for i, s in enumerate(steps) if "mozangle" in str(s.get("run", ""))]
    add("cargo: the dev-dependencies are dropped before cargo runs, and the step stops if one is still there",
        len(drop) == 1 and len(test) == 1 and drop[0] < steps.index(test[0]) and "exit 1" in str(steps[drop[0]]["run"]))
    keep = [s for s in steps if (s.get("with") or {}).get("path") == "gfx/wr/cargo-test.log"]
    add("cargo: the log is kept after a red run too", len(keep) == 1 and "always()" in str(keep[0].get("if", "")))
    return out


def main() -> int:
    failures = 0
    found = cases()
    for name, ok in found:
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok
    print("%d/%d cases as expected" % (len(found) - failures, len(found)))
    return 1 if failures else 0


def package_cases(gate: dict) -> list:
    import yaml

    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    text = (WORKFLOWS / "package-ab.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True)) or {}
    job = wf["jobs"]["package-ab"]
    steps = job["steps"]
    call = gate["jobs"].get("package-ab") or {}
    add("package-ab: gate.yml has one job that calls package-ab.yml, with no `needs` and no runner of its own, passing the build's run and the published tag",
        call.get("uses") == "./.github/workflows/package-ab.yml" and "needs" not in call and "runs-on" not in call and "steps" not in call
        and sum(1 for j in gate["jobs"].values() if "package-ab.yml" in str(j.get("uses", ""))) == 1
        and (call.get("with") or {}) == {"build_run_id": "${{ inputs.build_run_id }}", "published_tag": "${{ inputs.published_tag }}"})
    add("package-ab: the call can read the other run's artifacts and the release (actions: read, contents: read), and writes nothing",
        call.get("permissions") == {"actions": "read", "contents": "read"} and wf.get("permissions") == {"actions": "read", "contents": "read"})
    inputs = (on.get("workflow_call") or {}).get("inputs") or {}
    add("package-ab: package-ab.yml is a reusable workflow (build_run_id, published_tag firefox-68, candidate_tag empty), and runs on its own only for a push to latitude/*-oracles",
        set(on) == {"workflow_call", "push"} and on["push"].get("branches") == ["latitude/*-oracles"] and set(inputs) == {"build_run_id", "published_tag", "candidate_tag"}
        and inputs["published_tag"].get("default") == "firefox-68" and inputs["candidate_tag"].get("default") == "" and not any("required" in i for i in inputs.values()))
    mode = ((job.get("strategy") or {}).get("matrix") or {}).get("mode", "")
    add("package-ab: a push runs two legs of the job, the A/B of the run and the A/A of the published tag with itself; a call with candidate_tag is the A/A alone; the gate's call is the A/B alone",
        (job["strategy"].get("fail-fast") is False) and '["ab","tag"]' in mode and "github.event_name == 'push'" in mode and "inputs.candidate_tag != '' && '[\"tag\"]'" in mode
        and mode.rstrip(" }").endswith("'[\"ab\"]')")
        and job["env"].get("CAND_TAG") == "${{ matrix.mode == 'tag' && (inputs.candidate_tag || inputs.published_tag || 'firefox-68') || '' }}")
    add("package-ab: a push measures run 44921963200 against firefox-68 (the inputs of a push are empty), and a call uses what the gate passed",
        job["env"].get("BUILD_RUN_ID") == "${{ inputs.build_run_id || '44921963200' }}" and job["env"].get("TAG") == "${{ inputs.published_tag || 'firefox-68' }}")
    add("package-ab: 15 minutes on a GitHub runner, never the Latitude node",
        job.get("timeout-minutes") == 15 and job.get("runs-on") == "ubuntu-24.04" and "latitude-" not in text and "self-hosted" not in text)
    down = [s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact")]
    add("package-ab: the candidate is the asset-* of both legs and the source-commit of one run, read with the token when it is another run's",
        [(s["with"]["name"]) for s in down] == ["asset-linux-x86_64", "asset-win-x86_64", "source-commit"]
        and all(s["with"]["run-id"] == "${{ env.BUILD_RUN_ID }}" and "github.run_id" in s["with"]["github-token"] for s in down))
    built = [s for s in down if s["with"]["name"] == "source-commit"]
    add("package-ab: a build that recorded no source-commit is not an error of the download, the run's head_sha is the series commit",
        built[0].get("continue-on-error") is True and "series-commit.txt" in text and ".head_sha" in text)
    pub = [s for s in steps if s.get("id") == "published"]
    add("package-ab: the published release is checked against checksums.txt and its seal before anything is compared",
        len(pub) == 1 and "sha256sum -c checksums.txt" in pub[0]["run"] and pub[0]["run"].index("sha256sum -c") < pub[0]["run"].index("seal-check")
        and steps.index(pub[0]) < steps.index(down[0]))
    rel = [s for s in steps if s.get("id") == "candidate_release"]
    add("package-ab: the candidate release of the A/A is checked against its own checksums.txt and seal too, and only the legs of a tag download it; the artifacts of a run only the others",
        len(rel) == 1 and rel[0].get("if") == "env.CAND_TAG != ''" and "sha256sum -c checksums.txt" in rel[0]["run"] and "seal-check candidate-release" in rel[0]["run"]
        and "--output-name candidate_series_commit" in rel[0]["run"] and steps.index(rel[0]) < steps.index(down[0])
        and all(d.get("if") == "env.CAND_TAG == ''" for d in down))
    ab = [s for s in steps if ' compare "out/published' in str(s.get("run", ""))]
    cmd = str(ab[0]["run"]) if len(ab) == 1 else ""
    add("package-ab: the commits of the diff are fetched when this checkout lacks them, then explain, and one compare per leg whose red makes the step red",
        len(ab) == 1 and cmd.index("fetch --no-tags origin") < cmd.index(" explain ") < cmd.index(" compare ") and "FROM: ${{ steps.published.outputs.series_commit }}" in text
        and "|| RED=1" in cmd and 'exit "$RED"' in cmd and "continue-on-error" not in ab[0] and "if" not in ab[0] and "linux-x86_64 win-x86_64" in cmd)
    add("package-ab: the compare reads the content of both archives (the diff and the proof of build identity), and the A/A, a release with itself, expects that nothing changed",
        '--published-archive "$PUB" --candidate-archive "$1" $EXPECT' in cmd and 'EXPECT="--expect-identical"' in cmd and '[ "$CAND_TAG" = "$TAG" ]' in cmd
        and "CAND_FROM: ${{ steps.candidate_release.outputs.candidate_series_commit }}" in text)
    keep = [s for s in steps if (s.get("with") or {}).get("path") == "out"]
    add("package-ab: the lists and the reports are kept after a red run too", len(keep) == 1 and "always()" in str(keep[0].get("if", "")) and keep[0]["with"]["name"] == "package-ab${{ matrix.mode == 'tag' && '-aa' || '' }}")
    return out


if __name__ == "__main__":
    sys.exit(main())
