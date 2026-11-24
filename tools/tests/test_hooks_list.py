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


def test_a_gtest_declaration_on_two_lines_resolves(tmp_path):
    root = series(tmp_path, top(G1))
    src = root / FOLDER / "src" / "intl" / "gtest"
    src.mkdir(parents=True)
    (src / "TestWrapped.cpp").write_text(
        "TEST(Wrapped_Suite,\n     ALongNameThatClangFormatBreaks)\n{\n}\n"
        "TEST_F(Wrapped_Fixture,\r\n       AlsoBroken) {}\n"
        "TEST(Wrapped_Suite, OneLine) {}\n", encoding="utf-8")
    for ref, ok in (("gtest:Wrapped_Suite.ALongNameThatClangFormatBreaks", True),
                    ("gtest:Wrapped_Fixture.AlsoBroken", True), ("gtest:Wrapped_Suite.OneLine", True),
                    ("gtest:Wrapped_Suite.Nope", False), ("gtest:Wrapped_Suite.ALongNameThatClang", False)):
        assert (hl.reference_problem(root, ref) is None) == ok, ref


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


def test_a_reference_to_an_invariant_or_a_case_of_a_checker(tmp_path):
    root = series(tmp_path, top(G1))
    d = root / FOLDER / "src" / "scripts"
    d.mkdir(parents=True)
    (d / "ci_gate.py").write_text('INVARIANTS = ["host-free"]\nCASES = {"clean": 1}\ndef no_proxy():\n    pass\n',
                                  encoding="utf-8")
    for ref in ("py:scripts/ci_gate.py::invariant:host-free", "py:scripts/ci_gate.py::invariant:no_proxy",
                "py:scripts/ci_gate.py::case:clean", "wrapper:scripts/ci_host_gate.py::invariant:host-free",
                "wrapper:scripts/ci_host_gate.py::case:clean"):
        assert hl.reference_problem(root, ref) is None, ref
    for ref in ("py:scripts/ci_gate.py::invariant:absent", "py:scripts/ci_gate.py::case:absent",
                "py:scripts/ci_gate.py::case:clea", "py:scripts/ci_gate.py::invariant:",
                "py:scripts/missing.py::invariant:host-free", "wrapper:scripts/ci_host_gate.py::invariant:",
                "wrapper:scripts/ci_host_gate.py::case:"):
        assert hl.reference_problem(root, ref), ref


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


# --------------------------------------------------------------------------- G35: the declared exception
EXC_REMOVED = "  DoIt(x);"
EXC_ADDED = "  DoIt(x, StealthCtx(this), StealthMore(this));" + MARK     # two arguments of ours in a Mozilla call: no form can express it


def exception_series(tmp_path):
    patch = hunk("dom/A.cpp", ["   // lead", " " + FN, "   int x = 1;", "-" + EXC_REMOVED, "+" + EXC_ADDED, "   Done();",
                              "   More();", "   Last();"])
    root = series(tmp_path, patch)
    entries = hl.expected(root, FOLDER)
    entries[0]["test"] = "wrapper:tests/test_a.py::test_b"
    commit_list(root, entries)
    return root, entries


def test_a_declared_exception_is_left_out_of_the_contract_and_counted(tmp_path):
    root, entries = exception_series(tmp_path)
    assert [v.rule for v in hc.contract_violations(root)] == ["C6"]            # the rewrite no form expresses
    assert hl.declared_exceptions(root) == []
    entries[0].update(exception="a parameter of ours in a Mozilla call", pm="approvato")
    commit_list(root, entries)
    assert hc.contract_violations(root) == [] and hl.problems(root) == []
    assert [(f, e["line"]) for f, e in hl.declared_exceptions(root)] == [(FOLDER, EXC_ADDED.rstrip())]
    # T1 and T2 are left out too: no test, and the exception stands
    entries[0]["test"] = ""
    commit_list(root, entries)
    assert hc.contract_violations(root) == []


