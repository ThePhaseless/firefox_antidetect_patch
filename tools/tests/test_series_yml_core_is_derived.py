"""The core checkout of the series' checks (checks.yml, job `rebuilds`, which series.yml calls with
wrapper_ref main and release.yml with the run's own) reads the core the wrapper pins, derived by
the release resolver, never a commit written in the workflow (decision ci-05).

It was a literal sha moved by hand at each port. The step `core` runs
`release_plan.py --resolve-core-ref --wrapper-ref "$WRAPPER_REF"`, appends its one `core_ref=<ref>`
line to $GITHUB_OUTPUT, and the checkout of the core takes `steps.core.outputs.core_ref`.

    python -m pytest tools/tests
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKS_YML = ROOT / ".github" / "workflows" / "checks.yml"
SERIES_YML = ROOT / ".github" / "workflows" / "series.yml"


def _rebuilds(text):
    return yaml.safe_load(text)["jobs"]["rebuilds"]["steps"]


def _core_checkout(steps):
    found = [i for i, s in enumerate(steps)
             if s.get("uses", "").startswith("actions/checkout@") and s.get("with", {}).get("repository") == "oss-invisible/core"]
    assert len(found) == 1, "one checkout of the core in the rebuilds job"
    return found[0]


def check(text):
    steps = _rebuilds(text)
    at = _core_checkout(steps)
    ref = str(steps[at]["with"]["ref"])
    assert ref == "${{ steps.core.outputs.core_ref }}", "the core ref is the output of the resolver step, not %r" % ref
    assert not re.search(r"[0-9a-f]{40}", ref)
    resolver = [i for i, s in enumerate(steps) if s.get("id") == "core"]
    assert len(resolver) == 1 and resolver[0] < at, "the resolver step `core` comes before the core checkout"
    step = steps[resolver[0]]
    run = step["run"]
    assert 'platform/ci/src/scripts/release_plan.py --resolve-core-ref --wrapper-ref "$WRAPPER_REF"' in run
    assert step["env"]["WRAPPER_REF"] == "${{ inputs.wrapper_ref || 'main' }}", "the wrapper is the caller's wrapper_ref, main by default"
    assert '>> "$GITHUB_OUTPUT"' in run, "its core_ref= line goes to the step's output"
    assert "set -euo pipefail" in run, "a resolver that fails fails the job"
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}", "the resolver reads the wrapper through gh api"
    # the resolver is read from the series checkout, which comes first
    assert any(s.get("uses", "").startswith("actions/checkout@") and s.get("with", {}).get("path") == ".series"
               for s in steps[:resolver[0]])
    return True


def test_the_core_checkout_of_the_checks_is_the_resolver_output_and_not_a_sha():
    assert check(CHECKS_YML.read_text(encoding="utf-8"))


def test_the_series_rounds_call_the_checks_with_the_wrapper_of_main():
    call = yaml.safe_load(SERIES_YML.read_text(encoding="utf-8"))["jobs"]["checks"]
    assert call["uses"] == "./.github/workflows/checks.yml" and call["with"] == {"wrapper_ref": "main"}


def test_no_forty_hex_core_reference_is_written_in_the_workflow():
    steps = _rebuilds(CHECKS_YML.read_text(encoding="utf-8"))
    core = steps[_core_checkout(steps)]["with"]
    assert not any(re.fullmatch(r"[0-9a-f]{40}", str(v)) for v in core.values()), core


def test_the_known_bad_workflow_is_refused():
    """The workflow as it was: a literal commit in the checkout and no resolver step."""
    old = CHECKS_YML.read_text(encoding="utf-8").replace(
        "${{ steps.core.outputs.core_ref }}", "f598297cd22120432c7fbe3508af4926b367e469")
    try:
        check(old)
    except AssertionError:
        return
    raise AssertionError("a literal core commit was accepted")
