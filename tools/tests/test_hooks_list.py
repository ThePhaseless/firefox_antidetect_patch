"""HOOKS.json (tools/hooks_list.py): the list of each folder's hooks, generated from its hooks.patch and checked.

Each rule is shown failing on the input it exists for and passing on the fixed one, on a small series built in
tmp_path, then the committed lists are checked against the real series.

    python -m pytest tools/tests
"""
import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402
import hook_contract as hc  # noqa: E402
import hooks_list as hl  # noqa: E402

FOLDER = "fingerprint/x"
FN = "nsresult Foo::Bar(int aArg) {"
BODY = ["   int x = 1;", "   DoIt(x);", "   return NS_OK;", " }"]
MARK = "  // STEALTH-HOOK(fingerprint/x)"
G1 = "  if (StealthOne(this, aArg)) return NS_OK;" + MARK
G2 = "  if (StealthTwo(this, aArg)) return NS_OK;" + MARK
G2_CHANGED = "  if (StealthTwoB(this, aArg)) return NS_OK;" + MARK
ANCHOR = "  StealthMid(this, &x);" + MARK


def hunk(file, lines, section=FN, start=10):
    old = sum(1 for l in lines if l[0] in " -")
    new = sum(1 for l in lines if l[0] in " +")
    return ("diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@ -%d,%d +%d,%d @@ %s\n%s\n"
            % (file, file, file, file, start, old, start, new, section, "\n".join(lines)))


def top(*added, file="dom/A.cpp"):
    return hunk(file, ["   // lead", " ", " " + FN, *["+" + a for a in added], *BODY])


def pair(a, b, swapped=False):
    """Two hooks in two files (two added lines side by side would be one hook of two lines)."""
    one, two = top(a, file="dom/A.cpp"), top(b, file="dom/B.cpp")
    return two + one if swapped else one + two


def mid(*added, file="dom/A.cpp"):
    return hunk(file, ["   // lead", " " + FN, "   int x = 1;", *["+" + a for a in added], "   DoIt(x);", "   return NS_OK;", " }"])


def series(tmp_path, patch, folder=FOLDER):
    d = tmp_path / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "hooks.patch").write_text(patch, encoding="utf-8", newline="")
    (tmp_path / "SERIES").write_text(folder + "\n", encoding="utf-8", newline="")
    return tmp_path


def read_list(root):
    return json.loads(hl.list_path(root, FOLDER).read_text(encoding="utf-8"))


def commit_list(root, entries):
    hl.list_path(root, FOLDER).write_text(hl.render(entries), encoding="utf-8", newline="")


def set_patch(root, patch):
    (root / FOLDER / "hooks.patch").write_text(patch, encoding="utf-8", newline="")


# --------------------------------------------------------------------------- generating
def test_an_entry_per_hook_in_the_order_of_the_patch(tmp_path):
    root = series(tmp_path, pair(G1, G2))
    gen = hl.generated(root, FOLDER)
    assert [e["line"] for e in gen] == [G1.rstrip(), G2.rstrip()]
    assert [e["form"] for e in gen] == ["guard", "guard"]
    assert list(gen[0]) == ["file", "function", "kind", "form", "line"]
    assert gen[0]["file"] == "dom/A.cpp" and gen[0]["function"] == FN and gen[0]["kind"] == "add"


def test_a_deletion_and_a_rewrite_are_listed_too(tmp_path):
    deletion = hunk("dom/Bar.cpp", ["   keep();", "-  gone();", "   keep2();"], section="void Bar() {")
    rewrite = hunk("dom/Baz.cpp", ["   keep();", "-  return Real();", "+  return StealthWrap(Real());" + MARK, "   keep2();"],
                   section="int Baz() {")
    root = series(tmp_path, top(G1) + deletion + rewrite)
    by_file = {e["file"]: e for e in hl.generated(root, FOLDER)}
    assert by_file["dom/Bar.cpp"]["kind"] == "delete" and by_file["dom/Bar.cpp"]["line"] == ""
    assert "gone();" in by_file["dom/Bar.cpp"]["removed"]
    assert by_file["dom/Baz.cpp"]["kind"] == "rewrite" and by_file["dom/Baz.cpp"]["form"] == "wrap-expression"
    assert "return Real();" in by_file["dom/Baz.cpp"]["removed"]