def test_an_exception_without_the_pm_is_a_failure_and_no_exception(tmp_path):
    root, entries = exception_series(tmp_path)
    for fields in ({"exception": "why"}, {"exception": "why", "pm": "ok"}, {"exception": "why", "pm": ""},
                   {"exception": "", "pm": "approvato"}, {"pm": "si"}):
        commit_list(root, [dict(entries[0], **fields)])
        assert hl.problems(root), fields
        assert hl.declared_exceptions(root) == [], fields
        assert [v.rule for v in hc.contract_violations(root)] == ["C6"], fields      # nothing is excluded
    commit_list(root, [dict(entries[0], exception="why", pm="approvato")])
    assert hl.problems(root) == []


def test_the_exception_fields_survive_a_regeneration_like_the_test(tmp_path):
    root, entries = exception_series(tmp_path)
    entries[0].update(exception="why", pm="approvato")
    commit_list(root, entries)
    hl.write_all(root)
    again = read_list(root)
    assert again[0]["exception"] == "why" and again[0]["pm"] == "approvato" and again[0]["test"] == entries[0]["test"]
    assert list(again[0]).index("test") < list(again[0]).index("exception") < list(again[0]).index("pm")
    set_patch(root, hunk("dom/A.cpp", ["   // lead", " " + FN, "   int x = 1;", "-" + EXC_REMOVED, "+  DoIt(x, StealthCtx2(this));" + MARK,
                                       "   Done();", "   More();", "   Last();"]))
    assert "exception" not in hl.expected(root, FOLDER)[0]          # a hook whose text changed is asked again
    # an entry that has none gets none
    root2 = series(tmp_path / "other", top(G1))
    assert [k for k in hl.expected(root2, FOLDER)[0]] == ["file", "function", "kind", "form", "line", "test"]


def test_a_violation_is_left_out_only_when_every_hook_it_concerns_is_an_exception(tmp_path):
    two = hunk("dom/A.cpp", ["   // lead", " " + FN, "-  int x = 1;", "-  DoIt(x);", "+  int x = StealthA(this);" + MARK,
                             "+  DoIt(x, StealthB(this));" + MARK, "   Done();", "   More();", "   Last();"])
    root = series(tmp_path, two)
    entries = hl.expected(root, FOLDER)
    assert len(entries) == 2
    for e in entries:
        e["test"] = "wrapper:tests/test_a.py::test_b"
    entries[0].update(exception="why", pm="approvato")
    commit_list(root, entries)
    assert "C6" in {v.rule for v in hc.contract_violations(root)}        # the second line is not an exception
    entries[1].update(exception="why too", pm="approvato")
    commit_list(root, entries)
    assert hc.contract_violations(root) == []


def test_check_prints_the_number_of_declared_exceptions(tmp_path, monkeypatch, capsys):
    root, entries = exception_series(tmp_path)
    entries[0].update(exception="why", pm="approvato")
    commit_list(root, entries)
    monkeypatch.setattr(engine, "ROOT", root)
    assert engine.declared_exceptions() == 1
    monkeypatch.undo()
    assert engine.check() == 0
    out = capsys.readouterr().out
    assert "declared exceptions: %d" % engine.declared_exceptions() in out, out      # the series' own count


# --------------------------------------------------------------------------- T3 (G20): the test of a hook is run by a round
WORKFLOW = """name: release
on:
  workflow_dispatch:
    inputs:
      gtest_filter:
        # what the last green run ran
        description: "which"
        default: 'StealthA.*:StealthB.One:Stealth?.Wild:TestStealthC.*-StealthA.Skipped'
      other:
        default: 'NotTheFilter.*'
jobs:
  checks:
    steps:
      - run: node --test juggler/tests/*.test.mjs
      # - run: python3 scripts/ci/commented_out.py
      - name: python
        run: |
          python3 scripts/ci/test_ci.py
          python3 scripts/ci/test_stealth_download_watchdog.py
"""


def t3_series(tmp_path, with_workflow=True):
    root = series(tmp_path, top(G1))
    if with_workflow:
        wf = root / "platform" / "ci" / "src" / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "release.yml").write_text(WORKFLOW, encoding="utf-8", newline="")
    return root


