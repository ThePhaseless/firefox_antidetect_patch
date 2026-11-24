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
                                 "+  mState = StealthState();" + MARK, " }", " ", " void Next() {}", " void More() {}"])
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
    # port-06 rules (C12..C15) are never debt: they are fixed by the engine change and the HOOKS.json fields
    now = sorted(v.key for v in hc.contract_violations(engine.ROOT) if v.rule not in hc.PORT06_RULES)
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
    # whatever debt the series has, none at all once it is paid: one violation is added to the series' own
    real = [v for v in hc.contract_violations(engine.ROOT) if v.rule not in hc.PORT06_RULES]     # port-06 rules are never debt
    text = "  x = StealthX(this) + 1;"
    extra = hc.Violation("C5", "fingerprint/x", "dom/X.cpp", "void X()", text,
                         hc._key("C5", "fingerprint/x", "dom/X.cpp", "void X()", text))
    debt = hc.update_debt([], real, init=True)
    path = tmp_path / "hook-debt.json"
    monkeypatch.setattr(engine, "HOOK_DEBT", path)
    monkeypatch.setattr(hc, "contract_violations", lambda root: real + [extra])
    hc.write_debt(path, debt)                           # one violation not listed
    assert engine.check() == 1
    assert "not in the debt list" in capsys.readouterr().out
    monkeypatch.setattr(hc, "contract_violations", lambda root: real)
    hc.write_debt(path, debt + hc.update_debt([], [extra], init=True))     # one entry gone
    assert engine.check() == 1
    assert "no longer occurs" in capsys.readouterr().out
    hc.write_debt(path, debt)
    assert engine.check() == 0
    assert "hook contract:" in capsys.readouterr().out



# --------------------------------------------------------------------------- the pm's forms (PM-DECISIONS.md)
def rewrite(removed, added, file="dom/Foo.cpp", section=FN):
    """One Mozilla line rewritten, with context on both sides."""
    return patch(file, ["   // lead", " ", " " + section, "   int x = 1;", "-" + removed, "+" + added + MARK,
                        "   Done();", "   More();", "   Last();"], section=section)


def forms_of(text):
    return [h.form for h in hc.analyse_patch(FOLDER, text)[0]]


def test_wrap_expression_of_a_sub_expression():
    cases = {       # Mozilla's line -> our line: removing our call and its extra leading arguments gives Mozilla's line back
        "  mReduction = aReduction;": "  mReduction = StealthPerturbCompressorReduction(aReduction);",
        "  auto x = Expr(a, b);": "  auto x = StealthWrap(this, Expr(a, b));",
        "  return aValue;": "  return CanvasUtils::StealthProject(this, aArg, aValue);",
        "  rv = loadInfo->SetOriginAttributes(attrs);": "  rv = loadInfo->SetOriginAttributes(mozilla::net::StealthRequestAttributes(mOriginAttributes, attrs));",
        "  sts_thread_, attrs, getter_AddRefs(r))) {": "  sts_thread_, StealthLookupAttributes(this, attrs), getter_AddRefs(r))) {",
        "  PR_AF_INET, OriginAttributes(), 0, mFD,": "  PR_AF_INET, StealthTransportContext(this, OriginAttributes()), 0, mFD,",
        "  NS_SUCCEEDED(ResolveProxy())) {": "  NS_SUCCEEDED(nr_stealth_proxy_lookup(this, ResolveProxy()))) {",
    }
    for removed, added in cases.items():
        assert rules(rewrite(removed, added)) == [], (added, rules(rewrite(removed, added)))
        assert forms_of(rewrite(removed, added)) == ["wrap-expression"], added
    # red: the expression of Mozilla is altered, or the extra argument comes after it, or the call is not ours
    for removed, added in (("  mReduction = aReduction;", "  mReduction = StealthPerturb(aReduction * 2);"),
                           ("  mReduction = aReduction;", "  mReduction = StealthPerturb(aReduction, this);"),
                           ("  mReduction = aReduction;", "  mReduction = Perturb(aReduction);"),
                           ("  mReduction = aReduction;", "  mReduction = StealthPerturb(bReduction);"),
                           ("  auto x = Expr(a, b);", "  auto y = StealthWrap(Expr(a, b));")):
        assert "C6" in rules(rewrite(removed, added)), added
    # the logic and the name rules look at our call: extra arguments with logic, a Stealth call that is not first
    assert "C5" in rules(rewrite("  mReduction = aReduction;", "  mReduction = StealthPerturb(this + 1, aReduction);"))


