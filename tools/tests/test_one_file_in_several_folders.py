"""series-01: a Mozilla file several folders patch. `export` gives each folder the lines its marker names (tools/split.py), and everything that
reads the series has to cope with one path in the hooks.patch and the MANIFEST of several folders.

The source is a tiny repository (a tag and a head) with one file two folders touch: a hunk that mixes both markers, a rewrite with one
marker and a hook of the first folder further down. The folders are `network/b` and `fingerprint/a`, applied in that order (SERIES order).
The tests export it into a throwaway series and show, on that series:

  * each folder's hooks.patch holds its lines only, and has the form of `git diff --binary --full-index --no-renames`;
  * `build_stack` and `verify` give the head's tree byte for byte;
  * the MANIFEST lists the path in both folders, the inventory has one record per (file, folder) and the counts of each are its part's;
  * the budgets are per (file, folder);
  * `drift` names both folders and `port` onto a tag that changes the second folder's line stops naming that folder and no other;
  * a line no folder owns stops the export before it writes anything, with the failure and a `next:` line.

    python -m pytest tools/tests/test_one_file_in_several_folders.py
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402
import layout  # noqa: E402
from seed_inventory import seed_inventory, set_inventory  # noqa: E402
from test_apply_builds_the_layer_stack import run  # noqa: E402

A, B = "fingerprint/a", "network/b"
FILE = "mozilla.txt"
BASE = "".join("int v%d;\n" % n for n in range(1, 31))
LINES = BASE.splitlines(keepends=True)
LINES[LINES.index("int v20;\n") + 1:LINES.index("int v20;\n") + 1] = ["B2();  // STEALTH-HOOK(network/b)\n"]
LINES[LINES.index("int v10;\n")] = "int v10 = A2();  // STEALTH-HOOK(fingerprint/a)\n"
LINES[2:2] = ["A1();  // STEALTH-HOOK(fingerprint/a)\n", "B1();  // STEALTH-HOOK(network/b)\n"]
HEAD = "".join(LINES)
RECORD = {"file": FILE, "category": "spoof", "feature": "fa", "prefs": ["a.pref"], "added": 0, "removed": 0, "hunks": 0, "inline_logic_lines": 4,
          "hookable": "movable", "anchor": "by hand: the anchor", "notes": "by hand: the notes", "verifier": {"changed": [], "why": "kept"}}


def commit(src, text, message):
    (src / FILE).write_bytes(text.encode())
    run(src, "commit", "-qam", message)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """-> (source repository, series root). The source has the tag TAG and the branch `head`; the series is empty and every file export writes
    outside it is a copy."""
    src = tmp_path / "firefox"
    src.mkdir()
    run(src, "init", "-q")
    run(src, "config", "core.autocrlf", "false")
    (src / FILE).write_bytes(BASE.encode())
    run(src, "add", ".")
    run(src, "commit", "-qm", "upstream")
    run(src, "tag", "TAG")
    run(src, "checkout", "-q", "-B", "head")
    commit(src, HEAD, "both folders' lines")
    series = tmp_path / "engine"
    series.mkdir()
    (series / "SERIES").write_text("", encoding="utf-8")
    budget, removed = tmp_path / "hook-budget.json", tmp_path / "removed-budget.json"
    budget.write_text(json.dumps({FILE: 9}), encoding="utf-8")         # the old budget, per file, with a slack of 2
    removed.write_text(json.dumps({FILE: 3}), encoding="utf-8")
    upstream = tmp_path / "UPSTREAM.json"
    upstream.write_text(json.dumps({"mozilla_tag": "TAG", "source_branch": "head"}), encoding="utf-8")
    for name, value in (("ROOT", series), ("BUDGET", budget), ("REMOVED_BUDGET", removed), ("UPSTREAM", upstream),
                        ("WORKFLOWS_SERIES", tmp_path / "wf-series"), ("WORKFLOWS_ROOT", tmp_path / "wf-root")):
        monkeypatch.setattr(engine, name, value)
    monkeypatch.setattr(layout, "FEATURES", {"fa": A, "nb": B})
    seed_inventory(series, [RECORD])
    return src, series


def export(world, head="head", **kw):
    src, _series = world
    engine.export(src, "TAG", head, **kw)


def patch_of(series, folder):
    return (series / folder / "hooks.patch").read_text(encoding="utf-8")


def manifest_of(series, folder):
    return json.loads((series / folder / "MANIFEST.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ the folders' patches

def test_each_folder_holds_its_lines_and_the_series_is_in_series_order(world):
    src, series = world
    export(world)
    assert (series / "SERIES").read_text(encoding="utf-8").split() == [B, A]
    first, second = patch_of(series, B), patch_of(series, A)
    assert "+B1();" in first and "+B2();" in first and "A1()" not in first and "A2()" not in first
    assert "+A1();" in second and "-int v10;" in second and "+int v10 = A2();" in second and "B2()" not in second
    assert " B1();  // STEALTH-HOOK(network/b)" in second, "the first folder's line is the context of the second's hunk"
    # the form export always had: git diff of two trees, a/<path> b/<path>, the index line
    assert first.startswith("diff --git a/mozilla.txt b/mozilla.txt\nindex ") and second.startswith("diff --git a/mozilla.txt b/mozilla.txt\nindex ")


def test_the_manifest_lists_the_path_in_both_folders(world):
    src, series = world
    export(world)
    assert manifest_of(series, B)["modified"] == [FILE] and manifest_of(series, A)["modified"] == [FILE]


def test_build_stack_and_verify_give_the_head_tree(world, capsys):
    src, series = world
    export(world)
    layers = engine.build_stack(src, "TAG")
    assert [folder for folder, _commit, _tree in layers] == [None, B, A]
    assert layers[-1][2] == run(src, "rev-parse", "head^{tree}")
    assert engine.verify(src, "TAG", "head") == 0 and "identical" in capsys.readouterr().out
    assert run(src, "show", "%s:%s" % (layers[-1][1], FILE)) == HEAD.rstrip("\n")


def test_a_second_export_of_the_same_head_changes_nothing(world):
    src, series = world
    export(world)
    before = {p.relative_to(series).as_posix(): p.read_bytes() for p in series.rglob("*") if p.is_file()}
    export(world)
    assert {p.relative_to(series).as_posix(): p.read_bytes() for p in series.rglob("*") if p.is_file()} == before


def test_a_folder_whose_lines_are_all_gone_is_removed(world, capsys):
    src, series = world
    export(world)
    commit(src, HEAD.replace("B1();  // STEALTH-HOOK(network/b)\n", "").replace("B2();  // STEALTH-HOOK(network/b)\n", ""), "B's lines go")
    export(world)
    assert not (series / B).exists() and "removed network/b" in capsys.readouterr().out
    assert (series / "SERIES").read_text(encoding="utf-8").split() == [A]
    assert engine.verify(src, "TAG", "head") == 0


# ------------------------------------------------------------------------------------------------ the inventory

def test_the_inventory_has_one_record_per_file_and_folder(world):
    src, series = world
    export(world)
    records = engine.inventory_records()
    assert [(r["file"], layout.feature_folder(r["feature"])) for r in records] == [(FILE, B), (FILE, A)]
    born, kept = records
    # the record of the folder that held the file keeps every hand field and takes the counts of its part
    assert (kept["anchor"], kept["notes"], kept["prefs"], kept["verifier"], kept["hookable"]) == (
        "by hand: the anchor", "by hand: the notes", ["a.pref"], {"changed": [], "why": "kept"}, "movable")
    assert (kept["added"], kept["removed"], kept["hunks"]) == (2, 1, 2)
    # a new record: counts of its part, the file's category, the folder's feature, and the empty text a hand writes
    assert (born["added"], born["removed"], born["hunks"]) == (2, 0, 2)
    assert born["category"] == "spoof" and born["feature"] == "nb" and born["hookable"] == "already-hook"
    assert born["anchor"] == "" and born["notes"] == "" and "verifier" not in born
    assert manifest_of(series, A)["inventory"] == [kept] and manifest_of(series, B)["inventory"] == [born]
    assert engine.record_count_problems(records, engine.folder_diffs()) == []


def test_check_refuses_the_empty_text_of_a_derived_record_and_says_where_what_how_and_which_rule(world):
    export(world)
    found = engine.inventory_hand_problems(engine.inventory_records(), engine.folder_diffs())
    assert len(found) == 2 and all(f.startswith("FAIL network/b/MANIFEST.json, the record of mozilla.txt in network/b: its `") for f in found), found
    assert "its `anchor` is empty" in found[0] and "its `notes` is empty" in found[1]
    assert all(". Fix: write `" in f and ". Rule: docs/decisions/repo-07-one-fact-one-place.md" in f for f in found)


def test_an_empty_anchor_is_red_through_problems_and_check_not_only_the_cli(world, capsys):
    export(world)
    mine = "network/b/MANIFEST.json, the record of mozilla.txt in network/b: its `%s` is empty"
    found = engine.problems()
    assert [f for f in found if mine % "anchor" in f] and [f for f in found if mine % "notes" in f], found
    assert engine.check() != 0 and mine % "anchor" in capsys.readouterr().out
    records = engine.inventory_records()
    for r in records:
        if layout.feature_folder(r["feature"]) == B:
            r["anchor"], r["notes"] = "by hand: the anchor", "by hand: the notes"
    set_inventory(engine.ROOT, records)
    assert not [f for f in engine.problems() if "its `anchor` is empty" in f or "its `notes` is empty" in f]


# ------------------------------------------------------------------------------------------------ the inventory has one place

def red(found, where, what):
    return [f for f in found if f.startswith("FAIL " + where) and what in f]


def test_the_inventory_lives_in_the_manifests_of_the_folders_and_nowhere_else(world):
    src, series = world
    export(world)
    assert not (series / "tools" / "inventory.json").exists()
    assert engine.inventory_records() == manifest_of(series, B)["inventory"] + manifest_of(series, A)["inventory"], "the folders in SERIES order"
    assert not red(engine.problems(), "tools/inventory.json", "the file exists")


def test_a_tools_inventory_json_that_reappears_is_red_and_says_where_what_how_and_which_rule(world):
    src, series = world
    export(world)
    (series / "tools").mkdir(exist_ok=True)
    (series / "tools" / "inventory.json").write_text(json.dumps(engine.inventory_records()), encoding="utf-8")
    (found,) = red(engine.problems(), "tools/inventory.json", "the file exists")
    assert "delete tools/inventory.json: the inventory lives in each folder's MANIFEST.json" in found
    assert found.endswith("Rule: docs/decisions/repo-07-one-fact-one-place.md"), found
    assert engine.check() != 0


def test_a_record_in_the_manifest_of_another_folder_is_red(world):
    src, series = world
    export(world)
    stray = manifest_of(series, A)["inventory"][0]
    other = manifest_of(series, B)
    other["inventory"].append(stray)
    engine.write_json(series / B / "MANIFEST.json", other)
    (found,) = red(engine.problems(), "%s/MANIFEST.json" % B, "belongs to the folder %s, not to this one" % A)
    assert "move the record to the `inventory` of the MANIFEST.json of the folder its feature maps to" in found


def test_a_computed_field_edited_by_hand_in_a_manifest_is_red_and_names_export(world):
    """The computed fields (added, removed, hunks, inline_logic_lines) of a record are the hooks.patch's; the record is in the MANIFEST only."""
    src, series = world
    export(world)
    manifest = manifest_of(series, A)
    manifest["inventory"][0]["added"] = 99
    engine.write_json(series / A / "MANIFEST.json", manifest)
    (found,) = red(engine.problems(), "%s/MANIFEST.json" % A, "the record of mozilla.txt in %s says added 99" % A)
    assert "python tools/engine.py export" in found and found.endswith("Rule: docs/decisions/series-01-export-is-the-only-writer.md"), found