def t3_rules(root, test):
    entries = hl.expected(root, FOLDER)
    entries[0]["test"] = test
    commit_list(root, entries)
    return [v.rule for v in hc.contract_violations(root)]


def test_t3_a_gtest_must_be_in_the_filter_of_the_candidate(tmp_path):
    root = t3_series(tmp_path)
    for ref in ("gtest:StealthA.Any", "gtest:StealthB.One", "gtest:StealthZ.Wild", "gtest:TestStealthC.Anything"):
        assert t3_rules(root, ref) == [], ref
    for ref in ("gtest:StealthB.Two", "gtest:Nope.One", "gtest:StealthA.Skipped", "gtest:NotTheFilter.One"):
        assert t3_rules(root, ref) == ["T3"], ref


def test_t3_a_node_test_must_match_a_glob_of_the_node_job(tmp_path):
    root = t3_series(tmp_path)
    assert t3_rules(root, "node:juggler/tests/x.test.mjs") == []
    assert t3_rules(root, "node:juggler/tests/x.test.mjs#a title") == []
    for ref in ("node:juggler/tests/sub/x.test.mjs", "node:toolkit/x.test.mjs", "node:juggler/tests/x.mjs"):
        assert t3_rules(root, ref) == ["T3"], ref


def test_t3_a_python_test_must_be_run_by_a_step_or_be_a_tree_test_of_the_export_gate(tmp_path):
    root = t3_series(tmp_path)
    for ref in ("py:scripts/ci/test_ci.py::test_a", "py:scripts/ci/test_stealth_download_watchdog.py::test_b",
                "py:modules/libpref/test/test_stealth_prefs.py::test_c"):
        assert t3_rules(root, ref) == [], ref
    for ref in ("py:scripts/ci/commented_out.py::test_a", "py:scripts/ci/test_c.py::test_a",
                "py:modules/libpref/test/other_stealth.py::test_c", "py:scripts/ci/test.py::test_a"):
        assert t3_rules(root, ref) == ["T3"], ref


def test_t3_a_wrapper_test_and_a_series_without_the_workflow_are_not_judged(tmp_path):
    root = t3_series(tmp_path)
    assert t3_rules(root, "wrapper:tests/test_a.py::test_b") == []
    bare = t3_series(tmp_path / "bare", with_workflow=False)
    assert t3_rules(bare, "gtest:Nope.One") == []


def test_t3_is_debt_like_t1_and_has_a_stable_key(tmp_path):
    root = t3_series(tmp_path)
    t3_rules(root, "gtest:Nope.One")
    (v,) = hc.contract_violations(root)
    assert v.rule == "T3" and v.key.startswith("T3|%s|dom/A.cpp|" % FOLDER) and "gtest:Nope.One" in v.detail
    assert hc.debt_problems([v], [hc.entry_of(v)], [hc.entry_of(_viol("C2", "x();"))]) == []     # main has no T3: allowed once
    assert "T3" in hc.RULES and "T3" in hc.debt_summary([hc.entry_of(v)])


def test_the_rounds_of_the_real_series():
    rounds = hl._Rounds(engine.ROOT)
    assert rounds.known and "StealthFullscreen.*" in rounds.filter
    assert rounds.gtest_runs("StealthFullscreen", "Anything") and not rounds.gtest_runs("StealthNoSuchSuite", "X")
    assert rounds.node_runs("juggler/tests/x.test.mjs") and not rounds.node_runs("juggler/tests/sub/x.test.mjs")
    assert rounds.py_runs("scripts/ci/test_ci.py") and rounds.py_runs("modules/libpref/test/test_stealth_x.py")
    assert not rounds.py_runs("scripts/ci/commented_out_nowhere.py")