def test_wrap_call_g29_changes_only_the_called_name():
    ok = {"  MozFn(a, b);": "  StealthMozFn(a, b);",
          "  rv = obj->MozFn(a, b);": "  rv = obj->StealthMozFn(a, b);",
          "  rv = MozFn(a, b);": "  rv = mozilla::StealthMozFn(a, b);",
          "  nr_ice_get_addrs(ctx, 1);": "  nr_stealth_get_addrs(ctx, 1);"}
    for removed, added in ok.items():
        assert rules(rewrite(removed, added)) == [], added
        assert forms_of(rewrite(removed, added)) == ["wrap-call"], added
    for removed, added in (("  MozFn(a, b);", "  StealthMozFn(a);"),                 # an argument gone
                           ("  MozFn(a, b);", "  StealthMozFn(this, x, y, z, a, b);"),   # four arguments added: not a call wrap
                           ("  MozFn(a, b);", "  OtherFn(a, b);"),                    # not a Stealth name
                           ("  MozFn(a, b);", "  StealthA(a, StealthB(b));"),
                           ("  MozFn(a, b);", "  Stealth_x;")):
        assert "C6" in rules(rewrite(removed, added)), added


def test_wrap_function_renames_g1_g2_by_a_suffix():
    for removed, added in (("nsresult Foo::Bar(int aArg) {", "nsresult Foo::Bar_Mozilla(int aArg) {"),
                           ("already_AddRefed<S> Off::GetSurfaceSnapshot(", "already_AddRefed<S> Off::GetSurfaceSnapshotAsDrawn("),
                           ("  RefPtr<S> surface = GetSurfaceSnapshot();", "  RefPtr<S> surface = GetSurfaceSnapshotAsDrawn();"),
                           ("  return mDisplay->GetSurfaceSnapshot();", "  return mDisplay->GetSurfaceSnapshotAsDrawn();"),
                           ("#define FOR_EACH_X(f) \\", "#define FOR_EACH_X_MOZILLA(f) \\")):
        text = rewrite(removed, added)
        assert rules(text) == [] and forms_of(text) == ["wrap-function"], (added, rules(text), forms_of(text))
    for removed, added in (("  RefPtr<S> surface = GetSurfaceSnapshot();", "  RefPtr<S> surface = MyGetSurfaceSnapshot();"),   # not a suffix
                           ("  RefPtr<S> surface = GetSurfaceSnapshot();", "  RefPtr<S> surface = GetSurfaceSnapshotAsDrawn(a);"),  # arguments
                           ("  RefPtr<S> surface = GetSurfaceSnapshot();", "  RefPtr<S> shot = GetSurfaceSnapshotAsDrawn();"),  # two changes
                           ("  mSize = kSize;", "  mSize = kSizeLarge;")):                                                          # a value, not a function
        assert "C6" in rules(rewrite(removed, added)), added


def test_the_declarations_of_a_renamed_function_are_part_of_the_wrap():
    decl = "  already_AddRefed<S> GetSurfaceSnapshotAsDrawn(bool aA) const;" + MARK
    rename = patch("dom/Foo.cpp", ["   // lead", " ", "-already_AddRefed<S> Foo::GetSurfaceSnapshot(", "+already_AddRefed<S> Foo::GetSurfaceSnapshotAsDrawn(" + MARK,
                                   "     bool aA) {", "   Done();", "   More();", "   Last();"], section="")
    header = patch("dom/Foo.h", [" class Foo {", "   void A();", "+" + decl, "   void C();", "   void D();", "   int e;"], section="class Foo {")
    assert [h.form for h in hc.analyse_patch(FOLDER, rename + header)[0]] == ["wrap-function", "wrap-function"]
    assert rules(rename + header) == []
    assert forms_of(header) == ["member"]          # without the rename in the patch it is a member, not a wrap


def test_guards_with_a_value_g15():
    for text in (top("  if (nsresult rv; StealthGetX(this, aArg, &rv)) return rv;" + MARK),
                 top("  if (StealthOwnsX()) return StealthX(aArg);" + MARK)):
        assert rules(text) == [] and forms_of(text) == ["guard"], text
    mid = patch("dom/Foo.cpp", ["   // lead", " " + FN, "   int x = 1;", "+  if (StealthOwnsX()) return StealthX(aArg);" + MARK,
                                "   DoIt(x);", "   DoIt(x);", "   return NS_OK;", " }"])
    assert forms_of(mid) == ["anchor"] and rules(mid) == []
    red_green("C5", top("  if (nsresult rv; StealthGetX(this, &rv) && aArg) return rv;" + MARK),
              top("  if (nsresult rv; StealthGetX(this, aArg, &rv)) return rv;" + MARK))
    assert "C10" in rules(top("  if (OwnsX()) return StealthX(aArg);" + MARK))