def test_export_keeps_the_hand_fields_of_the_manifest_record_and_a_hand_edit_of_them_is_the_authors(world):
    src, series = world
    export(world)
    manifest = manifest_of(series, A)
    manifest["inventory"][0]["notes"] = "by hand, again"
    engine.write_json(series / A / "MANIFEST.json", manifest)
    export(world)
    assert manifest_of(series, A)["inventory"][0]["notes"] == "by hand, again"


def test_a_stale_inline_logic_lines_is_red_and_export_writes_it_for_every_record(world):
    export(world)
    records = engine.inventory_records()
    patches = {B: (world[1] / B / "hooks.patch").read_bytes(), A: (world[1] / A / "hooks.patch").read_bytes()}
    assert [r["inline_logic_lines"] for r in records] == [engine.inline_logic_of(layout.feature_folder(r["feature"]), patches[layout.feature_folder(r["feature"])], FILE) for r in records]
    records[0]["inline_logic_lines"] = 99
    set_inventory(engine.ROOT, records)
    found = [f for f in engine.problems() if "inline_logic_lines" in f]
    assert len(found) == 1 and "the record of mozilla.txt in network/b says inline_logic_lines 99" in found[0], found
    assert ". Fix: do not edit inline_logic_lines: `" in found[0] and "export" in found[0] and ". Rule: docs/decisions/repo-06-" in found[0]
    export(world)
    assert not [f for f in engine.problems() if "inline_logic_lines" in f]