# --------------------------------------------------------------------------- xpcshell refs and the untestable hook
def test_an_xpcshell_reference_must_exist_with_its_title(tmp_path):
    root = series(tmp_path, top(G1))
    d = root / FOLDER / "src" / "toolkit" / "test"
    d.mkdir(parents=True)
    (d / "test_x.js").write_text("add_task(async function test_the_title() {});\n", encoding="utf-8")
    assert hl.reference_problem(root, "xpcshell:toolkit/test/test_x.js#test_the_title") is None
    for ref in ("xpcshell:toolkit/test/test_x.js", "xpcshell:#t", "xpcshell:toolkit/test/test_x.js#nope", "xpcshell:toolkit/none.js#t"):
        assert hl.reference_problem(root, ref), ref


def test_t3_an_xpcshell_test_is_run_by_no_round_until_a_workflow_line_runs_it(tmp_path):
    root = t3_series(tmp_path)
    assert t3_rules(root, "xpcshell:toolkit/test/test_x.js#test_the_title") == ["T3"]
    wf = root / "platform" / "ci" / "src" / ".github" / "workflows" / "release.yml"
    wf.write_text(WORKFLOW + "      - run: firefox -xpcshell toolkit/test/test_x.js\n", encoding="utf-8", newline="")
    assert t3_rules(root, "xpcshell:toolkit/test/test_x.js#test_the_title") == []
    bare = t3_series(tmp_path / "bare", with_workflow=False)
    assert t3_rules(bare, "xpcshell:toolkit/test/test_x.js#test_the_title") == ["T3"]


def test_an_untestable_hook_is_counted_apart_and_has_no_t1(tmp_path, monkeypatch):
    root = series(tmp_path, top(G1))
    assert [v.rule for v in hc.contract_violations(root)] == ["T1"]
    entries = hl.expected(root, FOLDER)
    entries[0].update(untestable="no browser path reaches it", pm="approvato")
    commit_list(root, entries)
    assert hc.contract_violations(root) == [] and hl.problems(root) == []
    assert [(f, e["line"]) for f, e in hl.untestable_hooks(root)] == [(FOLDER, G1.rstrip())]
    assert hl.declared_exceptions(root) == []                 # counted apart from the exceptions
    monkeypatch.setattr(engine, "ROOT", root)
    assert engine.untestable_hooks() == 1 and engine.declared_exceptions() == 0
    # the C-rules still apply to an untestable hook: it excuses the missing test only
    set_patch(root, top("  // the reason", G1))
    entries = hl.expected(root, FOLDER)
    entries[-1].update(untestable="why", pm="approvato")
    commit_list(root, entries)
    assert "C4" in {v.rule for v in hc.contract_violations(root)}


def test_an_untestable_without_the_pm_or_beside_a_test_is_a_failure(tmp_path):
    root = series(tmp_path, top(G1))
    base = hl.expected(root, FOLDER)[0]
    for fields in ({"untestable": "why"}, {"untestable": "why", "pm": "ok"}, {"untestable": "", "pm": "approvato"},
                   {"untestable": "why", "pm": "approvato", "test": "wrapper:tests/test_a.py::test_b"}):
        commit_list(root, [dict(base, **fields)])
        assert hl.problems(root), fields
    commit_list(root, [dict(base, untestable="why", pm="approvato")])
    assert hl.problems(root) == []
    commit_list(root, [dict(base, untestable="why")])
    assert hl.untestable_hooks(root) == [] and [v.rule for v in hc.contract_violations(root)] == ["T1"]    # no pm: still debt
    entries = hl.expected(root, FOLDER)
    assert list(entries[0]) == ["file", "function", "kind", "form", "line", "test", "untestable"]


def test_check_prints_the_untestable_count(capsys):
    assert engine.check() == 0
    assert "untestable hooks: %d" % engine.untestable_hooks() in capsys.readouterr().out     # the series' own count