def test_the_shadow_g21_is_a_declaration_at_the_top_of_a_function():
    good = top("  const auto GetX = StealthGetX;" + MARK)
    assert forms_of(good) == ["shadow"] and rules(good) == []
    assert forms_of(top("  auto& GetY = mozilla::StealthGetY;" + MARK)) == ["shadow"]
    mid = patch("dom/Foo.cpp", ["   // lead", " " + FN, "   int x = 1;", "+  const auto GetX = StealthGetX;" + MARK,
                                "   DoIt(x);", "   DoIt(x);", "   return NS_OK;", " }"])
    assert forms_of(mid) == ["unknown"]                   # not at the top: not a shadow
    assert forms_of(top("  const auto GetX = GetY;" + MARK)) == ["unknown"]     # not our value


def test_a_forward_declaration_and_a_declaration_of_ours_are_registrations_g40():
    def at_scope(line):
        return patch("dom/Foo.cpp", [" #include \"a.h\"", " ", " namespace mozilla {", "+" + line + MARK, " ", " class Y {", " };",
                                     " int z;"], section="")
    for line in ("class StealthX;", "struct StealthY;", "bool StealthX(int aArg);", "static nsresult mozilla::StealthZ(const nsACString&);"):
        assert forms_of(at_scope(line)) == ["registration"] and rules(at_scope(line)) == [], line
    assert forms_of(at_scope("StealthX(aArg);")) == ["anchor"]            # a call is not a declaration
    assert forms_of(at_scope("bool Other(int aArg);")) == ["unknown"]     # not ours


def test_an_anchor_at_the_end_of_a_block_or_of_a_js_module_is_allowed_g30_g33():
    end = patch("dom/Foo.cpp", ["   // lead", " " + FN, "   int x = 1;", "   DoIt(x);", "+  StealthNote(this, aArg);" + MARK, " }", " ",
                                " void Next() {}", " void More() {}"])
    assert forms_of(end) == ["anchor"] and rules(end) == []
    js = patch("toolkit/Foo.sys.mjs", [" export function a() {", "   return 1;", " }", " ", "+StealthInstall(this);" + MARK], section="", start=40)
    assert forms_of(js) == ["anchor"] and rules(js) == []
    # the other forms keep C9 there, and so do the entries of a list
    member = patch("dom/Foo.h", [" class Foo {", "   void A();", "   void C();", "+  void StealthB();" + MARK, " };", " ", " int k;", " int j;"], section="class Foo {")
    assert "C9" in rules(member)


def test_a_multi_line_mozilla_expression_wrapped_stays_a_violation():
    two = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "   int x = 1;", "-  aData[i] = Convert(", "-      mBuffer[i], -inf);",
                                "+  aData[i] = StealthBin(i, Convert(" + MARK, "+      mBuffer[i], -inf));", "   Done();", "   More();", "   Last();"])
    assert "C6" in rules(two) and "C1" in rules(two), rules(two)
    assert "wrap-expression" not in forms_of(two)


# --------------------------------------------------------------------------- second pass: G9, `*` lines, G41, G2 marker, G7 names
def test_g9_one_argument_of_ours_added_to_a_call_of_mozilla_is_a_call_wrap():
    cases = {
        "  rv = ResolveProxy(a, Nothing());": "  rv = ResolveProxy(a, Nothing(), StealthCtx(mLoadInfo));",
        "  Foo(a, b);": "  Foo(StealthX(this), a, b);",
        "  Foo(a, b);": "  Foo(a, StealthX(this), b);",
        "  Foo();": "  Foo(StealthX(this));",
        "      getter_AddRefs(proxyRequest));": "      getter_AddRefs(proxyRequest), mozilla::net::StealthCtx(mLoadInfo));",
    }
    for removed, added in cases.items():
        text = rewrite(removed, added)
        assert rules(text) == [] and forms_of(text) == ["wrap-call"], (added, rules(text), forms_of(text))
    for removed, added in (("  Foo(a, b);", "  Foo(a, b, StealthX(this), StealthY(this));"),      # two arguments of ours
                           ("  Foo(a, b);", "  Foo(a, b, c);"),                                   # the argument is not ours
                           ("  Foo(a, b);", "  Foo(a, b, StealthX(this + 1));"),                  # logic in it
                           ("  Foo(a, b);", "  Foo(a, c, StealthX(this));"),                      # Mozilla's argument changed
                           ("  Foo(a, b);", "  Foo(a, b, StealthX(this)) + 1;")):
        assert "C6" in rules(rewrite(removed, added)), added