def test_a_backport_folder_has_no_list(tmp_path):
    root = series(tmp_path, top(G1))
    (root / FOLDER / "BACKPORT.json").write_text("{}", encoding="utf-8")
    assert hl.folders(root) == [] and hl.generated(root, FOLDER) == [] and hl.write_all(root) == {}


def test_a_folder_without_a_patch_has_an_empty_list(tmp_path):
    root = series(tmp_path, top(G1))
    (root / FOLDER / "hooks.patch").unlink()
    assert hl.write_all(root) == {FOLDER: 0}
    assert hl.list_path(root, FOLDER).read_text(encoding="utf-8") == "[]\n"
    assert hl.problems(root) == []


# --------------------------------------------------------------------------- the check: the list and the series coincide
def test_the_list_as_generated_is_clean(tmp_path):
    root = series(tmp_path, pair(G1, G2))
    assert any("HOOKS.json is missing" in p and FOLDER in p for p in hl.problems(root))      # red: no file yet
    hl.write_all(root)
    assert hl.problems(root) == []                                                            # green


def test_a_hook_lost_from_the_patch_while_the_list_has_it_fails(tmp_path):
    root = series(tmp_path, pair(G1, G2))
    hl.write_all(root)
    set_patch(root, top(G1))                       # a merge lost the second hook; HOOKS.json still lists it
    found = hl.problems(root)
    assert len(found) == 1 and FOLDER in found[0] and "StealthTwo" in found[0] and "no longer has" in found[0], found
    hl.write_all(root)                             # the regeneration repairs it
    assert hl.problems(root) == []


def test_a_hook_added_to_the_patch_but_not_to_the_list_fails(tmp_path):
    root = series(tmp_path, top(G1))
    hl.write_all(root)
    set_patch(root, pair(G1, G2))
    found = hl.problems(root)
    assert len(found) == 1 and FOLDER in found[0] and "StealthTwo" in found[0] and "lacks the hook" in found[0], found
    hl.write_all(root)
    assert hl.problems(root) == []


def test_a_field_changed_in_the_list_fails(tmp_path):
    root = series(tmp_path, top(G1))
    hl.write_all(root)
    entries = read_list(root)
    entries[0]["form"] = "anchor"
    commit_list(root, entries)
    found = hl.problems(root)
    assert len(found) == 1 and "form" in found[0] and "StealthOne" in found[0], found


def test_the_order_of_the_list_is_the_order_of_the_patch(tmp_path):
    root = series(tmp_path, pair(G1, G2))
    hl.write_all(root)
    commit_list(root, read_list(root)[::-1])
    assert any("order" in p for p in hl.problems(root))


# --------------------------------------------------------------------------- the hand fields
def test_hand_fields_survive_a_regeneration(tmp_path):
    root = series(tmp_path, pair(G1, G2))
    hl.write_all(root)
    entries = read_list(root)
    entries[1]["test"] = "gtest:Suite.Name"
    commit_list(root, entries)
    hl.write_all(root)
    assert [e["test"] for e in read_list(root)] == ["", "gtest:Suite.Name"]
    set_patch(root, pair(G1, G2, swapped=True))                   # moved: the identity is the text, not the place
    hl.write_all(root)
    assert [e["test"] for e in read_list(root)] == ["gtest:Suite.Name", ""]


def test_anchor_hand_fields_survive_and_only_an_anchor_has_them(tmp_path):
    root = series(tmp_path, mid(ANCHOR))
    entries = hl.expected(root, FOLDER)
    assert entries[0]["form"] == "anchor" and entries[0]["anchor"] == "" and entries[0]["why"] == ""
    entries[0].update(anchor="int x = 1;", why="x is computed there", test="node:a/b.mjs")
    commit_list(root, entries)
    again = hl.expected(root, FOLDER)
    assert (again[0]["anchor"], again[0]["why"], again[0]["test"]) == ("int x = 1;", "x is computed there", "node:a/b.mjs")
    plain = hl.expected(series(tmp_path / "other", top(G1)), FOLDER)
    assert "anchor" not in plain[0] and "why" not in plain[0]