def test_an_approved_exception_covers_every_copy_of_a_repeated_violation(tmp_path):
    # the same line twice in one function: the second violation has the key `...#2` and keeps the hook ids
    line = "  x = StealthN(this) + 1;" + MARK                 # logic in the hook: C5
    patch = hunk("dom/A.cpp", ["   // lead", " " + FN, "+" + line, "   int x = 1;", "+" + line, "   DoIt(x);",
                              "   return NS_OK;", " }"])
    root = series(tmp_path, patch)
    assert len([v for v in hc.contract_violations(root) if v.rule == "C5"]) == 2
    assert any(v.key.endswith("#2") and v.ids for v in hc._analyse(root)[1])
    entries = hl.expected(root, FOLDER)
    for e in entries:
        e.update(test="wrapper:tests/test_a.py::test_b", exception="the logic is a pref default", pm="approvato")
    commit_list(root, entries)
    assert [v for v in hc.contract_violations(root) if v.rule == "C5"] == []


# --------------------------------------------------------------------------- C9 of a declared anchor, and the cargo reference
def anchor_series(tmp_path, lines):
    root = series(tmp_path, hunk("dom/A.cpp", lines))
    entries = hl.expected(root, FOLDER)
    for e in entries:
        e["test"] = "wrapper:tests/test_a.py::test_b"
    commit_list(root, entries)
    return root, entries


def test_c9_a_declared_anchor_at_the_end_of_a_block_or_of_a_constructor_is_allowed(tmp_path):
    cases = {
        "if-branch": ["   // lead", " " + FN, "   if (a) {", "     int x = 1;", "+    priv->x = options.x;" + MARK, "   }", "   return NS_OK;", " }"],
        "constructor": ["   // lead", " Foo::Foo(const Foo& aRhs) {", "+  StealthCopied(this, aRhs);" + MARK, " }"],
    }
    for name, lines in cases.items():
        root, entries = anchor_series(tmp_path / name, lines)
        assert [v.rule for v in hc.contract_violations(root)] == ["C9"], name              # red: no anchor and why declared
        for e in entries:
            e.update(anchor="after the copy of the members", why="the last statement of the block: nothing follows to anchor to")
        commit_list(root, entries)
        assert hc.contract_violations(root) == [] and hl.problems(root) == [], name        # green, and the list is stable
        hl.write_all(root)
        assert [e.get("anchor") for e in read_list(root)] == ["after the copy of the members"], name
    # a Mozilla list is not a block end: the declaration does not cover it
    root, entries = anchor_series(tmp_path / "list", ["   // lead", "   static const int kA[] = {", "     1,", "     2,",
                                                          "+    " + "3," + MARK, "   };"])
    entries[0].update(anchor="a", why="b")
    commit_list(root, entries)
    assert [v.rule for v in hc.contract_violations(root)] == ["C9"]


def test_a_markdown_line_before_agents_md_is_not_the_last_line_of_a_block(tmp_path):
    md = patch_md("CLAUDE.md", ["+@STEALTH_CLAUDE.md <!-- STEALTH-HOOK(fingerprint/x) -->", " @AGENTS.md"])
    root = series(tmp_path, md)
    assert [v.rule for v in hc.contract_violations(root) if v.rule.startswith("C")] == []


def patch_md(file, lines):
    return ("diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@ -1 +1,2 @@\n%s\n" % (file, file, file, file, "\n".join(lines)))


def test_a_cargo_reference_is_format_checked_and_run_by_a_cargo_test_step(tmp_path):
    root = t3_series(tmp_path)
    for ref in ("cargo:stealth-x::tests::it_works", "cargo:stealth_x::it_works"):
        assert hl.reference_problem(root, ref) is None, ref
    for ref in ("cargo:stealth_x", "cargo:::t", "cargo:stealth_x::", "cargo:stealth_x:it_works", "cargo:a b::t"):
        assert hl.reference_problem(root, ref), ref
    assert t3_rules(root, "cargo:stealth_x::tests::it_works") == ["T3"]          # red: no step runs cargo test
    wf = root / "platform" / "ci" / "src" / ".github" / "workflows"
    (wf / "cargo-tests.yml").write_text(
        "jobs:\n  cargo:\n    steps:\n      # - run: cargo test -p commented_out\n"
        "      - run: cargo test --locked -p stealth_x\n"
        "      - run: |\n          cargo test \\\n            --package other-crate \\\n            -- --nocapture\n"
        "      - run: cargo test --manifest-path rust/third/Cargo.toml\n", encoding="utf-8", newline="")
    for ref in ("cargo:stealth_x::tests::it_works", "cargo:other-crate::t", "cargo:third::t"):
        assert t3_rules(root, ref) == [], ref
    for ref in ("cargo:stealth::t", "cargo:stealth_xy::t", "cargo:commented_out::t", "cargo:thir::t"):
        assert t3_rules(root, ref) == ["T3"], ref
    (wf / "cargo-tests.yml").write_text("jobs:\n  c:\n    steps:\n      - run: cargo test --workspace\n",
                                       encoding="utf-8", newline="")
    assert t3_rules(root, "cargo:anything::t") == []


