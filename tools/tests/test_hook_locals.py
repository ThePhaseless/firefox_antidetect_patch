"""C16, hook-02 point 3: a hook passes no local of Mozilla's function as an argument, except in an anchor. The locals are read
from the lines the hunks show of the function (and, with a `base`, from the whole function in the base file).

    python -m pytest tools/tests/test_hook_locals.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hook_contract as hc  # noqa: E402

FOLDER = "automation/hybrid-xrays"
MK = "  // STEALTH-HOOK(automation/hybrid-xrays)"


def hunk(old_start, new_start, lines, section):
    old = sum(1 for l in lines if l[0] in " -")
    new = sum(1 for l in lines if l[0] in " +")
    return "@@ -%d,%d +%d,%d @@ %s\n%s\n" % (old_start, old, new_start, new, section, "\n".join(lines))


def patch(file, *hunks):
    return "diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n%s" % (file, file, file, file, "".join(hunks))


def names(text, base=None):
    return sorted(n for v in hc.analyse_locals(FOLDER, text, base) for n in v.detail.split(": ", 1)[1].split(", "))


REWRAP = "JSObject* WrapperFactory::Rewrap(JSContext* cx, HandleObject existing,"

# the shape of main's WrapperFactory hunk: a rewrite whose added lines use three locals Mozilla's function declares
WRAPPER_FACTORY = patch("js/xpconnect/wrappers/WrapperFactory.cpp", hunk(560, 560, [
    "     XrayType xrayType = wantXrays ? GetXrayType(obj) : NotXray;",
    "     bool securityWrapper = IsSecurityWrapper(obj);",
    "     bool waiveXrays = HasWaiveXrayFlag(obj);",
    " ",
    "-    wrapper = SelectWrapper(securityWrapper, xrayType, waiveXrays, obj);",
    "+    // STEALTH-HOOK(automation/hybrid-xrays)",
    "+    wrapper = StealthTargetIsHybrid(cx) && !securityWrapper && !waiveXrays",
    "+                  ? StealthHybridWrapper(xrayType)",
    "+                  : SelectWrapper(securityWrapper, xrayType, waiveXrays, obj);",
    "   }",
], REWRAP))

# the shape of main's nsWindowWatcher: our anchor declares a local, a later hunk of the same function uses it
SIZE_OPENED = "static void SizeOpenedWindow(nsIDocShellTreeOwner* aTreeOwner,"
WINDOW_WATCHER = patch("toolkit/components/windowwatcher/nsWindowWatcher.cpp",
    hunk(2322, 2322, ["     int32_t left = 0;", "     int32_t top = 0;", " ",
                      "+  const bool stealthPlaced = mozilla::StealthPlacePopupAtDefault(aIsCallerChrome);" + MK,
                      "+", "   // Set up width"], SIZE_OPENED),
    hunk(2338, 2340, ["     height = *aSizeSpec.mInnerHeight;", "   }", " ",
                      "-  bool positionSpecified = aSizeSpec.PositionSpecified();",
                      "+  bool positionSpecified = aSizeSpec.PositionSpecified() || stealthPlaced;" + MK,
                      " ", "   // Check security state"], SIZE_OPENED))


def test_c16_flags_the_locals_a_rewrite_passes_on_the_shape_of_main_wrapper_factory():
    got = hc.analyse_locals(FOLDER, WRAPPER_FACTORY)
    assert [v.rule for v in got] == ["C16"]
    assert names(WRAPPER_FACTORY) == ["securityWrapper", "waiveXrays", "xrayType"]       # `cx` is a parameter, `obj` is Mozilla's own
    assert "line " in got[0].detail


def test_c16_flags_a_local_used_by_a_later_hunk_of_the_same_function():
    assert names(WINDOW_WATCHER) == ["stealthPlaced"]
    # a line that declares a local and passes others is not an anchor by form: it is judged like any hook
    passes = WINDOW_WATCHER.replace("StealthPlacePopupAtDefault(aIsCallerChrome)", "StealthPlacePopupAtDefault(aIsCallerChrome, left, top)")
    assert names(passes) == ["left", "stealthPlaced", "top"]


def test_c16_an_anchor_may_pass_locals():
    anchor = patch("toolkit/components/windowwatcher/nsWindowWatcher.cpp", hunk(2322, 2322, [
        "     int32_t left = 0;", "     int32_t top = 0;", " ", "     top = *aSizeSpec.mTop;",
        "+  mozilla::StealthPlacePopupAtDefault(aIsCallerChrome, left, top);" + MK, " ", "   // Set up width"], SIZE_OPENED))
    assert [h.form for h in hc.analyse_patch(FOLDER, anchor)[0]] == ["anchor"]
    assert names(anchor) == []
    guard_seen = patch("dom/Foo.cpp", hunk(10, 10, ["   int left = 0;", "   Work();", "+  if (StealthX(this, left)) return NS_OK;" + MK, "   More();"],
                                           "nsresult Foo::Bar(int aArg) {"))
    assert [h.form for h in hc.analyse_patch(FOLDER, guard_seen)[0]] == ["anchor"]     # mid-function: an anchor
    assert names(guard_seen) == []


def test_c16_a_guard_notice_or_wrap_that_passes_a_local_fails_and_this_or_a_parameter_passes():
    wrap = patch("dom/Foo.cpp", hunk(10, 10, ["   int local = 1;", "-  Use(local, aArg);", "+  Use(StealthX(this, local, aArg));" + MK, "   More();"],
                                     "nsresult Foo::Bar(int aArg) {"))
    assert names(wrap) == []                     # `local` is in Mozilla's own expression, which the wrap keeps
    wrap_ours = patch("dom/Foo.cpp", hunk(10, 10, ["   int local = 1;", "-  Use(aArg);", "+  Use(StealthX(this, local, aArg));" + MK, "   More();"],
                                          "nsresult Foo::Bar(int aArg) {"))
    assert names(wrap_ours) == ["local"]         # an argument of ours that is a local
    ok = patch("dom/Foo.cpp", hunk(10, 10, ["   int local = 1;", "-  Use(aArg);", "+  Use(StealthX(this, aArg));" + MK, "   More();"],
                                   "nsresult Foo::Bar(int aArg) {"))
    assert names(ok) == []                       # `this` and a parameter


def test_c16_not_a_local_by_name_or_by_use():
    base = ["   int local = 1;", "   RefPtr<X> mine;", "   const nsCString& aParam = Get();", "   Foo* p = nullptr;", " "]
    def one(added):
        return patch("dom/Foo.cpp", hunk(10, 10, [*base, "-  Use(aArg);", "+  " + added + MK, "   More();"], "nsresult Foo::Bar(int aArg) {"))
    assert names(one("Use(StealthX(this, local));")) == ["local"]
    assert names(one("Use(StealthX(this, mMember, sStatic, gGlobal, kConst, aParam));")) == []      # Mozilla's naming: not locals
    assert names(one("Use(StealthX(this, p->mField));")) == []                    # a receiver is not passed
    assert names(one("local = StealthX(this);")) == []                            # the target of an assignment is not passed
    assert names(one("Use(StealthX(this, other::local, obj.local));")) == []      # a qualified name or a member
    assert names(one("if (auto declared = StealthX(this)) return declared;")) == []    # declared by the hook itself
    assert names(one("Use(StealthX(this, \"local\"));")) == []                    # a string


def test_c16_what_it_cannot_see_a_declaration_outside_the_hunks_is_read_only_from_a_base():
    unseen = patch("js/xpconnect/wrappers/WrapperFactory.cpp", hunk(10, 10, [
        "   wrapper = Foo();", "-  Use(aArg);", "+  Use(StealthX(this, hidden));" + MK, "   More();"], REWRAP))
    assert names(unseen) == []
    base = ["#include <x>", "", REWRAP, "                             HandleObject obj) {", "  bool hidden = Compute();", "  Use(aArg);",
            "  Other();", "}", "", "void After() {", "  int hidden2 = 0;", "}"]
    assert names(unseen, lambda path: ["pad"] * 0 + base) == []             # old line 10 is outside the function: nothing read
    inside = patch("js/xpconnect/wrappers/WrapperFactory.cpp", hunk(5, 5, [
        "   bool hidden = Compute();", "-  Use(aArg);", "+  Use(StealthX(this, hidden, cx, existing));" + MK, "   More();"], REWRAP))
    far = patch("js/xpconnect/wrappers/WrapperFactory.cpp", hunk(6, 6, [
        "-  Use(aArg);", "+  Use(StealthX(this, hidden, cx, existing, obj));" + MK, "   Other();"], REWRAP))
    assert names(far) == []                                              # `hidden` is declared above the 3 lines of context
    assert names(far, lambda path: base) == ["hidden"]                   # the base shows it; cx, existing, obj are parameters
    assert names(inside) == ["hidden"]
    assert names(far, lambda path: None) == []                           # no base file: as without one


def test_c16_headers_are_not_read_and_a_backport_folder_is_exempt(tmp_path):
    header = patch("dom/Foo.h", hunk(10, 10, ["   int local = 1;", "-  Use(aArg);", "+  Use(StealthX(this, local));" + MK, "   More();"], "class Foo {"))
    assert names(header) == []
    root = tmp_path
    (root / FOLDER).mkdir(parents=True)
    (root / FOLDER / "hooks.patch").write_text(WRAPPER_FACTORY, encoding="utf-8", newline="")
    (root / "SERIES").write_text(FOLDER + "\n", encoding="utf-8")
    assert [v.rule for v in hc.locals_violations(root)] == ["C16"]
    (root / FOLDER / "BACKPORT.json").write_text("{}", encoding="utf-8")
    assert hc.locals_violations(root) == []


def test_c16_is_in_the_contract_never_debt_and_not_left_out_by_an_exception(tmp_path):
    import hooks_list as hl
    root = tmp_path
    (root / FOLDER).mkdir(parents=True)
    (root / FOLDER / "hooks.patch").write_text(WRAPPER_FACTORY, encoding="utf-8", newline="")
    (root / "SERIES").write_text(FOLDER + "\n", encoding="utf-8")
    gen = hl.generated(root, FOLDER)
    for e in gen:
        e.update(test="", exception="a ternary around Mozilla's call", reason_kind="expression", pm="approvato")
    (root / FOLDER / "HOOKS.json").write_text(hl.render(gen), encoding="utf-8", newline="")
    assert "C16" in {v.rule for v in hc.contract_violations(root)}
    assert "C16" in hc.PORT06_RULES and "C16" in hc.RULES
    v = [x for x in hc.contract_violations(root) if x.rule == "C16"][0]
    assert hc.update_debt([], [v], init=True) == []
    assert "never debt" in hc.debt_problems([v], [hc.entry_of(v)], None)[0]


def test_the_check_reads_the_base_when_it_is_given_a_source_and_a_tag(monkeypatch):
    import engine
    seen = []
    monkeypatch.setattr(hc, "git_base_reader", lambda source, tag: seen.append((source, tag)) or (lambda path: None))
    monkeypatch.setattr(engine, "problems", lambda: [])
    monkeypatch.setattr(engine, "contract_problems", lambda against_main=False, base=None: ([], 0, 0))
    monkeypatch.setattr(engine, "backport_in_tag_problems", lambda *a: [])
    monkeypatch.setattr(engine, "backport_replay_problems", lambda *a: [])
    engine.check(Path("src"), "TAG")
    assert seen == [(Path("src"), "TAG")]


def test_c16_the_added_else_if_of_the_s2_shape_passes_locals_the_base_declares():
    text = patch("js/xpconnect/wrappers/WrapperFactory.cpp", hunk(12, 12, [
        "     wrapper = &CrossOriginObjectWrapper::singleton;", "   }",
        "+  else if (StealthCallerObjectApplies(origin, target, targetIsChrome)) wrapper = StealthCallerObjectWrapper();" + MK,
        " ", "   // Special handling"], REWRAP))
    base = ["", REWRAP, "                             HandleObject obj) {", "  RootedObject origin(cx, Origin());", "  bool targetIsChrome = IsChrome();",
            "  JSObject* target = Target();", "  JSObject* wrapper = nullptr;", "  if (Cond()) {", "    wrapper = &CrossOriginObjectWrapper::singleton;",
            "  }", "", "  // Special handling", "  return wrapper;", "}"]
    assert names(text) == []                                  # the hunk shows none of the declarations
    assert names(text, lambda path: base) == ["origin", "target", "targetIsChrome"]     # `wrapper` is an assignment target


def test_the_hook_locals_command_is_red_on_a_hit_and_reads_the_tag(monkeypatch, capsys):
    import engine
    seen = []
    monkeypatch.setattr(hc, "git_base_reader", lambda source, tag: seen.append((source, tag)) or "reader")
    hit = hc.Violation("C16", FOLDER, "js/x/WrapperFactory.cpp", "f", "txt", "k", "line 5: xrayType")
    monkeypatch.setattr(hc, "locals_violations", lambda root, base=None: [hit] if base == "reader" else [])
    assert engine.hook_locals(Path("src"), "TAG") == 1
    out = capsys.readouterr().out
    assert seen == [(Path("src"), "TAG")] and "FAIL" in out and "xrayType" in out and "WrapperFactory.cpp" in out
    monkeypatch.setattr(hc, "locals_violations", lambda root, base=None: [])
    assert engine.hook_locals(Path("src"), "TAG") == 0
    assert "ok" in capsys.readouterr().out


def test_the_rebuilds_job_runs_the_hook_locals_command_against_the_materialized_tag():
    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    checks = (wf / "checks.yml").read_text(encoding="utf-8")
    rebuilds = checks.split("\n  rebuilds:")[1].split("\n  noreply-identity:")[0]
    assert "engine.py hook-locals --source source" in rebuilds
    assert "engine.py hook-locals" not in checks.split("\n  rebuilds:")[0]               # the rules job stays patch-only
    assert "hook-locals" not in (wf / "series.yml").read_text(encoding="utf-8")         # checks.yml is the one place a check is added