def test_a_changed_hook_text_drops_its_hand_fields_and_asks_again(tmp_path):
    root = series(tmp_path, pair(G1, G2))
    entries = hl.expected(root, FOLDER)
    entries[1]["test"] = "wrapper:tests/test_a.py::test_b"
    commit_list(root, entries)
    assert hl.problems(root) == []
    assert len([v for v in hl.missing_test_violations(root) if v.rule == "T1"]) == 1     # only the first hook lacks one
    set_patch(root, pair(G1, G2_CHANGED))
    assert [e["test"] for e in hl.expected(root, FOLDER)] == ["", ""]               # the hand field went with the old text
    assert any(FOLDER in p and "StealthTwoB" in p for p in hl.problems(root))      # the list lacks the new text
    assert len([v for v in hl.missing_test_violations(root) if v.rule == "T1"]) == 2   # check asks for the test again


def test_merge_pairs_identical_hooks_in_order():
    a = {"file": "f", "function": "F", "kind": "add", "form": "guard", "line": "x();"}
    out = hl.merge([dict(a), dict(a)], [dict(a, test="t1"), dict(a, test="t2")])
    assert [e["test"] for e in out] == ["t1", "t2"]
    assert [e["test"] for e in hl.merge([dict(a)], [])] == [""]
    assert hl.merge([dict(a)], [dict(a, line="y();", test="t")])[0]["test"] == ""


# --------------------------------------------------------------------------- the test references
def test_a_gtest_reference_must_exist(tmp_path):
    root = series(tmp_path, top(G1))
    src = root / FOLDER / "src" / "dom" / "gtest"
    src.mkdir(parents=True)
    (src / "TestFoo.cpp").write_text("TEST(FooSuite, Does) {}\nTEST_F(FooFixture, AlsoDoes) {}\n", encoding="utf-8")
    for ref, ok in (("gtest:FooSuite.Does", True), ("gtest:FooFixture.AlsoDoes", True),
                    ("gtest:FooSuite.Nope", False), ("gtest:Nope.Does", False), ("gtest:NoDot", False)):
        assert (hl.reference_problem(root, ref) is None) == ok, ref
    entries = hl.expected(root, FOLDER)
    entries[0]["test"] = "gtest:FooSuite.Nope"
    commit_list(root, entries)
    assert any("FooSuite.Nope" in p and "does not exist" in p and FOLDER in p for p in hl.problems(root))
    entries[0]["test"] = "gtest:FooSuite.Does"
    commit_list(root, entries)
    assert hl.problems(root) == []


def test_a_node_reference_must_exist_with_its_title(tmp_path):
    root = series(tmp_path, top(G1))
    d = root / FOLDER / "src" / "juggler" / "tests"
    d.mkdir(parents=True)
    (d / "x.test.mjs").write_text("test('hello world', () => {});\n", encoding="utf-8")
    for ref, ok in (("node:juggler/tests/x.test.mjs", True), ("node:juggler/tests/x.test.mjs#hello world", True),
                    ("node:juggler/tests/x.test.mjs#nothing", False), ("node:juggler/tests/missing.test.mjs", False)):
        assert (hl.reference_problem(root, ref) is None) == ok, ref
    entries = hl.expected(root, FOLDER)
    entries[0]["test"] = "node:juggler/tests/missing.test.mjs"
    commit_list(root, entries)
    assert any("missing.test.mjs" in p and "does not exist" in p for p in hl.problems(root))
    entries[0]["test"] = "node:juggler/tests/x.test.mjs#hello world"
    commit_list(root, entries)
    assert hl.problems(root) == []


def test_a_py_reference_and_a_wrapper_reference(tmp_path):
    root = series(tmp_path, top(G1))
    d = root / FOLDER / "src" / "modules" / "test"
    d.mkdir(parents=True)
    (d / "test_stealth_x.py").write_text("def test_it():\n    pass\n", encoding="utf-8")
    assert hl.reference_problem(root, "py:modules/test/test_stealth_x.py::test_it") is None
    assert hl.reference_problem(root, "py:modules/test/test_stealth_x.py::test_gone")
    assert hl.reference_problem(root, "py:modules/test/none.py::test_it")
    assert hl.reference_problem(root, "wrapper:tests/test_a.py::test_b") is None
    assert hl.reference_problem(root, "wrapper:nothing")
    assert hl.reference_problem(root, "whatever:x")


