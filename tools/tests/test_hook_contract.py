"""The hook contract of tools/hook_contract.py: each rule shown failing on the hunk it exists for and
passing on the fixed hunk, the stable key, the debt list as committed, and the debt against main.

    python -m pytest tools/tests
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402
import hook_contract as hc  # noqa: E402

FOLDER = "fingerprint/x"
FN = "nsresult Foo::Bar(int aArg) {"
BODY = ["   int x = 1;", "   DoIt(x);", "   return NS_OK;", " }"]


def patch(file, lines, section=FN, start=10, header=""):
    old = sum(1 for l in lines if l[0] in " -")
    new = sum(1 for l in lines if l[0] in " +")
    return ("diff --git a/%s b/%s\n%s--- a/%s\n+++ b/%s\n@@ -%d,%d +%d,%d @@ %s\n%s\n"
            % (file, file, header, file, file, start, old, start, new, section, "\n".join(lines)))


def top(*added, file="dom/Foo.cpp", **kw):
    """Lines added as the first statements of the function FN, with Mozilla's body after them."""
    return patch(file, ["   // lead", " ", " " + FN, *["+" + a for a in added], *BODY], **kw)


def rules(text, file_patch=None):
    _, found = hc.analyse_patch(FOLDER, text)
    return sorted({v.rule for v in found})


def red_green(rule, bad, good):
    assert rule in rules(bad), (rule, rules(bad))
    assert rules(good) == [], rules(good)


MARK = "  // STEALTH-HOOK(fingerprint/x)"
GUARD = "  if (StealthX(this, aArg)) return NS_OK;" + MARK


def test_c1_a_hook_of_more_than_one_line():
    red_green("C1", top("  if (StealthX(this, aArg)) {" + MARK, "    return NS_OK;", "  }"), top(GUARD))


def test_c2_the_marker_is_on_the_line():
    red_green("C2", top("  StealthNote(this, aArg);"), top("  StealthNote(this, aArg);" + MARK))


def test_c3_the_marker_comment_says_nothing_else():
    red_green("C3", top("  StealthNote(this, aArg);  // STEALTH-HOOK(fingerprint/x) because the page reads it"),
              top("  StealthNote(this, aArg);" + MARK))
    assert "C3" in rules(top("  StealthNote(this, aArg);  // why STEALTH-HOOK(fingerprint/x)"))


def test_c4_no_comment_line_beside_the_hook():
    red_green("C4", top("  // the reason", "  StealthNote(this, aArg);" + MARK),
              top("  StealthNote(this, aArg);" + MARK))


def test_c5_no_logic_in_the_hook():
    red_green("C5", top("  if (StealthX(this) && aArg) return NS_OK;" + MARK), top(GUARD))
    for logic in ("StealthX(this, aArg ? 1 : 2);", "StealthX(this, aArg + 1);", "StealthX(this) || aArg;"):
        assert "C5" in rules(top("  " + logic + MARK)), logic


def test_c6_mozilla_lines_stay_but_for_one_rewritten_line():
    bad_delete = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "-  int x = 1;", "   DoIt(x);", "   DoIt(x);", "   return NS_OK;", " }"])
    bad_rewrite = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "   int x = 1;", "-  DoIt(x);",
                                        "+  DoOther(x);" + MARK, "   DoIt(x);", "   return NS_OK;", " }"])
    for bad in (bad_delete, bad_rewrite):
        assert "C6" in rules(bad), rules(bad)
    two = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "-  int x = 1;", "-  DoIt(x);",
                                "+  Stealth(DoIt(x));" + MARK, "   return NS_OK;", "   Done();", "   More();"])
    assert "C6" in rules(two)
    # the three rewriting forms, one line each
    wrap_expr = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "   int x = 1;", "-  DoIt(x);",
                                      "+  StealthWrap(DoIt(x));" + MARK, "   Done();", "   More();", "   Last();"])
    wrap_fn = patch("dom/Foo.cpp", ["   // lead", " ", "-" + FN, "+nsresult Foo::Bar_Mozilla(int aArg) {" + MARK,
                                    *BODY])
    value = patch("modules/libpref/init/all.js", [" pref(\"a.x\", 1);", "-pref(\"a.b\", false);",
                                                  "+pref(\"a.b\", true);  // STEALTH-HOOK(fingerprint/x)",
                                                  " pref(\"a.y\", 2);", " pref(\"a.z\", 3);", " pref(\"a.w\", 3);"], section="")
    for good in (wrap_expr, wrap_fn, value):
        assert rules(good) == [], (rules(good), good)
    forms = [h.form for p in (wrap_expr, wrap_fn, value) for h in hc.analyse_patch(FOLDER, p)[0]]
    assert forms == ["wrap-expression", "wrap-function", "declared-value"], forms


