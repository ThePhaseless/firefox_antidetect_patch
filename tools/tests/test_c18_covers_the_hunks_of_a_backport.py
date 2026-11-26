"""Rule C18 (port-07) sees every hunk tools/churn.json has a row for, a backport folder's included.

churn.py --check (the `churn` job of a pull request) recomputes every hunk of every hooks.patch and compares the bytes, so a backport
folder's hunk with no row is red there. `check` judged hooks only, and a backport folder has none: the red came from the job, after the
push (PR 78: the Glean backport of port-06 had no rows). It is now red in `check`, and so in the export gate, before any pull request.

    python -m pytest tools/tests/test_c18_covers_the_hunks_of_a_backport.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import churn  # noqa: E402
import hook_contract as hc  # noqa: E402
from test_quiet_anchors import FOLDER, build  # noqa: E402

BACKPORT = "platform/backports/a-crate-fix"
CRATE_PATCH = """diff --git a/third_party/rust/c/src/lib.rs b/third_party/rust/c/src/lib.rs
--- a/third_party/rust/c/src/lib.rs
+++ b/third_party/rust/c/src/lib.rs
@@ -1,3 +1,4 @@
 pub fn a() {}
+pub fn b() {}
 pub fn c() {}
 pub fn d() {}
"""


def with_backport(tmp_path, rows_for_it: bool):
    """The one-hook series of test_quiet_anchors, plus a backport folder whose hunk has (or has not) a row in tools/churn.json."""
    root = build(tmp_path, churn_n=0)
    (root / BACKPORT).mkdir(parents=True)
    (root / BACKPORT / "hooks.patch").write_text(CRATE_PATCH, encoding="utf-8", newline="")
    (root / BACKPORT / "BACKPORT.json").write_text("{}", encoding="utf-8")
    (root / "SERIES").write_text("%s\n%s\n" % (FOLDER, BACKPORT), encoding="utf-8")
    if rows_for_it:
        data = json.loads((root / "tools" / "churn.json").read_text(encoding="utf-8"))
        for (folder, path, no), key in sorted(churn.hunk_keys(root).items()):
            if folder == BACKPORT:
                data["hooks"].append({"key": key, "folder": folder, "file": path, "hunk": no, "churn": 0, "which": []})
        (root / "tools" / "churn.json").write_bytes(churn.render(data))
    return root


def test_a_backport_hunk_without_a_row_is_red(tmp_path):
    root = with_backport(tmp_path, rows_for_it=False)
    (v,) = hc.churn_violations(root)
    assert v.rule == "C18" and (v.folder, v.file) == (BACKPORT, "third_party/rust/c/src/lib.rs")
    text = str(v.failure) if getattr(v, "failure", None) is not None else v.detail       # the failure carries the fix and the rule (repo-04)
    assert "hunk 1" in text and "no churn row in tools/churn.json" in text and "churn.py" in text
    assert "docs/decisions/port-07-quiet-anchors.md" in text


def test_a_backport_hunk_with_its_row_is_green(tmp_path):
    assert hc.churn_violations(with_backport(tmp_path, rows_for_it=True)) == []


def test_the_backport_hunk_is_one_of_the_hunks_churn_py_keys(tmp_path):
    root = with_backport(tmp_path, rows_for_it=False)
    assert (BACKPORT, "third_party/rust/c/src/lib.rs", 1) in churn.hunk_keys(root), "the same hunks churn.py --check recomputes"