def test_a_line_starting_with_a_star_is_code_unless_it_continues_a_block_comment():
    for code in ("  *aSurface = StealthProject(aSurface);", "  *sock = StealthWrap(sock);"):
        assert rules(top(code + MARK)) == [], code
        assert not hc.is_comment_line(code, "cpp")
    red_green("C4", top("  * the reason", "  StealthNote(this, aArg);" + MARK), top("  StealthNote(this, aArg);" + MARK))
    for comment in (" * text", " *", " */", "/* text */", "// text"):
        assert hc.is_comment_line(comment, "cpp"), comment
    # a rewrite of a dereferencing line is a wrap
    text = rewrite("  *aSurface = snapshot;", "  *aSurface = StealthProject(this, snapshot);")
    assert rules(text) == [] and forms_of(text) == ["wrap-expression"]


def test_c10_only_a_new_function_must_be_stealth_named_g41(monkeypatch):
    monkeypatch.setattr(hc, "_known_names", {"CSP_IsBypassedFor", "SessionSystemLocales"})
    red_green("C10", top("  if (CSP_IsBypassedForNew(this)) return NS_OK;" + MARK), top("  if (CSP_IsBypassedFor(this)) return NS_OK;" + MARK))
    assert rules(top("  if (nsContentUtils::SessionSystemLocales(this)) return NS_OK;" + MARK)) == []      # the last segment is known
    assert rules(top("  SessionSystemLocales(this, aArg);" + MARK)) == []
    assert "C10" in rules(top("  NoteIt(this, aArg);" + MARK))
    assert rules(top("  StealthNote(this, aArg);" + MARK)) == []
    monkeypatch.setattr(hc, "_known_names", set())
    assert "C10" in rules(top("  SessionSystemLocales(this, aArg);" + MARK))


def test_the_committed_names_of_existing_functions():
    names = json.loads(hc.KNOWN_NAMES_FILE.read_text(encoding="utf-8"))
    assert names == sorted(set(names)) and names, "tools/hook-names.json is sorted and not empty"
    assert not any(hc.is_stealth_chain(n) for n in names)
    assert "stealthApplyContext" in hc.known_names() and hc.is_known_name("obj->stealthApplyContext")
    assert not hc.is_known_name("NotAnExistingFunction")


def test_a_marker_block_comment_before_the_backslash_of_a_macro_line_is_the_marker_g2():
    def macro(added):
        return patch("dom/Foo.h", [" #define OTHER(f) \\", " ", "-#define FOR_EACH_X(f) \\", "+" + added, "   f(A) \\", "   f(B) \\",
                                   "   f(C)"], section="")
    good = macro("#define FOR_EACH_X_MOZILLA(f) /* STEALTH-HOOK(fingerprint/x) */ \\")
    assert hc.marker_split("#define FOR_EACH_X_MOZILLA(f) /* STEALTH-HOOK(fingerprint/x) */ \\") == \
        ("#define FOR_EACH_X_MOZILLA(f) \\", FOLDER, "")
    assert rules(good) == [] and forms_of(good) == ["wrap-function"], (rules(good), forms_of(good))
    assert "C3" in rules(macro("#define FOR_EACH_X_MOZILLA(f) /* because STEALTH-HOOK(fingerprint/x) */ \\"))
    assert "C3" in rules(macro("#define FOR_EACH_X_MOZILLA(f) /* STEALTH-HOOK(fingerprint/x) because */ \\"))
    assert "C2" in rules(macro("#define FOR_EACH_X_MOZILLA(f) \\"))


