"""Rule C18 (port-07): an anchor is chosen where Mozilla is quiet (docs/decisions/port-07-quiet-anchors.md).

A hook in a hunk whose churn (tools/churn.json: in how many of the last eight releases Mozilla changed a line near it) is at least
churn.BAND_MIN_CHURN names in its HOOKS.json entry why no quieter anchor serves: `quiet_anchor_why`, {kind: only-place, why} or
{kind: deferred, quieter}. Each case is a one-hook series built here; the tests break one thing at a time:

  * a hook in the band with no reason, a hook with no churn at all (new, moved, or its text changed), a missing churn file: red;
  * `only-place` passes; `deferred` passes while churn.json is for the series' tag and is red at another;
  * a reason of the wrong shape is red, in the band or out of it;
  * the band is the constant: change it and the same hook is judged again;
  * C18 is never debt; `check` runs it; HOOKS.json keeps the field through the export;
  * on the series as committed every hook has its churn (the reasons are the pm's: this test does not count them).

    python -m pytest tools/tests/test_quiet_anchors.py
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import churn  # noqa: E402
import engine  # noqa: E402
import hook_contract as hc  # noqa: E402
import hooks_list as hl  # noqa: E402

FOLDER = "fingerprint/x"
TAG = "FIREFOX_159_0_RELEASE"
PATCH = """diff --git a/a.cpp b/a.cpp
--- a/a.cpp
+++ b/a.cpp
@@ -1,4 +1,5 @@
 void F(int x) {
+  if (StealthX(x)) return;  // STEALTH-HOOK(fingerprint/x)
   int a = 1;
   int b = 2;
 }