def test_export_writes_inline_logic_lines_of_a_record_whose_file_is_not_split(world):
    src, series = world
    export(world)
    records = engine.inventory_records()
    for r in records:
        r["inline_logic_lines"] = 77
    set_inventory(engine.ROOT, records)
    run(src, "checkout", "-q", "-B", "only-b", "TAG")
    commit(src, BASE.replace("int v5;\n", "int v5;\nB3();  // STEALTH-HOOK(network/b)\n"), "only B")
    export(world, "only-b")
    (record,) = engine.inventory_records()
    assert record["inline_logic_lines"] == engine.inline_logic_of(B, (series / B / "hooks.patch").read_bytes(), FILE) != 77


def test_a_record_whose_folder_owns_no_line_any_more_moves_with_its_hand_text_to_the_folder_that_does(world, capsys):
    src, series = world
    run(src, "checkout", "-q", "-B", "only-b", "TAG")
    only_b = BASE.replace("int v5;\n", "int v5;\nB3();  // STEALTH-HOOK(network/b)\n")
    commit(src, only_b, "only B")
    export(world, "only-b")
    records = engine.inventory_records()
    assert [(r["file"], layout.feature_folder(r["feature"])) for r in records] == [(FILE, B)]
    assert records[0]["anchor"] == "by hand: the anchor" and records[0]["notes"] == "by hand: the notes" and records[0]["feature"] == "nb"
    assert "the record of mozilla.txt moved from fingerprint/a to network/b" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ the budgets

