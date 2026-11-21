r"""Every suite of the wrapper's list (ci/required-suites.json) has a leg in gate.yml, on every system the list names for it. Before the node.

The list of the required suites is the wrapper's; the matrix of the job `wrapper-e2e` of gate.yml is written by hand. A row of the list that nobody put in the
matrix is a suite that never runs, and the only check that said so was `wrapper-e2e-complete`, which runs after the engine build (run 44834434976: «COMPLETE RED:
wrapper.e2e.fakeweb/linux has no result: the leg did not report», forty minutes in). This one reads the two files and says it in seconds, in the `checks` job
of release.yml, before a server is turned on. The other direction too: a leg whose suite the list does not know is a leg nobody judges.

    python3 scripts/ci/gate_legs.py --required <wrapper>/ci/required-suites.json [--gate .github/workflows/gate.yml]

Exit 0 when the two agree, 1 and one line per disagreement when they do not.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github" / "workflows" / "gate.yml"
JOB = "wrapper-e2e"


def legs(gate: dict) -> list:
    """The rows of the matrix of the job `wrapper-e2e`, as written."""
    job = (gate.get("jobs") or {}).get(JOB) or {}
    return list(((job.get("strategy") or {}).get("matrix") or {}).get("include") or [])


def missing(required: list, gate: dict) -> list:
    """One readable line per (suite, os) of the list with no leg in the matrix, and per leg whose suite the list does not have."""
    rows = legs(gate)
    have = {(str(row.get("suite")), str(row.get("os"))) for row in rows}
    out = []
    for suite in required:
        for os_name in suite.get("os") or []:
            if (suite["id"], os_name) not in have:
                out.append("%s/%s has no leg in gate.yml's %s matrix" % (suite["id"], os_name, JOB))
    ids = {suite["id"] for suite in required}
    for suite, os_name in sorted(have):
        if suite not in ids:
            out.append("gate.yml's %s matrix has a leg %s/%s whose suite is not in the required list" % (JOB, suite, os_name))
    return out


def main(argv=None) -> int:
    import yaml

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--required", required=True, help="the wrapper's ci/required-suites.json")
    ap.add_argument("--gate", default=str(GATE), help="gate.yml (default: the one of this repository)")
    args = ap.parse_args(argv)
    required = json.loads(Path(args.required).read_text(encoding="utf-8"))
    gate = yaml.safe_load(Path(args.gate).read_text(encoding="utf-8"))
    problems = missing(required, gate)
    for line in problems:
        print("RED: " + line)
    if problems:
        return 1
    print("ok: the %d suites of the list have all their legs in gate.yml (%d legs)" % (len(required), len(legs(gate))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
