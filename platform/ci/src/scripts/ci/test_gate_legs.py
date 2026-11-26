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
    add("gate legs: Playwright's own Firefox is installed for the fake web, before the suite",
        len(browser) == 1 and "matrix.suite == 'wrapper.e2e.fakeweb'" in steps[browser[0]].get("if", "") and 0 <= browser[0] < suite)
    # the host oracle's stock control on Windows launches Playwright's own Firefox (run 45121964904: not installed, so the control never ran); only there
    add("gate legs: Playwright's own Firefox is installed for the host oracle on Windows only, before the suite",
        len(browser) == 1 and "(matrix.suite == 'wrapper.e2e.ab_host' && matrix.os == 'windows')" in steps[browser[0]].get("if", "") and 0 <= browser[0] < suite)

    # the A/B oracles (published engine against the candidate: page, network, host): their legs, their longer budget, and their files kept
    ORACLES = ("wrapper.e2e.ab_oracle", "wrapper.e2e.ab_network", "wrapper.e2e.ab_host")
    CRASH = "wrapper.e2e.ab_host_crash"
    for ORACLE in ORACLES:
        add("gate legs: the real gate.yml has a %s leg on Linux and on Windows" % ORACLE, {(ORACLE, "linux"), (ORACLE, "windows")} <= have)
    # the host oracle's recorder: a leg of its own on Linux only, under its own row id (the verdict of the suite step judges it as that row)
    crash_rows = [r for r in gate_legs.legs(gate) if r.get("suite") == CRASH]
    add("gate legs: the real gate.yml has a %s leg on Linux and none on Windows (the row is linux_only)" % CRASH,
        (CRASH, "linux") in have and (CRASH, "windows") not in have and len(crash_rows) == 1 and crash_rows[0].get("kind") == "linux")
    add("gate legs: the %s leg has 35 minutes (its test's own guard and the setup), and the job reads its budget from the leg" % CRASH,
        len(crash_rows) == 1 and int(crash_rows[0].get("timeout", 0)) == 35
        and str(gate["jobs"]["wrapper-e2e"].get("timeout-minutes", "")).replace(" ", "") == "${{matrix.timeout||25}}")
    oracle_rows = [r for r in gate_legs.legs(gate) if r.get("suite") in ORACLES]
    add("gate legs: the oracles' legs have more than the default 25 minutes, and the job reads its budget from the leg",
        len(oracle_rows) == 2 * len(ORACLES) and all(int(r.get("timeout", 0)) > 25 for r in oracle_rows)
        and str(gate["jobs"]["wrapper-e2e"].get("timeout-minutes", "")).replace(" ", "") == "${{matrix.timeout||25}}")
    # the network legs: the test's guard with a candidate (3285 s, the measured run plus 25%) and the job's own steps fit with room for a slow runner (runs 45121964904, 45153612447)
    net_rows = [r for r in gate_legs.legs(gate) if r.get("suite") == "wrapper.e2e.ab_network"]
    add("gate legs: the network oracle's legs have 75 minutes (its guard of 3285 s with a candidate and the job's steps)",
        len(net_rows) == 2 and all(int(r.get("timeout", 0)) == 75 for r in net_rows))
    # the host oracle's laboratory on Windows: the location service of the runner is turned on before the suite (run 45153612447: off and denied, the stock control stood still)
    location = [i for i, s in enumerate(steps) if s.get("name") == "Turn on the Windows location service of the runner (the laboratory of the geolocation step)"]
    loc_run = steps[location[0]].get("run", "") if location else ""
    add("gate legs: the location service of the runner is turned on for the host oracle on Windows only, before the suite, and a setting that does not hold is red",
        len(location) == 1 and steps[location[0]].get("if", "") == "matrix.suite == 'wrapper.e2e.ab_host' && matrix.os == 'windows'"
        and steps[location[0]].get("shell") == "pwsh" and 0 <= location[0] < suite
        and "Start-Service -Name lfsvc" in loc_run and "-Value 'Allow'" in loc_run and "throw" in loc_run
        # a missing key is created with its parents (-Force; run 45176061220: a parent key of HKCU was not there), and only when it is not there
        and "if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }" in loc_run and "Get-ItemProperty -Path $key -Name Value" in loc_run)
    # the host oracle on Windows runs on the image of the wrapper's host job, where stock Firefox reaches the location provider (runs 45165805370, 45206303882)
    host_win = [r for r in gate_legs.legs(gate) if r.get("suite") == "wrapper.e2e.ab_host" and r.get("os") == "windows"]
    add("gate legs: the host oracle's Windows leg runs on windows-2022, the image of the wrapper's host job",
        len(host_win) == 1 and host_win[0].get("runner") == "windows-2022")
    add("gate legs: the location step reads Windows' answer (CheckAccess) before and after and is red unless it is Allowed",
        "AppCapability]::Create('location').CheckAccess()" in loc_run and "CheckAccess(location) before:" in loc_run
        and "if ($after -ne 'Allowed')" in loc_run and loc_run.index("CheckAccess(location) before:") < loc_run.index("Set-ItemProperty"))
    suite_run = steps[suite]["run"] if suite >= 0 else ""
    add("gate legs: the suite step gives the oracles' tests a folder of their own outside result/ (the completeness judge reads every JSON in result/)",
        'export AB_ORACLE_OUT="$PWD/ab-oracle"' in suite_run and "mkdir -p ab-oracle" in suite_run and "result/ab-oracle" not in suite_run)
    oracle_kept = [s for s in steps if (s.get("with") or {}).get("path") == "ab-oracle"]
    add("gate legs: the oracles' dumps and diffs are kept in an artifact of their own per suite and system, after a red suite too, for the oracles' suites only",
        len(oracle_kept) == 1 and all("matrix.suite == '%s'" % o in oracle_kept[0].get("if", "") for o in ORACLES + (CRASH,)) and "always()" in oracle_kept[0].get("if", "")
        and str(oracle_kept[0]["with"].get("name")).endswith("-${{ matrix.os }}") and "result-" not in str(oracle_kept[0]["with"]["name"]))
    add("gate legs: the oracles' artifact is kept before the result",
        len(oracle_kept) == 1 and keep >= 0 and steps.index(oracle_kept[0]) < keep and steps.index(oracle_kept[0]) > verdict >= 0)

    # the Linux legs of the oracles and of the recorder: gdb, elfutils and the kernel's core pattern pointed at INVPW_CORE_DIR, before the suite; strace for the host ones
    cores = [s for s in steps if "$RUNNER_TEMP/cores" in str(s.get("run", ""))]
    cond = str(cores[0].get("if", "")) if len(cores) == 1 else ""
    e2e_deps = ((gate["jobs"].get("linux-deps-e2e") or {}).get("with") or {})
    e2e_list = str(e2e_deps.get("packages", "")).split()
    add("gate legs: the cores step of the oracles' legs has gdb and elfutils (the linux-deps-e2e list), sets the pattern to $RUNNER_TEMP/cores, exports INVPW_CORE_DIR, on Linux, for the four suites, before the suite",
        len(cores) == 1 and "matrix.kind == 'linux'" in cond and all("matrix.suite == '%s'" % o in cond for o in ORACLES + (CRASH,))
        and {"gdb", "elfutils"} <= set(e2e_list) and "apt-get" not in cores[0]["run"]
        and 'mkdir -p "$RUNNER_TEMP/cores"' in cores[0]["run"] and 'chmod 1777 "$RUNNER_TEMP/cores"' in cores[0]["run"]
        and 'kernel.core_pattern="$RUNNER_TEMP/cores/core.%e.%p.%t"' in cores[0]["run"]
        and 'echo "INVPW_CORE_DIR=$RUNNER_TEMP/cores" >> "$GITHUB_ENV"' in cores[0]["run"] and "matrix.os" not in cond and names.index(cores[0]["name"]) < suite)
    deps = " ".join(str(s.get("run", "")) for s in steps if s.get("name") == "Linux system deps (Firefox runtime libs, a virtual display)")
    add("gate legs: the host oracle's leg and the recorder's leg have strace, as the fontconfig ones (the linux-deps-e2e list, installed by the system deps step of every Linux leg)",
        "strace" in e2e_list and "sudo apt-get $APT install -y --no-download --no-install-recommends $(cat /tmp/linux-deps/roots.txt)" in deps and "linux-deps-e2e" in gate["jobs"]["wrapper-e2e"].get("needs"))

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
    rsteps = yaml.safe_load((WORKFLOWS / "checks.yml").read_text(encoding="utf-8"))["jobs"]["tree"]["steps"]
    check = [i for i, s in enumerate(rsteps) if "gate_legs.py" in (s.get("run") or "")]
    add("gate legs: the job `tree` of checks.yml (which the checks job of release.yml calls) runs gate_legs.py on the wrapper's list",
        len(check) == 1 and "--required .wrapper/ci/required-suites.json" in rsteps[check[0]]["run"])
    co = [i for i, s in enumerate(rsteps) if (s.get("with") or {}).get("path") == ".wrapper"]
    w = rsteps[co[0]]["with"] if len(co) == 1 else {}
    add("gate legs: the checks job checks out the wrapper's list at wrapper_ref (main by default) before the check",
        len(co) == 1 and len(check) == 1 and co[0] < check[0] and w.get("repository") == "oss-invisible/playwright"
        and "inputs.wrapper_ref || 'main'" in w.get("ref", "") and "ci/required-suites.json" in w.get("sparse-checkout", ""))
    add("gate legs: the node waits for the checks job, which calls checks.yml with the run's wrapper_ref",
        "checks" in (release["jobs"]["node"].get("needs") or []) and release["jobs"]["checks"]["uses"] == "./.github/workflows/checks.yml"
        and release["jobs"]["checks"]["with"]["wrapper_ref"] == "${{ inputs.wrapper_ref || 'main' }}")

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
    # the runner's screen on Windows: the wrapper's e2e legs declare 1920x1080 and read it back, as the wrapper's own e2e jobs do
    out.extend(display_cases(gate))
    # the package manifest A/B: the published engine's archives against a build's, a reusable workflow like the cargo one
    out.extend(package_cases(gate))
    # ci-03: no leg of the gate (nor verify-assets, nor linux-deps) reads the index, a mirror or an unchecked archive
    out.extend(ci03_cases())
    return out