def test_c7_no_whole_file_deleted_or_replaced():
    gone = patch("dom/Gone.cpp", ["-a", "-b", "-c"], section="", start=1, header="deleted file mode 100644\nindex 1..2\n")
    gone = gone.replace("+0,0", "+0,0")
    assert "C7" in rules(gone)
    swapped = patch("dom/Swap.cpp", ["-line %d" % i for i in range(25)] + ["+new %d" % i for i in range(5)], section="", start=1)
    assert "C7" in rules(swapped)
    assert "C7" not in rules(top(GUARD))


def test_c8_our_include_is_a_block_after_mozillas_separated_by_a_blank_line():
    def inc(*lines):
        return patch("dom/Foo.cpp", [" #include \"a.h\"", " #include \"b.h\"", *lines, " ", " using namespace mozilla;",
                                     " ", " namespace x {"], section="")
    bad = inc("+#include \"StealthX.h\"")
    good = inc("+", "+#include \"StealthX.h\"")
    assert "C8" in rules(bad)
    assert rules(good) == []
    before = patch("dom/Foo.cpp", [" ", "+#include \"StealthX.h\"", " #include \"a.h\"", " #include \"b.h\"", " ", " int k;", " int j;"], section="")
    assert "C8" in rules(before)


def test_c9_not_inside_a_list_nor_the_last_line_of_a_block():
    last = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "   int x = 1;", "   DoIt(x);",
                                 "+  StealthNote(this, aArg);" + MARK, " }", " ", " void Next() {}", " void More() {}"])
    assert "C9" in rules(last)
    assert "C9" not in rules(top("  StealthNote(this, aArg);" + MARK))
    in_list = patch("dom/moz.build", [" UNIFIED_SOURCES = [", "     \"a.cpp\",", "+    \"StealthX.cpp\",", "     \"b.cpp\",", " ]", " ", " X = 1"], section="")
    after = patch("dom/moz.build", [" UNIFIED_SOURCES = [", "     \"a.cpp\",", "     \"b.cpp\",", " ]", "+UNIFIED_SOURCES += [\"StealthX.cpp\"]  # STEALTH-HOOK(fingerprint/x)", " ", " X = 1", " Y = 2", " Z = 3"], section="")
    assert "C9" in rules(in_list)
    assert rules(after) == [], rules(after)


def test_c10_the_called_function_is_named_stealth_what():
    red_green("C10", top("  NoteIt(this, aArg);" + MARK), top("  StealthNoteIt(this, aArg);" + MARK))
    assert "C10" in rules(top("  if (Skip(this)) return NS_OK;" + MARK))
    for snake in ("stealth_note(this);", "nr_stealth_note(this);"):
        assert rules(top("  " + snake + MARK, file="dom/foo.c")) == [], snake


def test_c11_no_value_of_ours_in_a_numbered_space():
    ctx = [" interface nsIFoo : nsISupports {", "   readonly attribute long a;", "   readonly attribute long b;"]
    after = [" ", "   void c();", "   void d();"]
    bad = patch("dom/nsIFoo.idl", [*ctx, "+  const unsigned long STEALTH = 7;  // STEALTH-HOOK(fingerprint/x)", *after], section="")
    good = patch("dom/nsIFoo.idl", [*ctx, "+  void stealth();  // STEALTH-HOOK(fingerprint/x)", *after], section="")
    red_green("C11", bad, good)


def test_forms_are_classified_and_anchors_are_not_refused():
    def forms(text):
        return [h.form for h in hc.analyse_patch(FOLDER, text)[0]]
    assert forms(top(GUARD)) == ["guard"]
    assert forms(top("  StealthNote(this, aArg);" + MARK)) == ["notice"]
    mid = patch("dom/Foo.cpp", ["   // lead", " " + FN, "   int x = 1;", "+  StealthNote(this, &x);" + MARK, "   DoIt(x);",
                                "   DoIt(x);", "   return NS_OK;", " }"])
    assert forms(mid) == ["anchor"] and rules(mid) == []
    member = patch("dom/Foo.h", [" class Foo {", "   void A();", "+  void StealthB();" + MARK, "   void C();", "   void D();", "   int e;"], section="class Foo {")
    assert forms(member) == ["member"] and rules(member) == []
    reg = patch("dom/ipc/PFoo.ipdl", [" parent:", "   async A();", "+  async StealthB();" + MARK, "   async C();", "   async D();", "   async E();"], section="")
    assert forms(reg) == ["registration"] and rules(reg) == []


def test_hook_fields():
    text = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "   int x = 1;", "-  DoIt(x);",
                                 "+  StealthWrap(DoIt(x));  // STEALTH-HOOK(fingerprint/x)  ", "   Done();", "   More();", "   Last();"])
    (h,), _ = hc.analyse_patch(FOLDER, text)
    assert (h.folder, h.file, h.function, h.form) == (FOLDER, "dom/Foo.cpp", FN, "wrap-expression")
    assert h.line == "  StealthWrap(DoIt(x));  // STEALTH-HOOK(fingerprint/x)"      # trailing whitespace stripped
    assert h.removed == "  DoIt(x);" and h.kind == "rewrite" and h.marker == FOLDER