def test_the_budgets_are_per_file_and_folder_at_the_counted_value_and_the_slack_is_said(world, capsys):
    src, series = world
    export(world)
    assert json.loads(engine.BUDGET.read_text(encoding="utf-8")) == {"mozilla.txt|fingerprint/a": 2, "mozilla.txt|network/b": 2}
    assert json.loads(engine.REMOVED_BUDGET.read_text(encoding="utf-8")) == {"mozilla.txt|fingerprint/a": 1}
    out = capsys.readouterr().out
    assert "budget slack removed, hook budget of mozilla.txt: 5" in out and "budget slack removed, removed budget of mozilla.txt: 2" in out
    export(world)
    assert "slack" not in capsys.readouterr().out, "the conversion is once"


def test_the_checks_of_the_series_pass_on_what_export_wrote_but_the_text_of_the_new_record(world, monkeypatch):
    export(world)
    found = engine.problems()
    assert not [p for p in found if "is empty" not in p and ("budget" in p or "hooks.patch" in p or "patched by" in p)], found


# ------------------------------------------------------------------------------------------------ the reds

def test_a_line_no_folder_owns_stops_the_export_before_it_writes_anything_and_ends_with_next(world):
    src, series = world
    commit(src, HEAD.replace("int v25;\n", "int v25;\nunmarked();\n"), "an unmarked change")
    with pytest.raises(SystemExit) as stop:
        export(world)
    text = stop.value.code
    assert text.startswith("FAIL mozilla.txt:") and "untagged change" in text and "Rule: docs/decisions/series-01" in text
    assert text.strip().splitlines()[-1] == "next: python tools/engine.py export --source <source> --head head"
    assert not list(series.glob("*/**/hooks.patch")) and (series / "SERIES").read_text(encoding="utf-8") == ""