def _heredoc(run: str, which: int = 0) -> str:
    """The Python of the `which`th `python - <<'PY'` block of a step's script, as the shell hands it to the interpreter."""
    blocks = re.findall(r"<<'PY'\n(.*?)\n[ \t]*PY\n", run if run.endswith("\n") else run + "\n", re.S)
    return blocks[which]


def _run_python(code: str, args=(), cwd=None, env=None, isolated=True):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "step.py"
        script.write_text(code, encoding="utf-8")
        return subprocess.run([sys.executable] + (["-I"] if isolated else []) + [str(script), *args], capture_output=True, text=True, cwd=cwd, env=env)


def _fake_house(tmp: Path, core_commit: str, wrapper_commit: str, drift: str = ""):
    """A wheelhouse as py-deps.yml leaves it (two wheels, refs.json) and a site-packages with the same two distributions installed, as pip leaves them: the
    wheel's files in the installed RECORD. `drift` changes one thing: core-commit, wrapper-commit, core-file, core-wheel."""
    import hashlib
    import json
    import zipfile

    house, site = tmp / "py-deps", tmp / "site"
    house.mkdir()
    site.mkdir()
    refs = {}
    for kind, dist, commit in (("core", "invisible_core", core_commit), ("wrapper", "invisible_playwright", wrapper_commit)):
        files = {"%s/__init__.py" % dist: ("VERSION = 1\n" * 3).encode()}
        record = "".join("%s,sha256=%s,%d\n" % (n, hashlib.sha256(b).hexdigest(), len(b)) for n, b in sorted(files.items()))
        wheel = house / ("%s-1.0-py3-none-any.whl" % dist)
        with zipfile.ZipFile(wheel, "w") as z:
            for n, b in files.items():
                z.writestr(n, b)
            z.writestr("%s-1.0.dist-info/METADATA" % dist, "Metadata-Version: 2.1\nName: %s\nVersion: 1.0\n" % dist.replace("_", "-"))
            z.writestr("%s-1.0.dist-info/RECORD" % dist, record + "%s-1.0.dist-info/RECORD,,\n" % dist)
        refs[kind] = {"dist": dist, "wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "commit": commit, "extras": ""}
        # the installation: the files, and a dist-info whose RECORD has the wheel's lines (and more, as pip writes them)
        for n, b in files.items():
            (site / n).parent.mkdir(exist_ok=True)
            (site / n).write_bytes(b if not (drift == "core-file" and kind == "core") else b + b"# patched\n")
        info = site / ("%s-1.0.dist-info" % dist)
        info.mkdir()
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: %s\nVersion: 1.0\n" % dist.replace("_", "-"), encoding="utf-8")
        (info / "RECORD").write_text(record + "%s-1.0.dist-info/INSTALLER,,\n%s-1.0.dist-info/RECORD,,\n" % (dist, dist), encoding="utf-8")
    if drift == "core-file":
        # pip records what it wrote: the patched file has another hash than the wheel's line
        info = site / "invisible_core-1.0.dist-info" / "RECORD"
        body = "invisible_core/__init__.py,sha256=%s,%d\n" % (hashlib.sha256(b"VERSION = 1\n" * 3 + b"# patched\n").hexdigest(), 40)
        info.write_text(body + "invisible_core-1.0.dist-info/RECORD,,\n", encoding="utf-8")
    if drift == "core-wheel":
        wheel = house / refs["core"]["wheel"]
        wheel.write_bytes(wheel.read_bytes() + b"\0")
    (house / "refs.json").write_text(json.dumps(refs, indent=2), encoding="utf-8")
    return house, site


def _core_under_test_runs(code: str) -> dict:
    """The assertion of the core under test, run against a fake wheelhouse and a fake installation, in a repository whose HEAD is the wrapper's commit."""
    import os

    sha = "a" * 40
    results = {}
    for drift in ("", "core-commit", "wrapper-commit", "core-file", "core-wheel"):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            repo = tmp / "wrapper"
            repo.mkdir()
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@users.noreply.github.com"]
            subprocess.run(git + ["init", "-q"], cwd=repo, check=True, capture_output=True)
            (repo / "f").write_text("x", encoding="utf-8")
            subprocess.run(git + ["add", "f"], cwd=repo, check=True, capture_output=True)
            subprocess.run(git + ["commit", "-q", "-m", "x"], cwd=repo, check=True, capture_output=True)
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            house, site = _fake_house(tmp, "b" * 40 if drift == "core-commit" else sha, "c" * 40 if drift == "wrapper-commit" else head, drift)
            env = dict(os.environ, RUNNER_TEMP=str(tmp), CORE_REF=sha, PYTHONPATH=str(site))
            results[drift] = _run_python(code, cwd=repo, env=env, isolated=False)
    return results


def ci03_cases() -> list:
    """ci-03 over gate.yml, verify-assets.yml and linux-deps.yml: every pip install reads only the run's wheelhouse (--no-index --find-links, --require-hashes on the lock), the
    core under test is the wheel built from core_ref, Playwright's browser comes from a hash-checked archive, the Ubuntu packages of verify-assets from linux-deps."""
    import yaml

    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    gate = yaml.safe_load((WORKFLOWS / "gate.yml").read_text(encoding="utf-8"))
    gate_text = (WORKFLOWS / "gate.yml").read_text(encoding="utf-8")
    verify = yaml.safe_load((WORKFLOWS / "verify-assets.yml").read_text(encoding="utf-8"))
    deps = yaml.safe_load((WORKFLOWS / "linux-deps.yml").read_text(encoding="utf-8"))
    LOCK_INSTALL = 'python -m pip install --quiet --no-index --find-links "$RUNNER_TEMP/py-deps" --require-hashes -r "$RUNNER_TEMP/py-deps/lock.txt"'
    WHEELS_INSTALL = 'python -m pip install --quiet --no-index --no-deps --find-links "$RUNNER_TEMP/py-deps" invisible_core invisible_playwright'

    # --- the wheelhouse of the gate: one call, the wrapper's lock, the two refs -----------------------------------------------------------------------------
    call = gate["jobs"].get("py-deps-gate") or {}
    w = call.get("with") or {}
    add("ci-03 gate.yml: py-deps-gate calls py-deps.yml with the wrapper's gate lock at the wrapper_ref of the run, Python 3.11, the core at core_ref, the wrapper at wrapper_ref with its dev extra, "
        "Linux and Windows",
        call.get("uses") == "./.github/workflows/py-deps.yml" and w.get("lock_repository") == "oss-invisible/playwright" and w.get("lock_ref") == "${{ inputs.wrapper_ref }}"
        and w.get("lock") == "ci/py-lock/gate.txt" and w.get("python") == "3.11" and w.get("name") == "gate" and w.get("core_ref") == "${{ inputs.core_ref }}"
        and w.get("wrapper_ref") == "${{ inputs.wrapper_ref }}" and w.get("wrapper_extras") == "dev" and "core_extras" not in w
        and sorted(re.findall(r"[a-z0-9.-]+", w.get("runners", "")) ) == ["ubuntu-24.04", "windows-latest"])
    for job_name, artifact in (("gate", "py-deps-gate-${{ matrix.kind == 'win' && 'windows' || 'linux' }}"), ("wrapper-e2e", "py-deps-gate-${{ matrix.os }}")):
        job = gate["jobs"][job_name]
        steps = job["steps"]
        need = job.get("needs")
        need = [need] if isinstance(need, str) else list(need or [])
        fetch = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/download-artifact") and (s.get("with") or {}).get("name") == artifact]
        lock = [i for i, s in enumerate(steps) if str(s.get("run", "")).strip() == LOCK_INSTALL]
        wheels = [i for i, s in enumerate(steps) if WHEELS_INSTALL in str(s.get("run", ""))]
        pips = [l.strip() for s in steps for l in str(s.get("run", "")).splitlines() if re.search(r"\bpip3?\s+install\b", l) and not l.strip().startswith("#")]
        add("ci-03 gate.yml %s: it needs py-deps-gate, downloads the wheelhouse of its OS, installs the lock with its hashes, then the core and the wrapper wheels by name (no index, no dependency); "
            "no other pip install" % job_name,
            "py-deps-gate" in need and len(fetch) == 1 and len(lock) == 1 and len(wheels) == 1 and fetch[0] < lock[0] < wheels[0]
            and sorted(pips) == sorted([LOCK_INSTALL, WHEELS_INSTALL]) and (steps[fetch[0]].get("with") or {}).get("path") == "${{ runner.temp }}/py-deps")
    add("ci-03 gate.yml: no install from git or from a version, no direct_url.json: the core under test is read from the wheelhouse's refs.json",
        "git+https" not in gate_text and "direct_url" not in gate_text and "playwright==" not in gate_text and "cryptography==" not in gate_text and gate_text.count("refs.json") >= 2)
    os_values = {r.get("os") for r in gate["jobs"]["wrapper-e2e"]["strategy"]["matrix"]["include"]}
    add("ci-03 gate.yml: every leg of wrapper-e2e names its OS, linux or windows (the wheelhouse artifact is py-deps-gate-<os>)", os_values == {"linux", "windows"})

    # --- the core under test: the same assertion in both jobs, and it is red on every drift --------------------------------------------------------------------
    texts = []
    for job_name in ("gate", "wrapper-e2e"):
        steps = [s for s in gate["jobs"][job_name]["steps"] if WHEELS_INSTALL in str(s.get("run", ""))]
        texts.append(_heredoc(steps[0]["run"]) if len(steps) == 1 else "")
    add("ci-03 gate.yml: the core-under-test assertion of the gate and of the e2e legs is the same code", texts[0] == texts[1] and "refs.json" in texts[0] and "THE CORE UNDER TEST IS NOT core_ref" in texts[0])
    runs = _core_under_test_runs(texts[0]) if texts[0] else {}
    add("ci-03 gate.yml: the assertion is green when the wheelhouse's core is built from core_ref's commit, the wrapper from the checkout's, and the installed files are the wheels'%s"
        % ("" if runs.get("", None) is None or runs[""].returncode == 0 else ": " + runs[""].stderr[-300:]),
        bool(runs) and runs[""].returncode == 0 and "core under test: 1.0 from " + "a" * 40 in runs[""].stdout)
    add("ci-03 gate.yml: the assertion is RED when the core's wheel was built from another commit than core_ref's, naming it",
        bool(runs) and runs["core-commit"].returncode != 0 and "THE CORE UNDER TEST IS NOT core_ref" in runs["core-commit"].stderr and "b" * 40 in runs["core-commit"].stderr)
    add("ci-03 gate.yml: the assertion is RED when the wrapper's wheel was built from another commit than the checkout's",
        bool(runs) and runs["wrapper-commit"].returncode != 0 and "THE WRAPPER UNDER TEST IS NOT THIS CHECKOUT" in runs["wrapper-commit"].stderr)
    add("ci-03 gate.yml: the assertion is RED when what is installed is not the wheel's files (something put another core over it)",
        bool(runs) and runs["core-file"].returncode != 0 and "THE INSTALLED invisible-core IS NOT ITS WHEEL" in runs["core-file"].stderr)
    add("ci-03 gate.yml: the assertion is RED when the wheel in the wheelhouse is not the one the resolver built (sha256)",
        bool(runs) and runs["core-wheel"].returncode != 0 and "THE CORE WHEEL IS NOT THE ONE THE RESOLVER BUILT" in runs["core-wheel"].stderr)

    # --- Playwright's browser: a hash-checked archive, served on the loopback ---------------------------------------------------------------------------------
    pf = gate["jobs"].get("playwright-firefox") or {}
    pf_steps = pf.get("steps") or []
    pf_run = [s for s in pf_steps if "urlopen" in str(s.get("run", ""))]
    pf_code = _heredoc(pf_run[0]["run"]) if len(pf_run) == 1 else ""
    co = [s for s in pf_steps if str(s.get("uses", "")).startswith("actions/checkout")]
    add("ci-03 gate.yml: playwright-firefox reads the wrapper's pin of the archives (ci/py-lock/playwright-browsers.json) at wrapper_ref, on Linux and on Windows, and uploads playwright-firefox-<os>",
        len(co) == 1 and co[0]["with"].get("ref") == "${{ inputs.wrapper_ref }}" and "ci/py-lock/playwright-browsers.json" in co[0]["with"].get("sparse-checkout", "")
        and {(m["os"], m["platform"]) for m in pf["strategy"]["matrix"]["include"]} == {("linux", "ubuntu24.04-x64"), ("windows", "win64")}
        and any((s.get("with") or {}).get("name") == "playwright-firefox-${{ matrix.os }}" for s in pf_steps))
    add("ci-03 gate.yml: playwright-firefox puts TEMP and TMP on D:\\a\\_temp on Windows, as every Windows job",
        "D:\\a\\_temp" in str((pf.get("env") or {}).get("TEMP", "")) and "D:\\a\\_temp" in str((pf.get("env") or {}).get("TMP", "")))
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        (tmp / "wrapper" / "scripts").mkdir(parents=True)
        (tmp / "wrapper" / "scripts" / "playwright_pin.txt").write_text("1.61.0\n", encoding="utf-8")
        env = {"RUNNER_TEMP": str(tmp / "rt"), "PLATFORM": "win64", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
        missing = _run_python(pf_code, cwd=tmp, env=env) if pf_code else None
        pin = tmp / "wrapper" / "ci" / "py-lock"
        pin.mkdir(parents=True)
        (pin / "playwright-browsers.json").write_text(json.dumps({"playwright": "1.60.0", "platforms": {"win64": [{"path": "builds/firefox/1/firefox-win64.zip", "sha256": "0" * 64}]}}), encoding="utf-8")
        moved = _run_python(pf_code, cwd=tmp, env=env) if pf_code else None
        (pin / "playwright-browsers.json").write_text(json.dumps({"playwright": "1.61.0", "platforms": {"ubuntu24.04-x64": []}}), encoding="utf-8")
        none = _run_python(pf_code, cwd=tmp, env=env) if pf_code else None
        (pin / "playwright-browsers.json").write_text(json.dumps({"playwright": "1.61.0", "platforms": {"win64": [{"path": "builds/../x.zip", "sha256": "0" * 64}]}}), encoding="utf-8")
        badpath = _run_python(pf_code, cwd=tmp, env=env) if pf_code else None
    add("ci-03 gate.yml: playwright-firefox is RED, naming ci/py-lock/playwright-browsers.json, when the wrapper_ref has no such file",
        missing is not None and missing.returncode != 0 and "no wrapper/ci/py-lock/playwright-browsers.json" in missing.stderr)
    add("ci-03 gate.yml: playwright-firefox is RED when the pin is for another Playwright than scripts/playwright_pin.txt, when the platform has no archive, and on a path that is not under builds/",
        moved is not None and moved.returncode != 0 and "is for Playwright 1.60.0" in moved.stderr
        and none is not None and none.returncode != 0 and "no archives for win64" in none.stderr
        and badpath is not None and badpath.returncode != 0 and "not a path under builds/" in badpath.stderr)
    add("ci-03 gate.yml: playwright-firefox compares every download with the pinned sha256 and goes on to another host only when a download FAILS, never on another hash",
        "hashlib.sha256(data).hexdigest()" in pf_code and "if got != sha:" in pf_code and "except Exception" in pf_code and pf_code.count("break") == 1
        and pf_code.index("if got != sha:") > pf_code.index("except Exception"))
    e2e = gate["jobs"]["wrapper-e2e"]
    e2e_steps = e2e["steps"]
    names = [s.get("name", "") for s in e2e_steps]
    cond = "matrix.suite == 'wrapper.e2e.fakeweb' || (matrix.suite == 'wrapper.e2e.ab_host' && matrix.os == 'windows')"
    fetch = [i for i, s in enumerate(e2e_steps) if (s.get("with") or {}).get("name") == "playwright-firefox-${{ matrix.os }}"]
    inst = [i for i, s in enumerate(e2e_steps) if re.search(r"\bplaywright install firefox\b", str(s.get("run", "")))]
    suite = names.index(SUITE_STEP)
    install_run = str(e2e_steps[inst[0]].get("run", "")) if len(inst) == 1 else ""
    install_code = _heredoc(install_run) if install_run else ""
    add("ci-03 gate.yml: the e2e legs that need Playwright's Firefox need playwright-firefox, download its archives and let Playwright's installer read them from a server on 127.0.0.1 "
        "(PLAYWRIGHT_DOWNLOAD_HOST), checked first against the pin of the checkout, before the suite",
        "playwright-firefox" in e2e["needs"] and len(fetch) == 1 and len(inst) == 1 and fetch[0] < inst[0] < suite and e2e_steps[fetch[0]].get("if") == cond and e2e_steps[inst[0]].get("if") == cond
        and 'export PLAYWRIGHT_DOWNLOAD_HOST="http://127.0.0.1:$PORT"' in install_run and "--bind 127.0.0.1" in install_run and "hashlib.sha256" in install_code
        and install_run.index("hashlib.sha256") < install_run.index("python -m playwright install firefox") and "trap 'kill \"$SERVER\"" in install_run)
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        env = {"RUNNER_TEMP": str(tmp), "RUNNER_OS": "Windows", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
        nopin = _run_python(install_code, ["1"], cwd=tmp, env=env) if install_code else None
    add("ci-03 gate.yml: the leg is RED, naming ci/py-lock/playwright-browsers.json, when its checkout has no pin of the archives",
        nopin is not None and nopin.returncode != 0 and "no ci/py-lock/playwright-browsers.json" in nopin.stderr)

    # --- verify-assets.yml ---------------------------------------------------------------------------------------------------------------------------------------
    vtext = (WORKFLOWS / "verify-assets.yml").read_text(encoding="utf-8")
    vj = verify["jobs"]
    vcall = vj.get("py-deps-assets") or {}
    vdeps = vj.get("linux-deps-assets") or {}
    drive = vj["drive"]
    vsteps = drive["steps"]
    vrun = "\n".join(str(s.get("run", "")) for s in vsteps)
    add("ci-03 verify-assets.yml: the Python packages come from the gate lock's wheelhouse (py-deps.yml, the wrapper's ci/py-lock/gate.txt at main, which is the wrapper it checks out), "
        "installed offline with their hashes",
        vcall.get("uses") == "./.github/workflows/py-deps.yml" and vcall["with"].get("lock_repository") == "oss-invisible/playwright" and vcall["with"].get("lock_ref") == "main"
        and vcall["with"].get("lock") == "ci/py-lock/gate.txt" and "py-deps-assets" in drive["needs"] and LOCK_INSTALL in vrun
        and any((s.get("with") or {}).get("name") == "py-deps-assets-${{ matrix.kind == 'win' && 'windows' || 'linux' }}" for s in vsteps)
        and not re.search(r"\bpip3?\s+install\b(?!.*--no-index)", vrun) and "playwright==" not in vtext)
    add("ci-03 verify-assets.yml: the Ubuntu packages of Firefox's runtime come from linux-deps.yml (the roots of install-deps from the locked Playwright's table), by name with --no-download; no install-deps",
        vdeps.get("uses") == "./.github/workflows/linux-deps.yml" and vdeps["with"].get("playwright_wrapper_ref") == "main" and "linux-deps-assets" in drive["needs"]
        and "install-deps" not in vrun and "sudo apt-get $APT install -y --no-download --no-install-recommends $(cat /tmp/linux-deps/roots.txt)" in vrun
        and "sudo apt-get $APT update" in vrun and "sudo apt-get update" not in vrun
        and any((s.get("with") or {}).get("name") == "${{ needs.linux-deps-assets.outputs.artifact }}" and (s.get("with") or {}).get("path") == "/tmp/linux-deps" for s in vsteps))

    # --- linux-deps.yml: the table is read from the locked wheel ---------------------------------------------------------------------------------------------
    dsteps = deps["jobs"]["debs"]["steps"]
    spec = [s for s in dsteps if s.get("id") == "spec"][0]
    miss = [s for s in dsteps if "apt-get download" in str(s.get("run", ""))][0]
    dco = [s for s in dsteps if str(s.get("uses", "")).startswith("actions/checkout")]
    add("ci-03 linux-deps.yml: the Playwright whose table names install-deps' roots is the wrapper's locked one: its gate lock is checked out, no `pip install playwright`, the one wheel is downloaded "
        "with --require-hashes --no-deps (on a miss only) and coreBundle.js is read from the zip; the stanza is part of the entry's key",
        len(dco) == 1 and dco[0]["with"].get("sparse-checkout") == "ci/py-lock/gate.txt" and "playwright==" not in miss["run"] and not re.search(r"pip3?\s+install", miss["run"])
        and "pip download --quiet --disable-pip-version-check --only-binary=:all: --no-deps --require-hashes" in miss["run"] and "zipfile.ZipFile(wheels[0])" in miss["run"]
        and "playwright/driver/package/lib/coreBundle.js" in miss["run"] and "playwright-lock-stanza: sha256" in spec["run"]
        and miss.get("if") == "steps.restore.outputs.cache-hit != 'true'" and "no ci/py-lock/gate.txt at $PW_REF" in spec["run"])
    code = _heredoc(spec["run"])
    good = "aiohttp==3.9.0 \\\n    --hash=sha256:" + "1" * 64 + "\nplaywright==1.61.0 \\\n    --hash=sha256:" + "2" * 64 + " \\\n    --hash=sha256:" + "3" * 64 + "\npluggy==1.0 \\\n    --hash=sha256:" + "4" * 64 + "\n"
    cases_ = {"good": good, "none": "pluggy==1.0 \\\n    --hash=sha256:" + "4" * 64 + "\n", "nohash": "playwright==1.61.0 \\\n\npluggy==1.0\n",
              "badhash": "playwright==1.61.0 \\\n    --hash=sha256:xyz\n", "open": "playwright==1.61.0 \\\n    --hash=sha256:" + "2" * 64 + " \\\n"}
    got = {}
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for k, text in cases_.items():
            (tmp / (k + ".txt")).write_text(text, encoding="utf-8")
            got[k] = _run_python(code, [str(tmp / (k + ".txt")), str(tmp / (k + ".out"))])
        stanza = (tmp / "good.out").read_text(encoding="utf-8") if (tmp / "good.out").exists() else ""
    add("ci-03 linux-deps.yml: the playwright stanza is read from the lock (version and every hash, as a requirements file) and the step is RED on a lock with no playwright, with no hash, "
        "a line that is not a hash, or a stanza that does not end",
        got["good"].returncode == 0 and got["good"].stdout.strip() == "1.61.0" and stanza == "playwright==1.61.0 \\\n    --hash=sha256:" + "2" * 64 + " \\\n    --hash=sha256:" + "3" * 64 + "\n"
        and all(got[k].returncode != 0 for k in ("none", "nohash", "badhash", "open")))
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
    glean = cargo_oracles.GLEAN_TEST
    assert set(cargo_oracles.OURS) == {mod_b, mdns, glean}
    floor = cargo_oracles.OURS
    rows = ([(mod_b + "t%d" % i, "ok") for i in range(floor[mod_b])] + [(mdns + "t%d" % i, "ok") for i in range(floor[mdns])]
            + [(glean, "ok")] * floor[glean])
    add("cargo: a log with every module of ours at its floor is green", cargo_oracles.judge(_log(*rows)) == [])
    add("cargo: a log with no test of ours is red (cargo itself is green on `0 passed`)", len(cargo_oracles.judge(_log(("tests::other", "ok")))) == len(cargo_oracles.OURS))
    short = [r for r in rows if r != (mod_b + "t0", "ok")]
    add("cargo: a module one test below its floor is red and names the module", any(mod_b in r for r in cargo_oracles.judge(_log(*short))))
    add("cargo: a log without the test of mdns_service (a tree that does not have it: cargo says `0 passed`) is red and names it",
        any(mdns in r for r in cargo_oracles.judge(_log(*[r for r in rows if not r[0].startswith(mdns)]))))
    add("cargo: the test of mdns_service that failed is red",
        any("FAILED" in r for r in cargo_oracles.judge(_log(*[r for r in rows if r[0] != mdns + "t0"], (mdns + "t0", "FAILED")))))
    # the test of upstream's that the glean-core backport carries: a tree without the backport has no such test (cargo says `0 passed`: red, the row is red on the code as
    # vendored), with it the row is green; a failure of it is red
    add("cargo: a log without the glean-core test (the crate as vendored, without the backport: cargo says `0 passed` for the filter) is red and names it",
        any(glean in r for r in cargo_oracles.judge(_log(*[r for r in rows if r[0] != glean]))))
    add("cargo: the glean-core test that failed is red", any("FAILED" in r for r in cargo_oracles.judge(_log(*[r for r in rows if r[0] != glean], (glean, "FAILED")))))
    add("cargo: the glean-core filter is the full path of the one test, a path under its module (dispatcher::test::), and the row's floor is 1",
        cargo_oracles.GLEAN_FILTERS == (glean,) and glean.startswith("dispatcher::test::") and floor[glean] == 1)
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
    # glean-core: the test the backport carries is in the vendored crate's dispatcher tests, once, as a #[test] fn
    gd = (ROOT / "third_party" / "rust" / "glean-core" / "src" / "dispatcher" / "mod.rs").read_text(encoding="utf-8").replace("\r\n", "\n")
    name = glean.rsplit("::", 1)[1]
    add("cargo: the glean-core test named by the row is a #[test] fn of mod test in glean-core's dispatcher/mod.rs, once (the backport carries it)",
        gd.count("    #[test]\n    fn %s()" % name) == 1 and gd.count("fn %s(" % name) == 1 and "\nmod test {" in gd)
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
    # 18 minutes: the old max of 12m22s plus the glean-core step (2m03 on win, run 45718525016: job 9m41s win, 6m02s linux) is about 14.5 minutes, plus 25%; to be set
    # again to the largest measured time plus 25% when three runs have the third run
    add("cargo: the job has 18 minutes a leg (15 before the glean-core run: its worst case is about 14.5 minutes, plus 25%), on a GitHub runner of each system (the Latitude node is for compiling)",
        job.get("timeout-minutes") == 18 and {r["runner"] for r in job["strategy"]["matrix"]["include"]} == {"ubuntu-24.04", "windows-latest"}
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
    second = [s for s in steps if "cargo test --lib" in str(s.get("run", "")) and s.get("working-directory") == "dom/media/webrtc/transport/mdns_service"]
    third = [s for s in steps if "cargo test --lib" in str(s.get("run", "")) and s.get("working-directory") == "third_party/rust/glean-core"]
    tcmd = str(third[0]["run"]) if len(third) == 1 else ""
    add("cargo: the test of the glean-core backport has its own cargo run (`--lib`, in third_party/rust/glean-core, standalone: [workspace], the unused dev-dependencies dropped and checked), after mdns_service's, even if that was red",
        len(third) == 1 and len(second) == 1 and steps.index(third[0]) > steps.index(second[0]) and "!cancelled()" in str(third[0].get("if", ""))
        and "set -eo pipefail" in tcmd and "[workspace]" in tcmd and "exit 1" in tcmd and "continue-on-error" not in third[0]
        and all(d in tcmd for d in ("criterion", "pulldown-cmark-to-cmark", "xshell", "yaml-rust2"))
        and "env_logger" not in tcmd and "tempfile" not in tcmd and "ctor" not in tcmd
        and tcmd.split(" -- ", 1)[-1].split(" 2>&1")[0].split() == list(cargo_oracles.GLEAN_FILTERS)
        and "-p " not in tcmd and "--workspace" not in tcmd and "--no-fail-fast" not in tcmd and "tee -a" in tcmd and "gfx/wr/cargo-test.log" in tcmd
        and len(verdict) == 1 and steps.index(verdict[0]) > steps.index(third[0]))
    add("cargo: the sparse tree has the directory of glean-core",
        len(tree) == 1 and "'/third_party/rust/glean-core/'" in run[tree[0]])
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


# ---------------------------------------------------------------------------------------------------- the runner's screen on Windows

#: The step every Windows leg of the wrapper's e2e carries (wrapper PR 609, run 45730213378 of oss-invisible/playwright): the runner's screen is 1024x768 and the
#: browser window of the e2e is 1936x1048, so the OS cursor cannot be parked outside the window (tests/_os_cursor.py) and a native move for it reaches the page.
DISPLAY_STEP = "The runner's screen is 1920x1080, larger than the browser window is tall (read back)"
DISPLAY_SET = "Set-DisplayResolution -Width 1920 -Height 1080 -Force"
DISPLAY_READBACK = "if ($b.Width -lt 1920 -or $b.Height -lt 1080) {"


def _condition(expr, leg: dict) -> bool:
    """The `if:` of a step for one leg of the matrix: the forms gate.yml uses (`matrix.<key>`, ==, &&, ||, !, startsWith)."""
    if expr is None:
        return True
    text = str(expr).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    text = re.sub(r"startsWith\(\s*matrix\.(\w+)\s*,\s*('[^']*')\s*\)", lambda m: "(str(leg.get(%r, '')).startswith(%s))" % (m.group(1), m.group(2)), text)
    text = re.sub(r"matrix\.(\w+)", lambda m: "leg.get(%r)" % m.group(1), text)
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text)
    return bool(eval(text, {"__builtins__": {}, "str": str}, {"leg": leg}))


def display_problems(job: dict) -> list:
    """What is wrong with the screen step of a job like `wrapper-e2e`: every Windows leg whose suite is a wrapper.e2e.* one runs a step of exactly that name and body, before the
    step of the suite, and no Linux leg runs it; the read-back exits 1 below 1920x1080."""
    steps = job.get("steps") or []
    legs = [leg for leg in job["strategy"]["matrix"]["include"]]
    named = [s for s in steps if s.get("name") == DISPLAY_STEP]
    suite_at = next((i for i, s in enumerate(steps) if str(s.get("name", "")).startswith(SUITE_STEP)), -1)
    found = []
    if len(named) != 1:
        return ["the job has %d steps named %r, one is expected" % (len(named), DISPLAY_STEP)]
    step = named[0]
    body = str(step.get("run", ""))
    if step.get("shell") != "pwsh":
        found.append("the step does not run in pwsh")
    if DISPLAY_SET not in body:
        found.append("the step does not set the mode with `%s`" % DISPLAY_SET)
    if DISPLAY_READBACK not in body or "exit 1" not in body.split(DISPLAY_READBACK, 1)[-1] or "Write-Error" not in body.split(DISPLAY_READBACK, 1)[-1]:
        found.append("the read-back does not fail (Write-Error, exit 1) below 1920x1080")
    if "VirtualScreen" not in body:
        found.append("the screen is not read back from the VirtualScreen")
    if suite_at < 0 or steps.index(step) > suite_at:
        found.append("the step is not before the step of the suite")
    for leg in legs:
        windows_e2e = leg.get("os") == "windows" and str(leg.get("suite", "")).startswith("wrapper.e2e.")
        runs = _condition(step.get("if"), leg)
        if windows_e2e and not runs:
            found.append("the Windows leg %s does not run it" % leg.get("suite"))
        if not windows_e2e and runs:
            found.append("the leg %s (%s) runs it, and is not a Windows wrapper.e2e leg" % (leg.get("suite"), leg.get("os")))
    return found


def display_cases(gate: dict) -> list:
    import copy

    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    job = gate["jobs"]["wrapper-e2e"]
    legs = job["strategy"]["matrix"]["include"]
    windows_e2e = [l["suite"] for l in legs if l.get("os") == "windows" and str(l["suite"]).startswith("wrapper.e2e.")]
    add("screen: gate.yml has Windows wrapper.e2e legs (the step is for them)", len(windows_e2e) >= 10)
    add("screen: every Windows wrapper.e2e leg of gate.yml has the step, in the right place, and no other leg has it: %s" % (", ".join(display_problems(job)) or "ok"),
        display_problems(job) == [])
    add("screen: the wrapper.unit.* legs of Windows, which run no browser, do not get it", any(str(l["suite"]).startswith("wrapper.unit.") and l.get("os") == "windows" for l in legs)
        and not any(_condition(next(s for s in job["steps"] if s.get("name") == DISPLAY_STEP).get("if"), l) for l in legs if str(l["suite"]).startswith("wrapper.unit.")))

    def mutated(change):
        j = copy.deepcopy(job)
        change(j)
        return display_problems(j)

    def drop(j):
        j["steps"] = [s for s in j["steps"] if s.get("name") != DISPLAY_STEP]

    def late(j):
        step = next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP)
        j["steps"].remove(step)
        j["steps"].append(step)

    def weak(j):
        step = next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP)
        step["run"] = step["run"].replace("$b.Width -lt 1920 -or $b.Height -lt 1080", "$b.Width -lt 1024 -or $b.Height -lt 768")

    def no_exit(j):
        step = next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP)
        step["run"] = step["run"].replace("exit 1", "")

    def other_mode(j):
        step = next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP)
        step["run"] = step["run"].replace("-Width 1920 -Height 1080", "-Width 1280 -Height 1024")

    def renamed(j):
        next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP)["name"] = "The runner's screen"

    def everywhere(j):
        next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP).pop("if")

    def linux_only(j):
        next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP)["if"] = "matrix.os == 'linux'"

    def one_leg_short(j):
        next(s for s in j["steps"] if s.get("name") == DISPLAY_STEP)["if"] = "matrix.os == 'windows' && matrix.suite != 'wrapper.e2e.page'"

    add("screen: a job without the step is red", mutated(drop) != [])
    add("screen: the step after the suite is red", mutated(late) != [])
    add("screen: a read-back that accepts 1024x768 is red", mutated(weak) != [])
    add("screen: a read-back that does not exit 1 is red", mutated(no_exit) != [])
    add("screen: another mode than 1920x1080 is red", mutated(other_mode) != [])
    add("screen: another name is red", mutated(renamed) != [])
    add("screen: the step on every leg, Linux included, is red", mutated(everywhere) != [])
    add("screen: the step for Linux only is red", mutated(linux_only) != [])
    add("screen: a Windows wrapper.e2e leg without it is red and names it", any("wrapper.e2e.page" in p for p in mutated(one_leg_short)))
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
    add("package-ab: package-ab.yml is a reusable workflow (build_run_id, published_tag empty - the latest published, candidate_tag empty), and runs on its own only for a push to latitude/*-oracles",
        set(on) == {"workflow_call", "push"} and on["push"].get("branches") == ["latitude/*-oracles"] and set(inputs) == {"build_run_id", "published_tag", "candidate_tag"}
        and inputs["published_tag"].get("default") == "" and inputs["candidate_tag"].get("default") == "" and not any("required" in i for i in inputs.values()))
    mode = ((job.get("strategy") or {}).get("matrix") or {}).get("mode", "")
    add("package-ab: a push runs two legs of the job, the A/B of two releases (the latest against the one before it) and the A/A of the latest with itself; a call with candidate_tag is the A/A alone; the gate's call is the A/B alone",
        (job["strategy"].get("fail-fast") is False) and '["ab","tag"]' in mode and "github.event_name == 'push'" in mode and "inputs.candidate_tag != '' && '[\"tag\"]'" in mode
        and mode.rstrip(" }").endswith("'[\"ab\"]')")
        and job["env"].get("CAND_TAG") == "${{ matrix.mode == 'tag' && (inputs.candidate_tag || inputs.published_tag) || '' }}")
    add("package-ab: a call uses the run the gate passed, else this run's own (never a run id written in the workflow); the published engine is the input, else the latest published",
        job["env"].get("BUILD_RUN_ID") == "${{ inputs.build_run_id || github.run_id }}" and job["env"].get("TAG") == "${{ inputs.published_tag }}")
    latest = [s for s in steps if "published_release.py" in str(s.get("run", ""))]
    add("package-ab: the resolver step runs only when published_tag is empty, writes TAG (and CAND_TAG of the A/A, and of the A/B of two releases on its own push, with --rank 2 for the base) to GITHUB_ENV, has the token",
        len(latest) == 1 and latest[0].get("if") == "inputs.published_tag == ''" and 'echo "TAG=$BASE" >> "$GITHUB_ENV"' in latest[0]["run"]
        and 'echo "CAND_TAG=$LATEST" >> "$GITHUB_ENV"' in latest[0]["run"] and "--rank 2" in latest[0]["run"] and latest[0]["env"].get("GH_TOKEN") == "${{ github.token }}"
        and "engine-series/platform/ci/src/scripts/ci/published_release.py" in latest[0]["run"])
    add("package-ab: 15 minutes on a GitHub runner, never the Latitude node",
        job.get("timeout-minutes") == 15 and job.get("runs-on") == "ubuntu-24.04" and "latitude-" not in text and "self-hosted" not in text)
    # the candidate's artifacts, of the run named by BUILD_RUN_ID (the wheelhouse of the job's py-deps call is this run's own: no run-id)
    down = [s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact") and "run-id" in (s.get("with") or {})]
    add("package-ab: the candidate is the asset-* of both legs and the source-commit of one run, read with the token when it is another run's",
        [(s["with"]["name"]) for s in down] == ["asset-linux-x86_64", "asset-win-x86_64", "source-commit"]
        and all(s["with"]["run-id"] == "${{ env.BUILD_RUN_ID }}" and "github.run_id" in s["with"]["github-token"] for s in down))
    built = [s for s in down if s["with"]["name"] == "source-commit"]
    add("package-ab: a build that recorded no source-commit is not an error of the download, the run's head_sha is the series commit",
        built[0].get("continue-on-error") is True and "series-commit.txt" in text and ".head_sha" in text)
    pub = [s for s in steps if s.get("id") == "published"]
    add("package-ab: the resolver step comes before the published download",
        len(latest) == 1 and len(pub) == 1 and steps.index(latest[0]) < steps.index(pub[0]))
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