def test_a_cargo_test_naming_no_package_runs_the_crate_of_its_step_s_working_directory(tmp_path):
    # the mdns_service step of cargo-tests.yml: `cargo test --lib` in the crate's own directory
    root = t3_series(tmp_path)
    wf = root / "platform" / "ci" / "src" / ".github" / "workflows"
    (wf / "cargo-tests.yml").write_text(
        "jobs:\n  cargo:\n    steps:\n"
        "      - name: The test of ours in mdns_service\n"
        "        id: cargo-mdns\n"
        "        working-directory: dom/media/webrtc/transport/mdns_service\n"
        "        run: |\n"
        "          set -eo pipefail\n"
        "          cargo test --lib -- stealth_tests:: 2>&1 | tee -a log\n"
        "      - name: another step, no working directory\n"
        "        run: cargo test --lib\n"
        "      - working-directory: 'gfx/wr/'\n"
        "        run: cargo test -p webrender --lib\n", encoding="utf-8", newline="")
    assert t3_rules(root, "cargo:mdns_service::stealth_tests::a_test") == []    # red on the tool that read only -p
    # the directory does not leak into the next step, a named package is not the directory's, a prefix is not the name
    for ref in ("cargo:transport::t", "cargo:mdns::t", "cargo:wr::t", "cargo:gfx::t"):
        assert t3_rules(root, ref) == ["T3"], ref
    assert t3_rules(root, "cargo:webrender::t") == []


# --------------------------------------------------------------------------- T3: a node loop, pytest over a directory, the xpcshell leg's list
def release_with(tmp_path, steps):
    root = series(tmp_path, top(G1))
    wf = root / "platform" / "ci" / "src" / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "release.yml").write_text("jobs:\n  checks:\n    steps:\n" + steps, encoding="utf-8", newline="")
    return root


def test_t3_node_tests_run_in_a_shell_loop(tmp_path):
    root = release_with(tmp_path, (
        "      - run: |\n"
        "          rc=0\n"
        "          for f in juggler/tests/*.test.mjs; do\n"
        '            node --test --test-reporter=spec "$f" || rc=1\n'
        "          done\n"
        "          for g in other/*.mjs; do echo $g; done\n"
        "          node --test $UNSET ${rc} && true\n"
        "          exit $rc\n"))
    assert hl._Rounds(root).node_globs == ["juggler/tests/*.test.mjs"]
    assert t3_rules(root, "node:juggler/tests/x.test.mjs") == []
    for ref in ("node:juggler/tests/sub/x.test.mjs", "node:other/y.mjs", "node:rc=1"):
        assert t3_rules(root, ref) == ["T3"], ref
    # the old one-line form still works, and the words after `||` or `;` are not globs
    root = release_with(tmp_path / "one", "      - run: node --test juggler/tests/*.test.mjs; echo done\n")
    assert hl._Rounds(root).node_globs == ["juggler/tests/*.test.mjs"]