def test_a_moved_hook_keeps_its_key():
    bad = top("  // the reason", "  StealthNote(this, aArg);" + MARK, start=10)
    moved = top("  // the reason", "  StealthNote(this, aArg);" + MARK, start=20)
    keys = [v.key for v in hc.analyse_patch(FOLDER, bad)[1]]
    assert keys and keys == [v.key for v in hc.analyse_patch(FOLDER, moved)[1]]
    assert all("10" not in k.split("|")[-1] for k in keys)
    other = top("  // the reason", "  StealthNote(this, bArg);" + MARK)
    assert keys != [v.key for v in hc.analyse_patch(FOLDER, other)[1]]


def test_identical_hooks_in_one_function_have_distinct_keys():
    twice = top("  StealthNote(this, aArg);", "  StealthNote(this, aArg);")
    keys = [v.key for v in hc.analyse_patch(FOLDER, twice)[1]]
    assert len(keys) == len(set(keys)) and len(keys) >= 2, keys


def test_a_backport_folder_is_exempt(tmp_path):
    for name, backport in (("a/live", False), ("b/port", True)):
        d = tmp_path / name
        d.mkdir(parents=True)
        (d / "hooks.patch").write_text(top("  StealthNote(this, aArg);"), encoding="utf-8", newline="")
        if backport:
            (d / "BACKPORT.json").write_text("{}", encoding="utf-8")
    (tmp_path / "SERIES").write_text("a/live\nb/port\n", encoding="utf-8")
    assert {h.folder for h in hc.series_hooks(tmp_path)} == {"a/live"}
    assert {v.folder for v in hc.contract_violations(tmp_path)} == {"a/live"}


# --------------------------------------------------------------------------- the debt list
def test_the_debt_as_committed_is_exactly_the_violations_of_the_series():
    now = sorted(v.key for v in hc.contract_violations(engine.ROOT))
    debt = [e["key"] for e in json.loads(engine.HOOK_DEBT.read_text(encoding="utf-8"))]
    assert debt == sorted(debt), "tools/hook-debt.json is not sorted"
    assert now == debt
    assert len(set(debt)) == len(debt)


def test_the_debt_file_ends_its_lines_with_lf():
    data = engine.HOOK_DEBT.read_bytes()
    assert b"\r" not in data and data.endswith(b"]\n")
    assert data.decode("utf-8") == hc.debt_text(json.loads(data))


def _v(rule, text):
    return hc.Violation(rule, "f/x", "a.cpp", "void F() {", text, hc._key(rule, "f/x", "a.cpp", "void F() {", text))


def test_debt_against_the_series_and_main():
    a, b, c = _v("C2", "one();"), _v("C2", "two();"), _v("C4", "// three")
    debt = [hc.entry_of(a), hc.entry_of(b)]
    assert hc.debt_problems([a, b], debt, None) == []
    assert hc.debt_problems([a, b], debt, [hc.entry_of(a), hc.entry_of(b), hc.entry_of(c)]) == []
    new = hc.debt_problems([a, b, c], debt, None)
    assert len(new) == 1 and "not in the debt list" in new[0] and "C4" in new[0]
    gone = hc.debt_problems([a], debt, None)
    assert len(gone) == 1 and b.key in gone[0] and "remove it: python tools/engine.py hook-debt" in gone[0]
    grown = hc.debt_problems([a, b], debt, [hc.entry_of(a)])
    assert len(grown) == 1 and b.key in grown[0] and "main" in grown[0]


def test_hook_debt_removes_and_never_adds():
    a, b = _v("C2", "one();"), _v("C2", "two();")
    debt = [hc.entry_of(a), hc.entry_of(b)]
    assert [e["key"] for e in hc.update_debt(debt, [a], init=False)] == [a.key]
    assert [e["key"] for e in hc.update_debt([hc.entry_of(a)], [a, b], init=False)] == [a.key]
    assert sorted(e["key"] for e in hc.update_debt([], [a, b], init=True)) == sorted([a.key, b.key])


def test_check_refuses_a_new_violation_and_a_stale_entry(tmp_path, monkeypatch, capsys):
    debt = json.loads(engine.HOOK_DEBT.read_text(encoding="utf-8"))
    path = tmp_path / "hook-debt.json"
    monkeypatch.setattr(engine, "HOOK_DEBT", path)
    hc.write_debt(path, debt[1:])                       # one violation not listed
    assert engine.check() == 1
    assert "not in the debt list" in capsys.readouterr().out
    hc.write_debt(path, debt + [dict(debt[0], key="C2|x|y|z|000000000000")])     # one entry gone
    assert engine.check() == 1
    assert "no longer occurs" in capsys.readouterr().out
    hc.write_debt(path, debt)
    assert engine.check() == 0
    assert "hook contract:" in capsys.readouterr().out