def test_a_marker_naming_no_folder_stops_the_export(world):
    src, series = world
    commit(src, HEAD.replace("int v25;\n", "int v25;\nC1();  // STEALTH-HOOK(network/nowhere)\n"), "a marker of nobody")
    with pytest.raises(SystemExit) as stop:
        export(world)
    assert "the marker names network/nowhere, which is not a folder of the series" in stop.value.code
    assert stop.value.code.strip().splitlines()[-1].startswith("next: python tools/engine.py export")


def test_a_file_of_category_backport_stays_whole_in_the_folder_of_its_inventory_feature(world):
    src, series = world
    set_inventory(series, [dict(RECORD, category="backport", feature="nb")])
    export(world)
    assert (series / B / "hooks.patch").is_file() and not (series / A / "hooks.patch").exists()
    assert "+A1();" in patch_of(series, B) and "+B1();" in patch_of(series, B)
    assert engine.verify(src, "TAG", "head") == 0


# ------------------------------------------------------------------------------------------------ drift and port

def new_tag(src, name, text):
    run(src, "checkout", "-q", "-B", "up-" + name, "TAG")
    commit(src, text, "upstream " + name)
    run(src, "tag", name)


def test_drift_names_each_folder_that_patches_a_file_mozilla_changed(world, capsys):
    src, series = world
    export(world)
    new_tag(src, "NEW", BASE.replace("int v25;\n", "int v25 = 1;\n"))
    engine.drift(src, "TAG", "NEW")
    out = capsys.readouterr().out
    assert "changed mozilla.txt (network/b, fingerprint/a)" in out and "1 of our 1 patched Mozilla files changed" in out


def test_a_port_onto_a_tag_that_changes_the_second_folders_line_stops_naming_that_folder_only(world, capsys):
    src, series = world
    export(world)
    new_tag(src, "NEW", BASE.replace("int v10;\n", "int v10 = 1;\n"))          # the line fingerprint/a rewrites
    assert engine.port(src, "TAG", "NEW", "port/NEW", force=False) == 1
    out = capsys.readouterr().out
    assert "CONFLICT fingerprint/a: mozilla.txt" in out and "CONFLICT network/b" not in out, out
    assert run(src, "log", "--format=%s", "NEW..port/NEW").splitlines() == ["fingerprint/a (CONFLICT: mozilla.txt)", "network/b"]


def test_a_port_onto_a_tag_that_changes_the_first_folders_line_names_the_first_folder(world, capsys):
    src, series = world
    export(world)
    new_tag(src, "NEW", BASE.replace("int v21;\n", "int v21 = 2;\n"))          # the line B2 is inserted before
    assert engine.port(src, "TAG", "NEW", "port/NEW", force=False) == 1
    out = capsys.readouterr().out
    assert "CONFLICT network/b: mozilla.txt" in out, out
    assert "CONFLICT fingerprint/a" not in out


def test_a_port_onto_a_tag_that_changes_no_line_of_ours_merges_cleanly_for_both(world):
    src, series = world
    export(world)
    new_tag(src, "NEW", BASE.replace("int v28;\n", "int v28 = 1;\n"))
    assert engine.port(src, "TAG", "NEW", "port/NEW", force=False) == 0
    text = run(src, "show", "port/NEW:" + FILE)
    assert "A1();" in text and "B2();" in text and "int v28 = 1;" in text and "<<<<<<<" not in text