def test_t3_node_tests_run_by_checks_yml_count(tmp_path):
    """The node tests run in checks.yml, which the pull request round and every candidate call: a workflow other than release.yml runs them too."""
    root = release_with(tmp_path, "      - run: echo nothing\n")
    assert hl._Rounds(root).node_globs == []
    assert t3_rules(root, "node:juggler/tests/x.test.mjs") == ["T3"]
    wf = root / "platform" / "ci" / "src" / ".github" / "workflows"
    (wf / "checks.yml").write_text("jobs:\n  tree:\n    steps:\n      - run: |\n          for f in juggler/tests/*.test.mjs; do\n"
                                   "            node --test \"$f\" || rc=1\n          done\n", encoding="utf-8", newline="")
    assert hl._Rounds(root).node_globs == ["juggler/tests/*.test.mjs"]
    assert t3_rules(root, "node:juggler/tests/x.test.mjs") == []


def test_t3_a_pytest_line_over_a_directory_runs_the_tests_under_it(tmp_path):
    root = release_with(tmp_path, "      - run: python -m pytest tools/tests -q --rootdir=.\n"
                                  "      - run: python -m pytest $SELECT -q scripts/ci/test_one.py\n")
    for ref in ("py:tools/tests/test_a.py::test_x", "py:tools/tests/sub/test_b.py::test_y", "py:scripts/ci/test_one.py::test_z"):
        assert t3_rules(root, ref) == [], ref
    for ref in ("py:tools/other/test_a.py::test_x", "py:tools/tests_other/test_a.py::test_x", "py:scripts/ci/test_two.py::test_z",
                "py:test_a.py::test_x"):
        assert t3_rules(root, ref) == ["T3"], ref
    # a directory that is not a pytest argument does not count
    root = release_with(tmp_path / "no", "      - run: ls tools/tests\n")
    assert t3_rules(root, "py:tools/tests/test_a.py::test_x") == ["T3"]


def test_t3_an_xpcshell_test_is_run_when_the_legs_list_names_it(tmp_path):
    root = t3_series(tmp_path)
    ref = "xpcshell:toolkit/test/test_x.js#test_the_title"
    assert t3_rules(root, ref) == ["T3"]
    lst = root / "platform" / "ci" / "src" / "scripts" / "ci"
    lst.mkdir(parents=True)
    (lst / "xpcshell_tests.json").write_text(json.dumps({"files": ["toolkit/test/test_x.js"]}), encoding="utf-8", newline="")
    assert t3_rules(root, ref) == []
    assert t3_rules(root, "xpcshell:toolkit/test/test_y.js#t") == ["T3"]
    bare = t3_series(tmp_path / "bare", with_workflow=False)       # the list counts without the candidate workflow too
    lst = bare / "platform" / "ci" / "src" / "scripts" / "ci"
    lst.mkdir(parents=True)
    (lst / "xpcshell_tests.json").write_text(json.dumps({"files": ["toolkit/test/test_x.js"]}), encoding="utf-8", newline="")
    assert t3_rules(bare, ref) == []


def test_a_py_reference_under_tools_tests_names_a_test_of_the_series_itself(tmp_path):
    root = series(tmp_path, top(G1))
    ref = "py:tools/tests/test_repo_files_are_ours.py::test_claude_md_is_the_tag_plus_one_line"
    assert hl.reference_problem(root, ref)                      # red: the series has no such file
    d = root / "tools" / "tests"
    d.mkdir(parents=True)
    (d / "test_repo_files_are_ours.py").write_text("def test_claude_md_is_the_tag_plus_one_line():\n    pass\n", encoding="utf-8")
    assert hl.reference_problem(root, ref) is None
    assert hl.reference_problem(root, "py:tools/tests/test_repo_files_are_ours.py::test_gone")
    assert hl.reference_problem(root, "py:tools/other/test_repo_files_are_ours.py::test_claude_md_is_the_tag_plus_one_line")
    # the real series: the tests of platform/repo's two hooks resolve
    for name in ("test_claude_md_is_the_tag_plus_one_line_naming_a_file_that_exists",
                 "test_readme_md_is_the_tag_plus_one_line_naming_a_file_that_exists"):
        assert hl.reference_problem(engine.ROOT, "py:tools/tests/test_repo_files_are_ours.py::" + name) is None