"""
ONLY = {"kind": "only-place", "why": "the one statement every caller reaches"}
DEFERRED = {"kind": "deferred", "quieter": "a.cpp:int a = 1;"}


def build(tmp_path, churn_n=2, reason=None, patch=PATCH, base=TAG, tag=TAG, churn_file=True, churn_text=None):
    """A series of one folder with one hook; tools/churn.json says that hunk has churn `churn_n` (`churn_text`: the patch the file
    was written for, when it is not `patch`); `reason`: the HOOKS.json quiet_anchor_why."""
    root = tmp_path
    (root / FOLDER).mkdir(parents=True)
    (root / FOLDER / "hooks.patch").write_text(patch, encoding="utf-8", newline="")
    (root / "SERIES").write_text(FOLDER + "\n", encoding="utf-8")
    (root / "UPSTREAM.json").write_text(json.dumps({"mozilla_tag": tag}), encoding="utf-8")
    hl.write_all(root)
    if reason is not None:
        entries = json.loads((root / FOLDER / "HOOKS.json").read_text(encoding="utf-8"))
        entries[0]["quiet_anchor_why"] = reason
        (root / FOLDER / "HOOKS.json").write_text(hl.render(entries), encoding="utf-8", newline="")
    if churn_file:
        other = root.parent / (root.name + "-churn")
        (other / FOLDER).mkdir(parents=True)
        (other / FOLDER / "hooks.patch").write_text(churn_text or patch, encoding="utf-8", newline="")
        (other / "SERIES").write_text(FOLDER + "\n", encoding="utf-8")
        keys = churn.hunk_keys(other)
        hooks = [{"key": k, "folder": f, "file": p, "hunk": n, "churn": churn_n,
                  "which": ["15%d" % i for i in range(2, 2 + churn_n)]} for (f, p, n), k in sorted(keys.items())]
        data = {"base": base, "releases": [{"tag": TAG, "commit": "0" * 40}], "band": churn.BAND_MIN_CHURN, "hooks": hooks}
        (root / "tools").mkdir()
        (root / "tools" / "churn.json").write_bytes(churn.render(data))
    return root


def c18(root):
    return hc.churn_violations(root)


BAND = churn.BAND_MIN_CHURN


def test_the_fixture_is_one_hook_and_one_hunk(tmp_path):
    build(tmp_path, churn_n=0)
    assert [(h.folder, h.file, h.hunk) for h in hc.series_hooks(tmp_path)] == [(FOLDER, "a.cpp", 1)]
    assert c18(tmp_path) == []


# --------------------------------------------------------------------------- the band
def test_a_hook_in_the_band_without_a_reason_is_red(tmp_path):
    build(tmp_path, churn_n=BAND)
    (v,) = c18(tmp_path)
    assert v.rule == "C18" and (v.folder, v.file) == (FOLDER, "a.cpp")
    # where / what / fix / rule: the hook and its hunk, the churn, the field to write or the move, the decision
    assert "StealthX(x)" in v.detail and "hunk 1" in v.detail and "churn %d" % BAND in v.detail
    assert "BAND_MIN_CHURN" in v.detail and "quiet_anchor_why" in v.detail and "move the hook" in v.detail
    assert "docs/decisions/port-07-quiet-anchors.md" in v.detail


def test_a_hook_below_the_band_needs_no_reason(tmp_path):
    build(tmp_path, churn_n=BAND - 1)
    assert c18(tmp_path) == []


def test_the_band_is_the_constant_and_nothing_restates_the_number(tmp_path, monkeypatch):
    build(tmp_path, churn_n=BAND)
    assert len(c18(tmp_path)) == 1
    monkeypatch.setattr(churn, "BAND_MIN_CHURN", BAND + 1)
    assert c18(tmp_path) == []                       # the same hook, the same file: the constant decides
    monkeypatch.setattr(churn, "BAND_MIN_CHURN", BAND)
    decision = (Path(__file__).resolve().parents[2] / "docs" / "decisions" / "port-07-quiet-anchors.md").read_text(encoding="utf-8")
    assert "BAND_MIN_CHURN" in decision and "churn >= %d" % BAND not in decision and "at least %d" % BAND not in decision


def test_only_place_passes(tmp_path):
    build(tmp_path, churn_n=BAND, reason=ONLY)
    assert c18(tmp_path) == []


def test_deferred_passes_while_the_churn_file_is_for_the_tag_of_the_series(tmp_path):
    build(tmp_path, churn_n=BAND, reason=DEFERRED)
    assert c18(tmp_path) == []


def test_deferred_is_red_when_the_base_changed(tmp_path):
    # the next port: UPSTREAM.json names the new tag, churn.json is written again for it, and the hook is still where it was
    build(tmp_path, churn_n=BAND, reason=DEFERRED, base="FIREFOX_160_0_RELEASE")
    (v,) = c18(tmp_path)
    assert "deferred" in v.detail and "FIREFOX_160_0_RELEASE" in v.detail and TAG in v.detail
    assert "a.cpp:int a = 1;" in v.detail and "only-place" in v.detail and "docs/decisions/port-07-quiet-anchors.md" in v.detail


def test_only_place_survives_a_new_base(tmp_path):
    build(tmp_path, churn_n=BAND, reason=ONLY, base="FIREFOX_160_0_RELEASE")
    assert c18(tmp_path) == []


def test_a_deferred_hook_that_became_quiet_is_not_red_at_the_new_base(tmp_path):
    build(tmp_path, churn_n=0, reason=DEFERRED, base="FIREFOX_160_0_RELEASE")      # it moved: its hunk is quiet now
    assert c18(tmp_path) == []


# --------------------------------------------------------------------------- no churn
def test_a_hook_missing_from_churn_json_is_red(tmp_path):
    moved = PATCH.replace("StealthX(x)", "StealthY(x)")       # the file was written for another text: this hook is new to it
    build(tmp_path, churn_n=BAND, reason=ONLY, churn_text=moved)
    (v,) = c18(tmp_path)
    assert "a new or moved hook has no churn: run" in v.detail and "churn.py" in v.detail and "--write" in v.detail
    assert "docs/decisions/port-07-quiet-anchors.md" in v.detail


def test_a_missing_churn_json_is_red(tmp_path):
    build(tmp_path, churn_file=False)
    (v,) = c18(tmp_path)
    assert "tools/churn.json is missing" in v.detail and "churn.py" in v.detail and "--write" in v.detail


def test_a_churn_json_that_is_not_json_is_red(tmp_path):
    build(tmp_path, churn_n=0)
    (tmp_path / "tools" / "churn.json").write_text("{", encoding="utf-8")
    (v,) = c18(tmp_path)
    assert "not what tools/churn.py writes" in v.detail


def test_a_hunk_that_only_moved_keeps_its_churn(tmp_path):
    # the key has no line number: the same hunk lower in the file is the same hook
    build(tmp_path, churn_n=BAND, reason=ONLY)
    moved = PATCH.replace("@@ -1,4 +1,5 @@", "@@ -41,4 +41,5 @@")
    (tmp_path / FOLDER / "hooks.patch").write_text(moved, encoding="utf-8", newline="")
    assert c18(tmp_path) == []


# --------------------------------------------------------------------------- the shape of the field
BAD = [
    ("a string", "because"),
    ("a list", [ONLY]),
    ("no kind", {"why": "x"}),
    ("an unknown kind", {"kind": "later", "why": "x"}),
    ("only-place without why", {"kind": "only-place"}),
    ("only-place with an empty why", {"kind": "only-place", "why": "  "}),
    ("only-place with a quieter", {"kind": "only-place", "why": "x", "quieter": "a.cpp:b"}),
    ("deferred without quieter", {"kind": "deferred"}),
    ("deferred with an empty quieter", {"kind": "deferred", "quieter": ""}),
    ("deferred with a why", {"kind": "deferred", "quieter": "a.cpp:int a;", "why": "x"}),
    ("deferred with no colon", {"kind": "deferred", "quieter": "a.cpp int a;"}),
    ("deferred with no anchor text", {"kind": "deferred", "quieter": "a.cpp:  "}),
    ("deferred with no file", {"kind": "deferred", "quieter": ":int a;"}),
    ("deferred with a number", {"kind": "deferred", "quieter": 3}),
]


@pytest.mark.parametrize("name,value", BAD, ids=[n for n, _ in BAD])
def test_a_reason_of_the_wrong_shape_is_red(tmp_path, name, value):
    build(tmp_path, churn_n=BAND, reason=value)
    (v,) = c18(tmp_path)
    assert "quiet_anchor_why is wrong" in v.detail and "docs/decisions/port-07-quiet-anchors.md" in v.detail


def test_a_reason_of_the_wrong_shape_is_red_below_the_band_too(tmp_path):
    build(tmp_path, churn_n=0, reason={"kind": "someday"})
    assert [v.rule for v in c18(tmp_path)] == ["C18"]


# --------------------------------------------------------------------------- wiring
def test_c18_is_a_rule_that_is_never_debt():
    assert "C18" in hc.RULES and "C18" in hc.PORT07_RULES and "C18" in hc.NEVER_DEBT_RULES
    assert set(hc.PORT06_RULES) <= set(hc.NEVER_DEBT_RULES)
    v = hc.Violation("C18", FOLDER, "a.cpp", "", "x", hc._key("C18", FOLDER, "a.cpp", "", "x"), "d")
    assert "never debt" in hc.debt_problems([v], [hc.entry_of(v)], None)[0]
    assert hc.update_debt([], [v], init=True) == []
    again = hc.debt_problems([v], [], None)
    assert len(again) == 1 and again[0].startswith("%s/hooks.patch, a.cpp: C18" % FOLDER)


def test_hooks_list_keeps_the_field_through_the_export(tmp_path):
    build(tmp_path, churn_n=BAND, reason=ONLY)
    before = (tmp_path / FOLDER / "HOOKS.json").read_text(encoding="utf-8")
    assert "quiet_anchor_why" in before and "quiet_anchor_why" in hl.HAND_FIELDS
    hl.write_all(tmp_path)                                    # what the export does
    assert (tmp_path / FOLDER / "HOOKS.json").read_text(encoding="utf-8") == before
    assert hl.problems(tmp_path) == []
    # a hook whose text changes loses it on purpose (the identity of every hand field)
    (tmp_path / FOLDER / "hooks.patch").write_text(PATCH.replace("StealthX(x)", "StealthY(x)"), encoding="utf-8", newline="")
    hl.write_all(tmp_path)
    assert "quiet_anchor_why" not in (tmp_path / FOLDER / "HOOKS.json").read_text(encoding="utf-8")


def test_check_runs_c18(monkeypatch):
    extra = hc.Violation("C18", FOLDER, "a.cpp", "", "x", hc._key("C18", FOLDER, "a.cpp", "", "x"), "no quieter anchor named")
    monkeypatch.setattr(hc, "churn_violations", lambda root: [extra])
    found, _, _ = engine.contract_problems()
    assert any("C18" in p and "no quieter anchor named" in p for p in found)
    monkeypatch.setattr(hc, "churn_violations", lambda root: [])
    found, _, _ = engine.contract_problems()
    assert not any("C18" in p for p in found)


def test_every_hook_of_the_series_has_its_churn():
    """The committed churn.json is for this series: no hook of it is `a new or moved hook` (the reasons are another matter)."""
    missing = [v for v in hc.churn_violations(engine.ROOT) if "has no churn" in v.detail]
    assert missing == [], [(v.folder, v.file, v.text[:60]) for v in missing[:5]]