def test_a_qualified_callee_is_stealth_named_in_every_form_g7():
    for name in ("Class::StealthFn", "ns::Class::StealthFn", "mozilla::net::nr_stealth_fn", "obj->StealthFn"):
        assert hc.is_stealth_chain(name), name
    q = "mozilla::dom::Cls::StealthFn"
    guard = top("  if (%s(this, aArg)) return NS_OK;" % q + MARK)
    notice = top("  %s(this, aArg);" % q + MARK)
    mid = patch("dom/Foo.cpp", ["   // lead", " " + FN, "   int x = 1;", "+  %s(this, &x);" % q + MARK, "   DoIt(x);", "   DoIt(x);",
                                "   return NS_OK;", " }"])
    expr = rewrite("  x = aArg;", "  x = %s(this, aArg);" % q)
    sub = rewrite("  NS_SUCCEEDED(ResolveProxy())) {", "  NS_SUCCEEDED(%s(this, ResolveProxy()))) {" % q)
    call = rewrite("  rv = Foo(a);", "  rv = Cls::StealthFoo(a);")
    arg = rewrite("  rv = Foo(a);", "  rv = Foo(a, %s(this));" % q)
    shadow = top("  const auto GetX = %s;" % q + MARK)
    decl = patch("dom/Foo.cpp", [" #include \"a.h\"", " ", " namespace mozilla {", "+bool %s(int aArg);" % q + MARK, " ", " class Y {", " };", " int z;"], section="")
    for text, form in ((guard, "guard"), (notice, "notice"), (mid, "anchor"), (expr, "wrap-expression"), (sub, "wrap-expression"),
                       (call, "wrap-call"), (arg, "wrap-call"), (shadow, "shadow"), (decl, "registration")):
        assert rules(text) == [] and forms_of(text) == [form], (form, rules(text), forms_of(text))


# --------------------------------------------------------------------------- third pass: adjacent one-line hooks (C1)
def test_c1_two_adjacent_complete_marked_lines_are_two_hooks():
    one = "  StealthNote(this, aArg);" + MARK
    two = "  if (StealthOwns(this)) return NS_OK;" + MARK
    good = top(one, two)
    assert rules(good) == [] and forms_of(good) == ["notice", "guard"]
    assert [h.run for h in hc.analyse_patch(FOLDER, good)[0]] == [2, 2]
    # a statement of ours split over two lines (marker on both, or on one): one hook of two lines
    split_both = top("  StealthNote(this," + MARK, "                aArg);" + MARK)
    split_first = top("  StealthNote(this," + MARK, "                aArg);")
    for bad in (split_both, split_first):
        assert "C1" in rules(bad), rules(bad)
    # a line of ours without a marker that is part of a run
    assert "C1" in rules(top(one, "  StealthMore(this);"))
    assert "C1" in rules(top("  StealthMore(this);", one))
    assert "C1" in rules(top("  if (StealthOwns(this)) {" + MARK, "    return NS_OK;", "  }"))
    assert "C1" in rules(top("  if (StealthOwns(this))" + MARK, "    return NS_OK;" + MARK))     # a bare `if`: not complete
    # the rest of the contract is judged line by line in the run
    assert "C5" in rules(top(one, "  StealthNote(this, aArg + 1);" + MARK))
    assert "C10" in rules(top(one, "  NoteIt(this);" + MARK))
    assert "C3" in rules(top(one, "  StealthMore(this);  // STEALTH-HOOK(fingerprint/x) why"))


def test_c1_includes_and_build_additions_in_a_run_stay_fine():
    inc = patch("dom/Foo.cpp", [" #include \"a.h\"", " ", "+#include \"StealthX.h\"", "+#include \"StealthY.h\"", " ", " using namespace mozilla;", " ",
                                " namespace x {"], section="")
    assert "C1" not in rules(inc)


# --------------------------------------------------------------------------- the classifier gaps the pm ruled (G1, G9, G23, G30, G41, G50, G53)
def test_g50_a_marker_alone_before_a_directive_of_a_preprocessed_file_is_one_hook():
    def prefs(*lines, file="modules/libpref/greprefs.js"):
        return patch(file, [" // Do not add anything else.", " ", " #include init/all.js", *lines], section="", start=3)
    good = prefs("+// STEALTH-HOOK(platform/prefs)", "+#include init/StealthPrefs.js")
    assert rules(good) == [] and forms_of(good) == ["registration"]
    assert [h.line for h in hc.analyse_patch(FOLDER, good)[0]] == ["#include init/StealthPrefs.js"]
    assert rules(prefs("+// STEALTH-HOOK(platform/prefs)", "+#include init/StealthPrefs.js", file="a.json")) == []
    # red: the same two lines in a C++ file, a marker before a line that is not a directive, a note beside the marker
    assert rules(prefs("+// STEALTH-HOOK(platform/prefs)", '+#include "StealthPrefs.h"', file="dom/A.cpp"))
    assert rules(prefs("+// STEALTH-HOOK(platform/prefs)", '+pref("a.b", 1);'))
    assert rules(prefs("+// STEALTH-HOOK(platform/prefs): our defaults", "+#include init/StealthPrefs.js"))
    assert rules(prefs("+#include init/StealthPrefs.js"))      # no marker at all