# --------------------------------------------------------------------------- debt (rules T1 and T2) and the shared writer
def test_a_hook_without_a_test_is_debt_until_it_has_one(tmp_path):
    root = series(tmp_path, top(G1))
    hl.write_all(root)
    assert [v.rule for v in hc.contract_violations(root)] == ["T1"]
    entries = read_list(root)
    d = root / FOLDER / "src" / "juggler" / "tests"
    d.mkdir(parents=True)
    (d / "x.test.mjs").write_text("test('t', () => {});\n", encoding="utf-8")
    entries[0]["test"] = "node:juggler/tests/x.test.mjs"
    commit_list(root, entries)
    assert hc.contract_violations(root) == [] and hl.problems(root) == []


def test_an_anchor_without_anchor_and_why_is_debt(tmp_path):
    root = series(tmp_path, mid(ANCHOR))
    entries = hl.expected(root, FOLDER)
    entries[0]["test"] = "wrapper:tests/test_a.py::test_b"
    commit_list(root, entries)
    assert [v.rule for v in hc.contract_violations(root)] == ["T2"]
    entries[0].update(anchor="int x = 1;", why="x is computed there")
    commit_list(root, entries)
    assert hc.contract_violations(root) == []


def _viol(rule, text):
    return hc.Violation(rule, "f/x", "a.cpp", "void F() {", text, hc._key(rule, "f/x", "a.cpp", "void F() {", text))


def test_a_rule_main_does_not_know_yet_may_enter_the_debt_once():
    t1, t1b, c2 = _viol("T1", "one();"), _viol("T1", "b();"), _viol("C2", "two();")
    e = hc.entry_of
    assert hc.debt_problems([t1, c2], [e(t1), e(c2)], [e(c2)]) == []                  # T1 is new on main's side: allowed
    grown = hc.debt_problems([t1, c2], [e(t1), e(c2)], [e(t1)])                        # C2 is not exempt
    assert len(grown) == 1 and c2.key in grown[0]
    more = hc.debt_problems([t1, t1b, c2], [e(t1), e(t1b), e(c2)], [e(t1), e(c2)])     # main has T1: it only shrinks
    assert len(more) == 1 and t1b.key in more[0]


def test_export_and_the_command_write_the_same_list(tmp_path, monkeypatch, capsys):
    assert "write_hooks_list()" in inspect.getsource(engine.export)
    root = series(tmp_path, pair(G1, G2))
    monkeypatch.setattr(engine, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["engine.py", "hooks-list"])
    assert engine.main() == 0
    assert "1 HOOKS.json files, 2 entries" in capsys.readouterr().out
    first = hl.list_path(root, FOLDER).read_bytes()
    assert first == hl.render(hl.expected(root, FOLDER)).encode("utf-8") and b"\r" not in first
    assert engine.write_hooks_list().endswith("1 HOOKS.json files, 2 entries")
    assert hl.list_path(root, FOLDER).read_bytes() == first


def test_check_reports_a_hook_lost_in_a_merge(monkeypatch):
    assert not any("HOOKS.json" in p for p in engine.problems())
    victim = next(f for f in hl.folders(engine.ROOT) if len(hl.generated(engine.ROOT, f)) >= 2)
    real_load = hl.load
    monkeypatch.setattr(hl, "load", lambda root, folder: real_load(root, folder)[1:] if folder == victim else real_load(root, folder))
    got = [p for p in engine.problems() if "HOOKS.json" in p]
    assert len(got) == 1 and got[0].startswith(victim + "/HOOKS.json lacks the hook"), got


# --------------------------------------------------------------------------- the real series
def test_every_committed_list_is_what_the_series_generates():
    assert hl.problems(engine.ROOT) == []
    names = hl.folders(engine.ROOT)
    assert names, "no folder"
    for folder in names:
        data = hl.list_path(engine.ROOT, folder).read_bytes()
        assert b"\r" not in data and data.endswith(b"\n"), folder
        assert data.decode("utf-8") == hl.render(hl.expected(engine.ROOT, folder)), folder
    assert sum(len(hl.generated(engine.ROOT, f)) for f in names) == len(hc.series_hooks(engine.ROOT))


def test_a_backport_folder_of_the_series_has_no_list():
    for f in hl.series_names(engine.ROOT):
        if (engine.ROOT / f / "BACKPORT.json").exists():
            assert not hl.list_path(engine.ROOT, f).exists(), f
