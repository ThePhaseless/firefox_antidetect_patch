r"""Every job of the workflows that runs on a GitHub Windows runner has TEMP and TMP on D:, set on the job.

The profile of every Firefox a leg launches is made in TEMP. On the Windows runners of GitHub the default TEMP is on C:, and four browsers at once
saturate that disk (a queue up to 144, latencies up to 4 s): the parent's main thread stays still 40-60 s and the legs fail at random (a `goto` that
hangs, a start that never answers). Measured on 20/11 with two hunts of the wrapper's e2e: the profiles on C: took 5 of 4 shards, TEMP and TMP on
`D:\a\_temp` took none. A test cannot fail for a reason that is not its own, so the fix is at the source: the job's `env` names D:.

`runner.temp` is not readable in a job's `env` (only `github`, `needs`, `strategy`, `matrix`, `inputs`, `secrets` and `vars` are), so the job names
the runner's temp folder itself: `D:\a\_temp`, which the runner makes before the first step. A job that runs on both systems says
`startsWith(matrix.runner, 'windows') && 'D:\a\_temp' || '/tmp'` (`/tmp` is what Linux uses anyway). The `build` job runs on the Linux node and
cross-compiles the Windows leg: it is not a Windows job.

    python3 scripts/ci/test_gate_windows_temp.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
BS = chr(92)
D_TEMP = "D:" + BS + "a" + BS + "_temp"
CONDITIONAL = re.compile(
    r"^\$\{\{\s*startsWith\((?P<ctx>matrix\.\w+),\s*'windows'\)\s*&&\s*'(?P<win>[^']*)'\s*\|\|\s*'(?P<other>[^']*)'\s*\}\}$")
CONTEXT = re.compile(r"\$\{\{\s*(matrix\.\w+)\s*\}\}")


def _legs(job: dict) -> list:
    """One dict `{"matrix.runner": "windows-latest", ...}` per leg of the job's matrix (one empty dict when it has none or it is computed at run time)."""
    matrix = (job.get("strategy") or {}).get("matrix")
    if not isinstance(matrix, dict):
        return [{}]
    matrix = dict(matrix)
    include = matrix.pop("include", None) or []
    matrix.pop("exclude", None)
    legs = [{}]
    for key, values in matrix.items():
        legs = [dict(leg, **{"matrix." + key: v}) for leg in legs for v in values]
    rows = [{"matrix." + k: v for k, v in row.items()} for row in include]
    return rows if (rows and not matrix) else legs + rows


def _value(leg: dict, raw) -> str:
    raw = str(raw).strip()
    m = CONDITIONAL.match(raw)
    if not m:
        return raw
    return m.group("win") if str(leg.get(m.group("ctx"), "")).startswith("windows") else m.group("other")


def problems(name: str, doc: dict) -> list:
    """One line per Windows leg of the workflow whose TEMP or TMP is not on D:."""
    out = []
    for job_id, job in (doc.get("jobs") or {}).items():
        if "runs-on" not in job:
            continue
        env = job.get("env") or {}
        for leg in _legs(job):
            runner = CONTEXT.sub(lambda m: str(leg.get(m.group(1), "?")), str(job["runs-on"]))
            if "windows" not in runner:
                continue
            for var in ("TEMP", "TMP"):
                value = _value(leg, env[var]) if var in env else None
                if value is None or not value.upper().startswith("D:" + BS):
                    out.append("%s: job `%s` on %s has %s=%r, not a folder on D:" % (name, job_id, runner, var, value))
    return out


def windows_jobs() -> list:
    """The (workflow, job) pairs that run on a Windows runner: what the check is meant to judge, so that a reader that sees none is not a green."""
    import yaml

    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (doc.get("jobs") or {}).items():
            for leg in _legs(job):
                if "windows" in CONTEXT.sub(lambda m: str(leg.get(m.group(1), "?")), str(job.get("runs-on", ""))):
                    found.append((path.name, job_id))
                    break
    return found


def _job(runs_on, env=None, matrix=None) -> dict:
    return {"jobs": {"a": {"runs-on": runs_on, "env": env, "strategy": {"matrix": matrix} if matrix else None, "steps": []}}}


def cases() -> list:
    import yaml

    out = []

    def add(name, ok):
        out.append((name, bool(ok)))

    for path in sorted(WORKFLOWS.glob("*.yml")):
        found = problems(path.name, yaml.safe_load(path.read_text(encoding="utf-8")))
        add("windows temp: %s - every Windows job has TEMP and TMP on D:%s" % (path.name, "" if not found else ": " + "; ".join(found)), not found)
    seen = set(windows_jobs())
    expected = {("gate.yml", "gate"), ("gate.yml", "wrapper-e2e"), ("verify-assets.yml", "drive"), ("release.yml", "gtest-cross")}
    add("windows temp: the check sees the Windows jobs it is meant to judge%s" % ("" if expected <= seen else ": it misses %s" % sorted(expected - seen)),
        expected <= seen)
    add("windows temp: the build job (the Linux node cross-compiles) is not taken for a Windows job", ("release.yml", "build") not in seen)
    # A check that has only ever said fine is not known to say anything else.
    add("windows temp: a Windows job with no TEMP is refused", problems("x.yml", _job("windows-2022")))
    add("windows temp: TEMP on C: is refused", len(problems("x.yml", _job("windows-2022", {"TEMP": "C:" + BS + "t", "TMP": D_TEMP}))) == 1)
    add("windows temp: TEMP without TMP is refused", len(problems("x.yml", _job("windows-2022", {"TEMP": D_TEMP}))) == 1)
    add("windows temp: both on D: is accepted", problems("x.yml", _job("windows-2022", {"TEMP": D_TEMP, "TMP": D_TEMP})) == [])
    cond = "${{ startsWith(matrix.runner, 'windows') && '" + D_TEMP + "' || '/tmp' }}"
    include = {"include": [{"leg": "linux", "runner": "ubuntu-24.04"}, {"leg": "win", "runner": "windows-latest"}]}
    add("windows temp: a matrix job with D: on its Windows leg is accepted", problems("x.yml", _job("${{ matrix.runner }}", {"TEMP": cond, "TMP": cond}, include)) == [])
    wrong_way = cond.replace("'" + D_TEMP + "' || '/tmp'", "'/tmp' || '" + D_TEMP + "'")
    add("windows temp: a matrix job that is on C: on its Windows leg is refused", len(problems("x.yml", _job("${{ matrix.runner }}", {"TEMP": wrong_way, "TMP": wrong_way}, include))) == 2)
    add("windows temp: a Windows leg of an `include` matrix with no TEMP is seen", len(problems("x.yml", _job("${{ matrix.runner }}", None, include))) == 2)
    add("windows temp: a Linux job is not judged", problems("x.yml", _job("ubuntu-24.04")) == [])
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