def test_g41_mozillas_own_macros_are_not_the_called_name_of_a_hook_and_the_known_names_are_known():
    for call in ("MOZ_RELEASE_ASSERT(a == b);", "ABORT(a);", "NS_ENSURE_SUCCESS(rv, rv);"):
        assert rules(top("  " + call + MARK)) == [], call
    assert "C10" in rules(top("  OtherApi(a);" + MARK))
    assert "C10" in rules(top("  MOZ_RELEASE_ASSERT(OtherApi(a));" + MARK))
    for name in ("CSP_IsBypassedFor", "SessionSystemLocale", "SessionSystemLocales", "WorkerLocaleLanguage",
                 "SeedDeclaredTimezoneAndLanguage", "SetDeclaredRealmTimeAndLanguage"):
        assert hc.is_known_name(name), name
        assert rules(top("  " + name + "(this);" + MARK)) == [], name


def test_c11_a_webidl_dictionary_default_is_not_a_numbered_space():
    def idl(line):
        return patch("dom/webidl/Window.webidl", ["   // lead", "   dictionary D {", "+" + line + "  // STEALTH-HOOK(fingerprint/x)",
                                                  "   };"], section="dictionary D {")
    assert "C11" not in rules(idl("  unsigned long jugglerEventId = 0;"))
    assert "C11" not in rules(idl("  double latency = 0;"))
    assert "C11" in rules(idl("  const unsigned short FOO = 4;"))


def test_c5_logic_is_judged_in_the_part_that_is_ours():
    text = rewrite('  const char* f = a() ? a() : "debugger eval code";', '  const char* f = a() ? a() : "eval code";')
    assert forms_of(text) == ["declared-value"] and rules(text) == []
    text = rewrite("  x = Mozilla(a);", "  x = StealthWrap(a) ? Mozilla(a) : b;")
    assert rules(text)          # a ternary of ours is still logic


def test_g9_partial_line_of_a_multi_line_call_adds_one_plain_argument():
    for removed, added in (("  aLastModified);", "  this, aLastModified);"), ("  mLastModified);", "  this, mLastModified);"),
                           ("  aTime,", "  this, aTime,")):
        text = rewrite(removed, added)
        assert rules(text) == [] and forms_of(text) == ["wrap-call"], (added, rules(text), forms_of(text))
    for removed, added in (("  aLastModified);", "  this, x, aLastModified);"),        # two arguments of ours
                           ("  aLastModified);", "  this, bLastModified);"),            # Mozilla's text changed
                           ("  Foo(aLastModified);", "  this, Foo(aLastModified);")):  # not the end of a call that spans lines
        assert "C6" in rules(rewrite(removed, added)), added


def test_g29_g9_the_called_function_replaced_and_plain_arguments_added():
    ok = {"  const auto l = ShaderOutput(gl);": "  const auto l = StealthShaderOutputLanguage(gl, mStealthPerPage);",
          "  MozFn(a, b);": "  StealthMozFn(this, a, b);",
          "  rv = obj->MozFn(a);": "  rv = obj->StealthMozFn(a, mX);"}
    for removed, added in ok.items():
        text = rewrite(removed, added)
        assert rules(text) == [] and forms_of(text) == ["wrap-call"], (added, rules(text), forms_of(text))
    for removed, added in (("  MozFn(a, b);", "  StealthMozFn(x, y, a, b);"),           # two arguments of ours
                           ("  status = PR_Connect(fd, &p, T);", "  status = StealthConnect(mNetAddr, mProxyTransparent, mProxyHost, fd, &p, T);"),
                           ("  MozFn(a, b);", "  StealthMozFn(this, a, b, x);"),
                           ("  MozFn(a, b);", "  StealthMozFn(x, a, b, y);"),
                           ("  MozFn(a, b);", "  StealthMozFn(this, b, a);"),           # reordered
                           ("  MozFn(a, b);", "  StealthMozFn(this, x + 1, a, b);"),    # logic in one
                           ("  MozFn(a, b);", "  StealthMozFn(this, G(), a, b);"),      # a call in one
                           ("  MozFn(a, b);", "  StealthMozFn(this, a, c);"),           # Mozilla's argument changed
                           ("  MozFn(a, b);", "  OtherFn(this, a, b);"),                # not a Stealth name
                           ("  o->MozFn(a);", "  StealthMozFn(o, a);"),                 # the object is gone: not this form
                           ("  MozFn(a, b);", "  StealthMozFn(this, a, b) + 1;")):      # the rest of the line changed
        assert "C6" in rules(rewrite(removed, added)), added


