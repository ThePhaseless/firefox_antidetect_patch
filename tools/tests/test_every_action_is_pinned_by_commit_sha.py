"""Every `uses:` of every workflow of this repository runs code pinned by a commit SHA: an action, or a reusable workflow of another repository,
is `owner/repo[/path]@<40 hex>` with its version in a trailing comment; a workflow of this repository is a local `./` path. A tag or a branch
moves under the run (a release of the action, a push to another repository's main) and the code that runs is no longer the code reviewed.

    python -m pytest tools/tests
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
RULE = "actions pinned by commit SHA"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
LINE = re.compile(r"^\s*-?\s*uses:\s*(\S+)\s*(#\s*\S.*)?$")


def problems(name, text):
    """FAIL lines for one workflow's text: a `uses:` that is neither local nor pinned by a full SHA with a comment naming its version."""
    out = []
    doc = yaml.safe_load(text) or {}
    commented = {m.group(1): bool(m.group(2)) for m in (LINE.match(l) for l in text.splitlines()) if m}
    for job_name, job in (doc.get("jobs") or {}).items():
        places = [("the job calls a workflow", job.get("uses"))] if job.get("uses") else []
        places += [(step.get("name") or "step %d" % i, step.get("uses")) for i, step in enumerate(job.get("steps") or [], 1) if step.get("uses")]
        for where, uses in places:
            uses = str(uses)
            if uses.startswith("./"):
                continue
            if not PINNED.match(uses):
                out.append("FAIL %s / %s / %s: `uses: %s` is not pinned to a 40-hex commit SHA. Fix: resolve the tag through the API "
                           "(gh api repos/<owner>/<repo>/git/ref/tags/<tag>, peel an annotated tag) and write the SHA with the version in a comment. "
                           "Rule: %s" % (name, job_name, where, uses, RULE))
            elif not commented.get(uses):
                out.append("FAIL %s / %s / %s: `uses: %s` has no trailing comment naming its version. Fix: add `# <version>` after the SHA. "
                           "Rule: %s" % (name, job_name, where, uses, RULE))
    return out


def test_every_workflow_pins_what_it_uses():
    found = [p for wf in sorted(WORKFLOWS.glob("*.yml")) for p in problems(wf.name, wf.read_text(encoding="utf-8"))]
    assert not found, "\n".join(found)


def test_a_tag_a_branch_and_another_repositorys_main_are_refused():
    for bad in ("actions/checkout@v4", "pypa/gh-action-pypi-publish@release/v1", "oss-invisible/core/.github/workflows/x.yml@main",
                "actions/checkout@11d5960a", "actions/checkout@11D5960A326750D5838078E36CF38B85AF677262"):
        text = "on: push\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: %s # v4\n" % bad
        assert problems("x.yml", text), bad


def test_a_sha_with_its_version_and_a_local_workflow_are_accepted():
    good = ("on: push\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4 (v4.4.0)\n"
            "  k:\n    uses: ./.github/workflows/checks.yml\n")
    assert problems("x.yml", good) == []
    bare = "on: push\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
    assert any("no trailing comment" in p for p in problems("x.yml", bare))
