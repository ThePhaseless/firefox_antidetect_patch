"""repo-06 (docs/decisions/repo-06-what-a-tool-can-write-a-tool-writes.md): a derived fact is written by a tool, and `check` refuses a hand-written
one that differs from what the tool computes, naming the command that writes it.

  * the inventory counts of a record (and no evidence field, repo-07): `export` writes them from the folder's hooks.patch;
  * the budget entry of a Mozilla file the series patches for the first time: `export` writes it at the counted value;
  * the sha256 of every file under a folder's src/: `export` writes it in the folder's MANIFEST.json;
  * the owner of a file of ours: the folder that holds it under src/, no table in tools/layout.py;
  * tools/gtest-suites.json: `gtest-list --write` writes it from the HOOKS.json files.

Each is shown red on the code before the change: the old message did not name the command, the old export wrote none of them, and
layout.OWN_FILES was a hand table.

    python -m pytest -q tools/tests/test_series_writes_what_it_computes.py
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402
import gtest_list  # noqa: E402
import layout  # noqa: E402
from seed_inventory import seed_inventory  # noqa: E402
from test_apply_builds_the_layer_stack import run, world  # noqa: E402,F401

EXPORT = "python tools/engine.py export"
GTEST_LIST = "python tools/engine.py gtest-list --write"


# ---------------------------------------------------------------------------------------------------------------------------- counts
DIFF = ("diff --git a/a.cpp b/a.cpp\n--- a/a.cpp\n+++ b/a.cpp\n@@ -1,2 +1,3 @@\n keep\n-old\n+new  // STEALTH-HOOK(platform/f)\n+\n"
        "@@ -9,1 +10,2 @@\n z\n+more  // STEALTH-HOOK(platform/f)\n")


def test_file_diffs_counts_the_lines_of_the_hunks_and_quotes_none():
    d = engine.file_diffs(DIFF)["a.cpp"]
    assert d == {"added": 3, "removed": 1, "hunks": 2}


def test_the_record_keeps_its_hand_fields_and_takes_the_three_computed_ones_and_drops_evidence():
    record = {"file": "a.cpp", "category": "hook", "feature": "x", "added": 99, "removed": 99, "hunks": 99, "evidence": ["+stale"], "notes": "mine",
              "verifier": {"why": "checked"}, "anchor": "a", "hookable": "yes"}
    fresh = engine.computed_record(record, engine.file_diffs(DIFF)["a.cpp"])
    assert (fresh["added"], fresh["removed"], fresh["hunks"]) == (3, 1, 2) and "evidence" not in fresh
    assert (fresh["notes"], fresh["verifier"], fresh["anchor"], fresh["feature"]) == ("mine", {"why": "checked"}, "a", "x")
    assert list(fresh)[:5] == ["file", "category", "feature", "added", "removed"], "keys keep the order of the inventory"


def test_a_count_edited_by_hand_fails_and_the_message_names_export():
    diffs = engine.file_diffs(DIFF)
    good = engine.computed_record({"file": "a.cpp", "category": "hook"}, diffs["a.cpp"])
    assert engine.record_count_problems([good], diffs) == []
    for field, value in (("added", 2), ("removed", 0), ("hunks", 1)):
        found = engine.record_count_problems([dict(good, **{field: value})], diffs)
        assert len(found) == 1 and "a.cpp" in found[0] and EXPORT in found[0], found
        assert "Rule: docs/decisions/series-01" in found[0]


def test_an_evidence_field_fails_and_the_message_says_where_the_fix_and_the_rule():
    diffs = engine.file_diffs(DIFF)
    good = engine.computed_record({"file": "a.cpp", "category": "hook"}, diffs["a.cpp"])
    found = engine.evidence_problems("x/z/MANIFEST.json", [dict(good, evidence=["-old"])])
    assert len(found) == 1 and "a.cpp" in found[0] and "evidence" in found[0] and "delete the field" in found[0], found
    assert "Rule: docs/decisions/repo-07-one-fact-one-place.md" in found[0], found
    # the same record inside a MANIFEST.json is refused with its own where
    found = engine.evidence_problems("x/y/MANIFEST.json", [dict(good, evidence=[])])
    assert len(found) == 1 and "x/y/MANIFEST.json" in found[0], found


def test_every_record_as_committed_is_what_export_writes():
    records = engine.inventory_records()
    diffs = {}
    for folder in engine.existing_folders():
        patch = engine.ROOT / folder / "hooks.patch"
        if patch.exists():
            diffs.update({(path, folder): d for path, d in engine._diffs_of(patch).items()})
    assert engine.record_count_problems(records, diffs) == []
    assert records and not any("evidence" in r for r in records), "the lines are the hooks.patch itself"


# ------------------------------------------------------------------------------------------------------ export writes the new things
@pytest.fixture
def exported(world, tmp_path, monkeypatch):
    """The two-file repository with its series in a throwaway directory; every file export writes outside the series is a copy."""
    root = engine.ROOT
    budget, removed = tmp_path / "hook-budget.json", tmp_path / "removed-budget.json"
    budget.write_text("{}\n", encoding="utf-8")
    removed.write_text("{}\n", encoding="utf-8")
    upstream = tmp_path / "UPSTREAM.json"
    upstream.write_text(json.dumps({"mozilla_tag": "TAG", "source_branch": "series"}), encoding="utf-8")
    for name, value in (("BUDGET", budget), ("REMOVED_BUDGET", removed), ("UPSTREAM", upstream),
                        ("WORKFLOWS_SERIES", tmp_path / "wf-series"), ("WORKFLOWS_ROOT", tmp_path / "wf-root")):
        monkeypatch.setattr(engine, name, value)
    monkeypatch.setattr(layout, "feature_folder", lambda feature: "fingerprint/a")
    monkeypatch.setattr(layout, "GROUP_ORDER", ["platform", "fingerprint", "port"])
    run(world, "checkout", "-q", "-B", "work", "TAG")
    engine.apply(world, "TAG", "series", force=False)
    seed_inventory(root, [{"file": "mozilla.txt", "feature": "x", "category": "hook", "hookable": "yes", "notes": "mine"}])
    return world, root, None, budget, removed


def test_export_writes_the_budget_of_a_file_new_to_the_series_and_leaves_the_others(exported):
    world, root, inventory, budget, removed = exported
    budget.write_text(json.dumps({"other.txt": 4}), encoding="utf-8")       # an entry that is there is not touched
    engine.export(world, "TAG", "series")
    assert json.loads(budget.read_text(encoding="utf-8")) == {"mozilla.txt|fingerprint/a": 1, "other.txt": 4}
    assert json.loads(removed.read_text(encoding="utf-8")) == {}, "nothing of Mozilla's is removed: no entry"
    budget.write_text(json.dumps({"mozilla.txt|fingerprint/a": 3}), encoding="utf-8")     # a budget above the count stays: shrink-budget lowers it
    engine.export(world, "TAG", "series")
    assert json.loads(budget.read_text(encoding="utf-8")) == {"mozilla.txt|fingerprint/a": 3}


def test_export_writes_the_removed_budget_of_a_new_file_that_loses_mozillas_lines(exported):
    world, root, inventory, budget, removed = exported
    run(world, "checkout", "-q", "-B", "more", "series")
    (world / "mozilla.txt").write_bytes(b"one\nhook(); // STEALTH-HOOK(fingerprint/a)\nTWO // STEALTH-HOOK(fingerprint/a)\n")
    run(world, "commit", "-qam", "rewrites a line of Mozilla's")
    engine.export(world, "TAG", "more")
    assert json.loads(removed.read_text(encoding="utf-8")) == {"mozilla.txt|fingerprint/a": 1}
    assert json.loads(budget.read_text(encoding="utf-8")) == {"mozilla.txt|fingerprint/a": 2}


def test_export_writes_the_counts_of_the_record_and_keeps_the_hand_fields(exported):
    world, root, inventory, budget, removed = exported
    engine.export(world, "TAG", "series")
    (record,) = engine.inventory_records()
    assert (record["added"], record["removed"], record["hunks"]) == (1, 0, 1) and "evidence" not in record
    assert record["notes"] == "mine" and record["feature"] == "x"
    manifest = json.loads((root / "fingerprint" / "a" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["inventory"] == [record], "the manifest quotes the record export wrote"


def test_export_records_the_sha256_of_every_file_under_src(exported):
    world, root, inventory, budget, removed = exported
    engine.export(world, "TAG", "series")
    manifest = json.loads((root / "fingerprint" / "a" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["added"] == {"dom/StealthA.cpp": "100644"}, "`added` stays path -> mode: what reads the modes needs no change"
    assert manifest["sha256"] == {"dom/StealthA.cpp": hashlib.sha256(b"// ours\n").hexdigest()}
    other = json.loads((root / "platform" / "b" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert other["sha256"] == {"tool.py": hashlib.sha256(b"print(1)\n").hexdigest()}


# ------------------------------------------------------------------------------------------------------------------ the sha256 checks
def _with_manifest(tmp_path, manifest, files):
    d = tmp_path / "platform" / "f"
    (d / "src").mkdir(parents=True)
    for rel, data in files.items():
        (d / "src" / rel).write_bytes(data)
    return d


def test_a_manifest_without_the_sha256_of_a_file_it_adds_fails_naming_export(tmp_path):
    d = _with_manifest(tmp_path, None, {"a.py": b"x\n"})
    found = engine.manifest_hash_problems("platform/f", d, {"added": {"a.py": "100644"}, "modified": []})
    assert len(found) == 1 and "no `sha256` map" in found[0] and EXPORT in found[0], found
    found = engine.manifest_hash_problems("platform/f", d, {"added": {"a.py": "100644"}, "modified": [], "sha256": {}})
    assert len(found) == 1 and "no sha256 for a.py" in found[0] and EXPORT in found[0], found


def test_a_file_whose_bytes_are_not_the_recorded_ones_fails_and_a_stale_hash_fails(tmp_path):
    d = _with_manifest(tmp_path, None, {"a.py": b"x\n"})
    good = {"added": {"a.py": "100644"}, "modified": [], "sha256": {"a.py": hashlib.sha256(b"x\n").hexdigest()}}
    assert engine.manifest_hash_problems("platform/f", d, good) == []
    (d / "src" / "a.py").write_bytes(b"y\n")
    found = engine.manifest_hash_problems("platform/f", d, good)
    assert len(found) == 1 and "platform/f/src/a.py" in found[0] and EXPORT in found[0], found
    stale = dict(good, sha256={**good["sha256"], "gone.py": "0" * 64})
    (d / "src" / "a.py").write_bytes(b"x\n")
    found = engine.manifest_hash_problems("platform/f", d, stale)
    assert len(found) == 1 and "gone.py" in found[0], found


def test_a_folder_that_adds_nothing_needs_no_sha256(tmp_path):
    assert engine.manifest_hash_problems("platform/f", tmp_path, {"added": {}, "modified": []}) == []


def test_every_manifest_as_committed_has_the_sha256_of_its_files():
    found = []
    for folder in engine.existing_folders():
        d = engine.ROOT / folder
        found += engine.manifest_hash_problems(folder, d, json.loads((d / "MANIFEST.json").read_text(encoding="utf-8")))
    assert found == []


def test_check_reports_the_sha256_problems_of_every_folder(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "manifest_hash_problems", lambda folder, d, manifest: seen.append(folder) or [])
    assert engine.problems() == []
    assert seen == engine.existing_folders(), "problems() asks about every folder of the series"


# ------------------------------------------------------------------------------------------------------------------- OWN_FILES derived
def test_there_is_no_table_of_the_owners_of_our_files():
    assert not hasattr(layout, "OWN_FILES"), "a table of the same fact as src/ is a second writer"


def test_a_file_under_src_belongs_to_its_folder_with_no_table_entry(tmp_path):
    for folder, rel in (("fingerprint/x/y", "dom/base/StealthNeverHeardOf.cpp"), ("platform/z", "scripts/new/thing.py")):
        d = tmp_path / folder
        (d / "src" / Path(rel).parent).mkdir(parents=True)
        (d / "src" / rel).write_bytes(b"x\n")
        (d / "MANIFEST.json").write_text("{}", encoding="utf-8")
    held, twice = layout.src_owners(tmp_path)
    assert held == {"dom/base/StealthNeverHeardOf.cpp": "fingerprint/x/y", "scripts/new/thing.py": "platform/z"} and twice == []
    assert layout.own_file_folder("scripts/new/thing.py", held) == "platform/z"


def test_every_file_of_ours_in_the_series_has_the_folder_that_holds_it():
    held, twice = layout.src_owners(engine.ROOT)
    assert twice == [] and len(held) > 700
    for path, folder in list(held.items())[:20]:
        assert (engine.ROOT / folder / "src" / path).is_file()
        assert layout.own_file_folder(path, held) == folder


def test_a_file_that_no_folder_holds_stops_and_says_how_to_place_it():
    with pytest.raises(KeyError) as stop:
        layout.own_file_folder("dom/base/StealthNew.cpp", {})
    text = stop.value.args[0]
    assert "dom/base/StealthNew.cpp" in text and "--own dom/base/StealthNew.cpp=<folder>" in text and "Rule: docs/decisions/series-01" in text


def test_own_places_a_new_file_by_path_or_by_directory_and_the_longest_wins():
    declared = {"dom/": "fingerprint/a", "dom/special/": "fingerprint/b", "dom/one.cpp": "fingerprint/c"}
    assert layout.own_file_folder("dom/x.cpp", {}, declared) == "fingerprint/a"
    assert layout.own_file_folder("dom/special/x.cpp", {}, declared) == "fingerprint/b"
    assert layout.own_file_folder("dom/one.cpp", {}, declared) == "fingerprint/c"
    assert layout.own_file_folder("dom/one.cpp", {"dom/one.cpp": "platform/old"}, {"dom/one.cpp": "fingerprint/c"}) == "fingerprint/c", "a move"


def test_a_path_under_the_src_of_two_folders_is_a_failure_of_check(tmp_path, monkeypatch):
    for folder in ("platform/f", "platform/g"):
        d = tmp_path / folder
        (d / "src").mkdir(parents=True)
        (d / "src" / "same.py").write_bytes(b"x\n")
        (d / "MANIFEST.json").write_text("{}", encoding="utf-8")
    held, twice = layout.src_owners(tmp_path)
    assert twice == [("same.py", "platform/f", "platform/g")] and held == {"same.py": "platform/f"}


def test_export_places_a_new_file_with_own_and_keeps_it_there_without(exported):
    world, root, inventory, budget, removed = exported
    engine.export(world, "TAG", "series")
    run(world, "checkout", "-q", "-B", "more", "series")
    (world / "dom").mkdir(exist_ok=True)
    (world / "dom" / "StealthB.cpp").write_bytes(b"// new\n")
    run(world, "add", ".")
    run(world, "commit", "-qm", "a new file of ours")
    with pytest.raises(SystemExit) as stop:
        engine.export(world, "TAG", "more")
    text = stop.value.code
    assert "dom/StealthB.cpp" in text and "--own" in text
    last = text.strip().splitlines()[-1]
    assert last.startswith("next: python tools/engine.py export") and "--own dom/StealthB.cpp=<folder>" in last
    engine.export(world, "TAG", "more", {"dom/StealthB.cpp": "fingerprint/a"})
    assert (root / "fingerprint" / "a" / "src" / "dom" / "StealthB.cpp").read_bytes() == b"// new\n"
    manifest = json.loads((root / "fingerprint" / "a" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert set(manifest["added"]) == {"dom/StealthA.cpp", "dom/StealthB.cpp"} and set(manifest["sha256"]) == set(manifest["added"])
    engine.export(world, "TAG", "more")          # nothing declared: the folder that holds the file owns it
    assert (root / "fingerprint" / "a" / "src" / "dom" / "StealthB.cpp").is_file()


def test_own_values_are_checked():
    assert engine.declared_owners(["dom/=fingerprint/a", "x.cpp=platform/b"]) == {"dom/": "fingerprint/a", "x.cpp": "platform/b"}
    for bad in ("dom/x.cpp", "dom/x.cpp=", "=fingerprint/a", "dom/x.cpp=nowhere/a", "dom/x.cpp=fingerprint"):
        with pytest.raises(SystemExit) as stop:
            engine.declared_owners([bad])
        assert "next: python tools/engine.py export" in stop.value.code, bad


# ---------------------------------------------------------------------------------------------------------------------- the gtest list
def test_the_preprocessor_guards_of_a_file_say_where_a_test_is_built():
    text = ("TEST(All, A) {}\n#ifdef XP_WIN\nTEST(Win, A) {}\n#else\nTEST(NotWin, A) {}\n#endif\n"
            "#if defined(XP_LINUX) && !defined(ANDROID) && defined(__x86_64__)\nTEST(Lin, A) {}\n#endif  // XP_LINUX\n"
            "#if defined(MOZ_SOMETHING_UNKNOWN)\nTEST(Maybe, A) {}\n#endif\n#ifndef MOZ_SOMETHING_UNKNOWN\nTEST(Maybe, B) {}\n#endif\n")
    active = gtest_list.guarded_lines(text)
    where = {}
    for m in gtest_list.hooks_list.GTEST_RE.finditer(text):
        where[m.groups()] = active[text.count("\n", 0, m.start())]
    both = {"windows", "linux"}
    assert where[("All", "A")] == both and where[("Win", "A")] == {"windows"} and where[("NotWin", "A")] == {"linux"}
    assert where[("Lin", "A")] == {"linux"}
    assert where[("Maybe", "A")] == both and where[("Maybe", "B")] == both, "a condition that cannot be read keeps the test on both"


def test_a_moz_build_condition_says_where_a_file_is_built():
    lines = ['UNIFIED_SOURCES += ["TestA.cpp"]', 'if CONFIG["OS_TARGET"] == "WINNT":', '', '    UNIFIED_SOURCES += ["TestW.cpp"]',
             'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "gtk":', '    UNIFIED_SOURCES += ["TestL.cpp"]',
             'if CONFIG["OS_TARGET"] != "WINNT":', '    UNIFIED_SOURCES += ["TestNotW.cpp"]',
             'if CONFIG["MOZ_DEBUG"]:', '    UNIFIED_SOURCES += ["TestU.cpp"]']
    where = {line.split('"')[1]: gtest_list._moz_platforms(lines, n) for n, line in enumerate(lines) if "SOURCES" in line}
    both = {"windows", "linux"}
    assert where == {"TestA.cpp": both, "TestW.cpp": {"windows"}, "TestL.cpp": {"linux"}, "TestNotW.cpp": {"linux"}, "TestU.cpp": both}


def _series_with_a_gtest(tmp_path, source, test="gtest:StealthA.One", moz_build=None):
    root = tmp_path / "series"
    d = root / "fingerprint" / "a"
    (d / "src" / "dom").mkdir(parents=True)
    (d / "src" / "dom" / "TestStealthA.cpp").write_text(source, encoding="utf-8")
    if moz_build is not None:
        (d / "src" / "dom" / "moz.build").write_text(moz_build, encoding="utf-8")
    (d / "MANIFEST.json").write_text("{}", encoding="utf-8")
    (d / "HOOKS.json").write_text(json.dumps([{"file": "x.cpp", "function": "f", "kind": "add", "form": "guard", "line": "x", "test": test}]), encoding="utf-8")
    (root / "SERIES").write_text("fingerprint/a\n", encoding="utf-8")
    (root / "tools").mkdir()
    return root


def test_a_suite_is_listed_sorted_and_marked_where_its_tests_are_built(tmp_path):
    root = _series_with_a_gtest(tmp_path, "#ifdef XP_WIN\nTEST(StealthA, One) {}\n#endif\n")
    assert gtest_list.suites(root) == [{"suite": "StealthA", "windows_only": True, "linux_only": False}]
    root = _series_with_a_gtest(tmp_path / "b", "TEST(StealthA, One) {}\n", moz_build='if CONFIG["OS_TARGET"] == "WINNT":\n    SOURCES += ["TestStealthA.cpp"]\n')
    assert gtest_list.suites(root) == [{"suite": "StealthA", "windows_only": True, "linux_only": False}]
    root = _series_with_a_gtest(tmp_path / "c", "TEST(StealthA, One) {}\n#ifdef XP_WIN\nTEST(StealthA, Two) {}\n#endif\n")
    assert gtest_list.suites(root) == [{"suite": "StealthA", "windows_only": False, "linux_only": False}], "one test on both: the suite is on both"


def test_a_suite_registered_in_a_mozbuild_file_of_ours_keeps_its_platform(tmp_path):
    source = "TEST(StealthA, One) {}\n"
    cond = 'if CONFIG["OS_TARGET"] == "WINNT":\n    SOURCES += ["TestStealthA.cpp"]\n'
    for name in ("StealthATests.mozbuild", "StealthATests.build"):
        root = _series_with_a_gtest(tmp_path / name, source)
        (root / "fingerprint" / "a" / "src" / "dom" / name).write_text(cond, encoding="utf-8")
        assert gtest_list.suites(root) == [{"suite": "StealthA", "windows_only": True, "linux_only": False}], name
    root = _series_with_a_gtest(tmp_path / "none", source)
    (root / "fingerprint" / "a" / "src" / "dom" / "Other.txt").write_text(cond, encoding="utf-8")
    assert gtest_list.suites(root) == [{"suite": "StealthA", "windows_only": False, "linux_only": False}], "only build files are read"


def test_a_stale_gtest_list_fails_and_the_message_names_gtest_list_write(tmp_path):
    root = _series_with_a_gtest(tmp_path, "TEST(StealthA, One) {}\n")
    found = gtest_list.problems(root)
    assert len(found) == 1 and "does not exist" in found[0] and GTEST_LIST in found[0], found
    gtest_list.write(root)
    assert gtest_list.problems(root) == []
    (root / gtest_list.FILE).write_text(gtest_list.render([]), encoding="utf-8")            # a suite deleted by hand
    found = gtest_list.problems(root)
    assert len(found) == 1 and GTEST_LIST in found[0] and "Rule: docs/decisions/repo-06" in found[0], found
    gtest_list.write(root)
    (root / "fingerprint" / "a" / "HOOKS.json").write_text(json.dumps([{"file": "x.cpp", "function": "f", "kind": "add", "form": "guard", "line": "x",
                                                                       "test": "gtest:StealthA.One"},
                                                                      {"file": "y.cpp", "function": "f", "kind": "add", "form": "guard", "line": "y",
                                                                       "test": "gtest:StealthB.One"}]), encoding="utf-8")
    assert gtest_list.problems(root), "a hook that names a new suite makes the file stale"


def test_the_gtest_list_as_committed_is_what_the_series_gives():
    assert gtest_list.problems(engine.ROOT) == []
    rows = json.loads((engine.ROOT / gtest_list.FILE).read_text(encoding="utf-8"))
    names = [r["suite"] for r in rows]
    assert names == sorted(names) and len(names) == len(set(names)) and len(names) > 50
    assert all(set(r) == {"suite", "windows_only", "linux_only"} for r in rows)
    by = {r["suite"]: r for r in rows}
    assert by["StealthWebGPUAdapter"]["windows_only"] and by["StealthWebGPUBundledVulkan"]["linux_only"] and not by["StealthGLMultisample"]["windows_only"]


def test_the_command_compares_and_writes(tmp_path, monkeypatch, capsys):
    root = _series_with_a_gtest(tmp_path, "TEST(StealthA, One) {}\n")
    monkeypatch.setattr(engine, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["engine.py", "gtest-list"])
    assert engine.main() == 1
    assert "next: " + GTEST_LIST in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["engine.py", "gtest-list", "--write"])
    assert engine.main() == 0 and "1 suites" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["engine.py", "gtest-list"])
    assert engine.main() == 0