def test_g1_a_rename_on_a_definition_line_may_drop_static():
    text = rewrite("static ShShaderOutput ShaderOutput(gl::GLContext* gl) {", "ShShaderOutput ShaderOutputForDriver(gl::GLContext* gl) {")
    assert forms_of(text) == ["wrap-function"] and rules(text) == []
    assert "C6" in rules(rewrite("static ShShaderOutput ShaderOutput(gl::GLContext* gl) {",
                                 "ShShaderOutput ShaderOutputForDriver(gl::GLContext* gl, int x) {"))


def test_a_literal_for_a_literal_or_one_macro_of_ours_for_a_token_is_a_declared_value():
    cases = {"    aLineBreak.AssignLiteral(NS_ULINEBREAK);": "    aLineBreak.AssignLiteral(STEALTH_NATIVE_ULINEBREAK);",
             '    rv = F(type, ""_ns, 1);': '    rv = F(type, "x"_ns, 2);',
             "    rv = F(a, 1);": "    rv = F(a, STEALTH_X);"}
    for removed, added in cases.items():
        text = rewrite(removed, added)
        assert forms_of(text) == ["declared-value"] and rules(text) == [], (added, rules(text), forms_of(text))
    for removed, added in (("#ifdef XP_WIN", "#if STEALTH_NATIVE_EOL_IS_CRLF"),                 # a directive changed: not one token
                           ('    rv = F(type, ""_ns, ""_ns, ""_ns, ""_ns,', '    rv = F(type, ""_ns, mUser, mPass, ""_ns,'),   # a field in place of a literal
                           ("#ifdef XP_WIN", "#if OTHER_MACRO"), ("#ifdef XP_WIN", "#if STEALTH_X && FOO"),
                           ("    A(NS_ULINEBREAK);", "    A(OTHER_ULINEBREAK);"),
                           ("    A(NS_ULINEBREAK, 1);", "    A(STEALTH_ULINEBREAK, 2);"),
                           ("    rv = F(a, b);", "    rv = F(a, c);")):              # a name replaced by a name: not a value
        assert "C6" in rules(rewrite(removed, added)), added


G53_OPEN = "      StealthWithContentOrigin(aPresContext,  // STEALTH-HOOK(fingerprint/x)"
G53_MID = ["      LayoutDevicePixel::ToAppUnits(", "          guiEvent->mWidget->TopLevelWidgetToScreenOffset(),"]
G53_CLOSE_OLD = "          aPresContext->DeviceContext()->AppUnitsPerDevPixel()));"
G53_CLOSE_NEW = "          aPresContext->DeviceContext()->AppUnitsPerDevPixel())));  // STEALTH-HOOK(fingerprint/x)"


def g53(open_line=G53_OPEN, mid=G53_MID, close_new=G53_CLOSE_NEW, changed_mid=None):
    lines = ["   const CSSPoint pt = CSSPixel::FromAppUnits(", "       topLevelPoint +", "+" + open_line, *[" " + m for m in mid]]
    if changed_mid:
        lines = lines[:-1] + ["-" + mid[-1], "+" + changed_mid]
    lines += ["-" + G53_CLOSE_OLD, "+" + close_new, "   return Some(pt);"]
    return patch("dom/events/Event.cpp", lines, section="Maybe<X> Event::GetScreenCoords(")


def test_g53_a_multi_line_wrap_opened_by_an_added_line_and_closed_by_the_rewritten_last_line():
    text = g53()
    assert rules(text) == [] and forms_of(text) == ["wrap-expression", "wrap-expression"]
    # red: the opener has no marker, the closer has none, a middle line of Mozilla's changes, the closer changes more
    assert rules(g53(open_line="      StealthWithContentOrigin(aPresContext,"))
    assert rules(g53(close_new="          aPresContext->DeviceContext()->AppUnitsPerDevPixel())));"))
    assert "C6" in rules(g53(changed_mid="          guiEvent->mWidget->Other(),"))
    assert "C6" in rules(g53(close_new=G53_CLOSE_NEW.replace("AppUnitsPerDevPixel()", "AppUnitsPerDevPixel(1)")))
    assert "C6" in rules(g53(close_new=G53_CLOSE_NEW.replace("())));", "()));")))       # no `)` of ours: no wrap
    assert "C6" in rules(g53(open_line="      OtherCall(aPresContext,  // STEALTH-HOOK(fingerprint/x)"))   # not our call


def test_g41_a_wrap_whose_callee_is_an_existing_name_of_ours_is_the_same_form_as_a_stealth_named_one():
    ok = {"  return aPopup ? CHROME_MINIMAL_POPUP": "  return aPopup ? mozilla::JugglerPopupChromeFlags(aFeatures, CHROME_MINIMAL_POPUP)",
          "  auto x = Expr(a, b);": "  auto x = SessionSystemLocale(this, Expr(a, b));",
          "  Foo(a, b);": "  Foo(a, b, WorkerLocaleLanguage(this));",
          "  rv = MozFn(a);": "  rv = SessionSystemLocales(a);"}
    for removed, added in ok.items():
        text = rewrite(removed, added)
        assert rules(text) == [], (added, rules(text))
        assert forms_of(text) in (["wrap-expression"], ["wrap-call"]), (added, forms_of(text))
    # red: the same shape with a callee that is neither Stealth-named nor listed in hook-names.json
    for removed, added in (("  return aPopup ? CHROME_MINIMAL_POPUP", "  return aPopup ? mozilla::OtherPopupFlags(aFeatures, CHROME_MINIMAL_POPUP)"),
                           ("  auto x = Expr(a, b);", "  auto x = NotListed(this, Expr(a, b));"),
                           ("  Foo(a, b);", "  Foo(a, b, NotListed(this));"),
                           ("  rv = MozFn(a);", "  rv = NotListed(a);")):
        assert rules(rewrite(removed, added)) != [], added


# --------------------------------------------------------------------------- G53 across two hunks of one file
G53H_OPEN = "      StealthDeclaredEnumeration(  // STEALTH-HOOK(fingerprint/x)"
G53H_CLOSE_OLD = "          },"
G53H_CLOSE_NEW = "          }),  // STEALTH-HOOK(fingerprint/x)"
G53H_A = ["       GetCurrentSerialEventTarget(), __func__,"]
G53H_MID = ["          [self = RefPtr(this)](RefPtr<D> aDevices) mutable {", "            Work();", "            More();"]
G53H_B = ["          [](RefPtr<E>&& reason) {", "            Unreachable();", "          });"]


def hunk_at(old_start, new_start, lines, section="RefPtr<P> M::GetPhysicalDevices() {"):
    old = sum(1 for l in lines if l[0] in " -")
    new = sum(1 for l in lines if l[0] in " +")
    return "@@ -%d,%d +%d,%d @@ %s\n%s\n" % (old_start, old, new_start, new, section, "\n".join(lines))


def g53_two_hunks(open_line=G53H_OPEN, close_new=G53H_CLOSE_NEW, with_open=True, with_close=True, between=None):
    """The two ends of a G53 wrap in two hunks of one file, as git cuts them when the lines between are far apart."""
    f = "dom/media/MediaManager.cpp"
    out = "diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n" % (f, f, f, f)
    new_off = 0
    if with_open:
        out += hunk_at(100, 100, ["   Then(", *[" " + a for a in G53H_A], "+" + open_line, *[" " + m for m in G53H_MID[:1]]])
        new_off += 1
    if between:
        out += hunk_at(110 + 0, 110 + new_off, [" " + G53H_MID[1], "-" + G53H_MID[2], "+" + between, " " + G53H_B[0]])
    if with_close:
        out += hunk_at(130, 130 + new_off, [" " + G53H_MID[2], " " + "          }", "-" + G53H_CLOSE_OLD,
                                            "+" + close_new, *[" " + b for b in G53H_B]])
    return out


def test_g53_pairs_the_two_ends_across_two_hunks_of_one_file():
    text = g53_two_hunks()
    assert text.count("\n@@ ") == 2 and rules(text) == [] and forms_of(text) == ["wrap-expression", "wrap-expression"]


def test_g53_an_unpaired_end_across_hunks_fails():
    assert rules(g53_two_hunks(with_close=False)), "an opener with no closer"
    only_close = g53_two_hunks(with_open=False)
    assert "C6" in rules(only_close), "a closer with no opener"
    assert rules(g53_two_hunks(open_line="      StealthDeclaredEnumeration(")), "no marker on the opener"
    assert "C6" in rules(g53_two_hunks(open_line="      OtherCall(  // STEALTH-HOOK(fingerprint/x)"))


def test_g53_a_changed_mozilla_line_between_the_ends_fails():
    text = g53_two_hunks(between="            Changed();")
    assert text.count("\n@@ ") == 3
    assert "C6" in rules(text)
