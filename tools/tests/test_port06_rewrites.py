"""port-06: a hook only adds; a rewrite of Mozilla lines is an exception with a reason that holds (tools/hook_contract.py
C12..C15, docs/decisions/port-06-hooks-only-add.md). Each rule is shown failing on the hunk it exists for and passing on
the hunk that fixes it.

    python -m pytest tools/tests/test_port06_rewrites.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hook_contract as hc  # noqa: E402
import hooks_list as hl  # noqa: E402

FOLDER = "fingerprint/x"
MARK = "  // STEALTH-HOOK(fingerprint/x)"
FN = "nsresult Foo::Bar(int aArg) {"


def patch(file, lines, section=FN):
    old = sum(1 for l in lines if l[0] in " -")
    new = sum(1 for l in lines if l[0] in " +")
    return ("diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@ -10,%d +10,%d @@ %s\n%s\n"
            % (file, file, file, file, old, new, section, "\n".join(lines)))


def block(removed, added, file="dom/Foo.cpp", section=FN):
    """One block of Mozilla lines replaced by ours, with context on both sides. `removed` and `added` are lists of lines."""
    return patch(file, ["   // lead", " ", " " + section, "   int x = 1;", *["-" + r for r in removed],
                        *["+" + a for a in added], "   Done();", "   More();", "   Last();"], section=section)


def entries(text, **fields):
    """The HOOKS.json entries of a patch, each with the hand fields: a declared exception when `exception` is given."""
    hooks, _ = hc.analyse_patch(FOLDER, text)
    out = []
    for h in hooks:
        e = hl._entry(h)
        e.update(fields)
        out.append(e)
    return out


def exc(kind, why="no form carries it", **more):
    return dict(exception=why, reason_kind=kind, pm="approvato", **more)


def found(text, **fields):
    return hc.analyse_rewrites(FOLDER, text, entries(text, **fields) if fields else [])


def rules_of(text, **fields):
    return sorted({v.rule for v in found(text, **fields)})


# --------------------------------------------------------------------------- the three examples used below
# a value inside an expression Mozilla builds, on two lines: no one-line form carries it
EXPR = block(["  if (aLen > 20) {", "    x = x.substr(aLen - 20);"],
             ["  if (aLen > 30) {" + MARK, "    x = x.substr(aLen - 30);" + MARK])
# a parameter added to a C++ signature of Mozilla's
SIG = block(["nsresult Foo::Bar(int aArg) {"], ["nsresult Foo::Bar(int aArg," + MARK, "                  double aStealth) {" + MARK])


def test_a_form_is_not_a_rewrite_to_declare():
    one_line = block(["  DoIt(x);"], ["  DoIt(StealthWrap(this, x));" + MARK])
    assert rules_of(one_line) == []
    pair = block(["  int n = Compute(20);"], ["  int n = Compute(30);" + MARK])
    assert rules_of(pair) == []


def test_c12_a_rewrite_outside_the_forms_needs_a_declared_exception():
    assert rules_of(EXPR) == ["C12"]
    assert rules_of(EXPR, **exc("expression")) == []
    v = found(EXPR)[0]
    assert v.rule == "C12" and "exception" in v.detail and v.folder == FOLDER and v.key.startswith("C12|%s|" % FOLDER)


def test_c12_the_exception_needs_the_pm_and_an_allowed_reason_kind():
    assert rules_of(EXPR, exception="why", pm="approvato") == ["C12"]                            # no reason_kind
    assert rules_of(EXPR, exception="why", pm="approvato", reason_kind="convenience") == ["C12"]    # not one of the four
    assert rules_of(EXPR, exception="why", reason_kind="expression") == ["C12"]                  # no pm: not an exception at all
    assert rules_of(EXPR, exception="   ", pm="approvato", reason_kind="expression") == ["C12"]    # no reason in words
    for kind in hc.REASON_KINDS:
        if kind != "macro":
            assert "C12" not in rules_of(EXPR, **exc(kind)), kind


def test_c12_a_deleted_mozilla_line_is_a_rewrite_too():
    gone = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "-  DoIt(x);", "   DoMore();", "   Done();", "   Last();"])
    assert rules_of(gone) == ["C12"]
    assert "C12" not in rules_of(gone, **exc("expression"))


def test_a_declaration_rewrite_of_an_idl_or_webidl_parameter_is_allowed():
    idl = block(["  void foo(in long a);"], ["  void foo(in long a," + MARK, "               in double aLatency);" + MARK],
                file="dom/interfaces/nsIFoo.idl", section="interface nsIFoo : nsISupports")
    assert rules_of(idl) == ["C12"]
    assert rules_of(idl, **exc("declaration")) == []                       # an IDL parameter needs no side-state reason
    webidl = block(['  [BinaryName="shadowRootForBindings"]'], ['  [NeedsSubjectPrincipal, BinaryName="shadowRootForBindings"]' + MARK],
                   file="dom/webidl/Element.webidl", section="interface Element")
    assert rules_of(webidl) == ["C12"]
    assert rules_of(webidl, **exc("declaration")) == []
    ipdl = block(["  async Foo(bool a);"], ["  async Foo(bool a," + MARK, "            LoadInfoArgs? aLoadInfo);" + MARK],
                 file="netwerk/ipc/PFoo.ipdl", section="protocol PFoo")
    assert rules_of(ipdl, **exc("declaration")) == []


def test_c15_a_parameter_added_to_a_cpp_signature_is_threading():
    assert "C15" in rules_of(SIG)
    assert "C15" in rules_of(SIG, **exc("expression"))                    # not a declaration
    assert "C15" in rules_of(SIG, **exc("declaration", "the binding passes it"))       # a declaration that names no side state
    assert rules_of(SIG, **exc("declaration", "no side state can carry it: the caller's principal is known only here")) == []
    v = [x for x in found(SIG, **exc("expression")) if x.rule == "C15"][0]
    message = str(hc.violation_failure(v))
    assert "side object" in message and "thread-local" in message and "Rule: docs/decisions/port-06-hooks-only-add.md" in message


def test_c15_a_parameter_added_to_a_call_is_threading_too():
    call = block(["  rv = Lookup(aURI, aFlags);"], ["  rv = Lookup(aURI, aFlags, aStealthState);" + MARK])
    assert "C15" in rules_of(call, **exc("expression"))
    ok = block(["  rv = Lookup(aURI, aFlags);"], ["  rv = Lookup(aURI," + MARK, "              aFlags, aStealthState);" + MARK])
    assert "C15" in rules_of(ok, **exc("declaration", "no one"))
    assert "C15" not in rules_of(ok, **exc("declaration", "no side state can carry it across the IPC boundary"))


def test_c15_logic_or_an_unrelated_insertion_is_not_a_parameter():
    logic = block(["  if (aLen) {"], ["  if (aLen && aStealthOn) {" + MARK])
    assert "C15" not in rules_of(logic, **exc("expression"))


def test_a_macro_rewrite_is_allowed_with_an_if_and_refused_elsewhere():
    ifdef = block(["#ifdef XP_WIN"], ["#if STEALTH_NATIVE_EOL_IS_CRLF" + MARK])
    assert rules_of(ifdef) == ["C12"]
    assert rules_of(ifdef, **exc("macro")) == []
    # a `&& 0` on the `#if` line is the same rewrite: a directive cannot be wrapped, no C14
    widen = block(["#if !defined(XP_WIN) && !defined(XP_MACOSX)"], ["#if !defined(XP_WIN) && !defined(XP_MACOSX) && 0" + MARK])
    assert rules_of(widen, **exc("macro")) == []
    # the kind says macro, but no preprocessor line is rewritten: a value in an expression is `expression`
    wrong = rules_of(EXPR, **exc("macro"))
    assert wrong == ["C12"] and "macro" in found(EXPR, **exc("macro"))[0].detail
    define = block(["#define STEALTH_X(a) \\", "  Foo(a, 20)"], ["#define STEALTH_X(a) \\", "  Foo(a, 30)"])
    assert "C12" not in rules_of(define, **exc("macro"))


SKIP_OK = block(["  DoIt(x);"], ["  if (!StealthSkipsIt(this)) {" + MARK, "    DoIt(x);", "  }" + MARK])
SKIP_BAD = block(["  DoIt(x);"], ["  if (!StealthSkipsIt(this)) {" + MARK, "    DoIt(x, true);", "  }" + MARK])


def test_c13_a_skip_keeps_mozillas_text_verbatim():
    assert rules_of(SKIP_OK, **exc("skip", "reads the host")) == []
    bad = found(SKIP_BAD, **exc("skip", "reads the host"))
    assert [v.rule for v in bad] == ["C13"], [(v.rule, v.detail) for v in bad]
    assert "DoIt(x);" in bad[0].detail and "verbatim" in bad[0].detail          # the message names the line


def test_c13_whitespace_does_not_matter_and_a_deletion_cannot_be_a_skip():
    reindented = block(["  DoIt(x,   y);"], ["  if (!StealthSkipsIt(this)) {" + MARK, "        DoIt(x, y);", "  }" + MARK])
    assert rules_of(reindented, **exc("skip")) == []
    gone = patch("dom/Foo.cpp", ["   // lead", " ", " " + FN, "-  DoIt(x);", "   DoMore();", "   Done();", "   Last();"])
    assert rules_of(gone, **exc("skip")) == ["C13"]


def test_c13_only_judges_a_skip():
    assert "C13" not in rules_of(SKIP_BAD, **exc("expression"))


def test_a_skip_is_not_a_wrap():
    # Mozilla's line kept whole inside our guard: the text is not evaluated for nothing; neither C14 nor C15
    assert rules_of(SKIP_OK, **exc("expression")) == []


WRAP_I = block(["  int r = DoIt(a,", "                x);"], ["  int r = StealthWrap(this, DoIt(a, x));" + MARK])
WRAP_I_OK = block(["  int r = DoIt(a,", "                x);"], ["  int r = StealthDoIt(this, a, 7);" + MARK])


def test_c14_i_mozillas_expression_intact_inside_our_line_is_a_wrap():
    v = found(WRAP_I, **exc("expression"))
    assert [x.rule for x in v] == ["C14"] and "wrap-expression" in v[0].detail and "(i)" in v[0].detail
    assert rules_of(WRAP_I_OK, **exc("expression")) == []                 # the expression does not survive: no form fits
    one_line_wrap = block(["  int r = DoIt(a, x);"], ["  int r = StealthWrap(this, DoIt(a, x));" + MARK])
    assert rules_of(one_line_wrap) == []                                  # declared as the form it is: no rewrite to judge


def test_c14_ii_adding_a_logical_operator_or_a_ternary_around_mozillas_expression():
    anded = block(["  if (aArg) {"], ["  if (aArg && StealthOn(this)) {" + MARK])
    v = found(anded, **exc("expression"))
    assert [x.rule for x in v] == ["C14"] and "(ii)" in v[0].detail and "&&" in v[0].detail
    ored = block(["  bool placed = aSpec.Positioned();"], ["  bool placed = aSpec.Positioned() || aStealthPlaced;" + MARK])
    assert "||" in found(ored, **exc("expression"))[0].detail
    ternary = block(["  rv = Open(aURI, aFlags);"], ["  rv = StealthOn(this) ? OpenOurs(aURI) : Open(aURI, aFlags);" + MARK])
    assert "?" in found(ternary, **exc("expression"))[0].detail and rules_of(ternary, **exc("expression")) == ["C14"]
    # the wrap that fixes it is a form: nothing to judge
    wrapped = block(["  if (aArg) {"], ["  if (StealthOn(this, aArg)) {" + MARK])
    assert rules_of(wrapped) == []


def test_c14_applies_even_with_an_exception_and_names_the_form_that_fits():
    anded = block(["  if (aArg) {"], ["  if (aArg && StealthOn(this)) {" + MARK])
    for kind in ("expression", "declaration"):
        assert rules_of(anded, **exc(kind)) == ["C14"], kind
    assert rules_of(anded) == ["C12", "C14"]                              # without any exception both


def test_c14_does_not_read_a_preprocessor_line_or_an_idl_optional_as_an_expression():
    widen = block(["#if defined(XP_WIN)"], ["#if defined(XP_WIN) && STEALTH_ON" + MARK])
    assert rules_of(widen, **exc("macro")) == []
    ipdl = block(["  async Foo(bool a);"], ["  async Foo(bool a, LoadInfoArgs? aLoadInfo);" + MARK], file="netwerk/ipc/PFoo.ipdl",
                 section="protocol PFoo")
    assert rules_of(ipdl, **exc("declaration")) == []


def test_an_rvalue_reference_qualifier_is_not_a_logical_and():
    ref = block(["  operator hb_face_t*() const { return mFace; }"],
                ["  operator hb_face_t*() const& { return mFace; }" + MARK, "  operator hb_face_t*() const&& = delete;" + MARK],
                file="gfx/thebes/gfxFontEntry.h", section="class AutoHBFace {")
    assert rules_of(ref, **exc("declaration")) == []


def test_the_key_is_stable_and_has_no_line_number():
    a = found(EXPR)[0]
    moved = EXPR.replace("@@ -10,", "@@ -90,").replace("+10,", "+90,")
    assert hc.analyse_rewrites(FOLDER, moved, [])[0].key == a.key


def test_the_rule_texts_exist():
    for r in hc.PORT06_RULES:
        assert r in hc.RULES and hc.RULES[r]


# --------------------------------------------------------------------------- in the series: HOOKS.json, the contract, the debt
def _series(tmp_path, patch_text, hooks_fields=None):
    d = tmp_path / FOLDER
    d.mkdir(parents=True)
    (d / "hooks.patch").write_text(patch_text, encoding="utf-8", newline="")
    (tmp_path / "SERIES").write_text(FOLDER + "\n", encoding="utf-8")
    if hooks_fields is not None:
        gen = hl.generated(tmp_path, FOLDER)
        for e in gen:
            e.update(hooks_fields)
            if e["form"] == "unknown" and not hc.excepted_lacks(e):
                e["form"] = "excepted"          # what the export writes (G63)
        (d / "HOOKS.json").write_text(hl.render(gen), encoding="utf-8", newline="")
    return tmp_path


def _port06(root):
    return sorted((v.rule) for v in hc.contract_violations(root) if v.rule in hc.PORT06_RULES)


def test_the_contract_judges_the_exception_the_old_rules_leave_out(tmp_path):
    root = _series(tmp_path, EXPR, dict(exception="no form", pm="approvato", test="py:tools/tests/test_x.py::test_y"))
    assert _port06(root) == ["C12"]            # the exception has no reason_kind: C6 is left out, C12 is not
    assert not any(v.rule == "C6" for v in hc.contract_violations(root))


def test_the_contract_accepts_the_exception_with_its_reason_kind(tmp_path):
    root = _series(tmp_path, EXPR, dict(exception="a value in two lines", reason_kind="expression", pm="approvato"))
    assert _port06(root) == []


def test_reason_kind_is_a_hand_field_kept_by_the_export(tmp_path):
    root = _series(tmp_path, EXPR, dict(test="", exception="a value in two lines", reason_kind="expression", pm="approvato"))
    again = hl.expected(root, FOLDER)
    assert all(e["reason_kind"] == "expression" for e in again)
    assert hl.render(again) == (root / FOLDER / "HOOKS.json").read_text(encoding="utf-8")
    assert hl.problems(root) == [] or all("reason_kind" not in str(p) for p in hl.problems(root))


def test_check_refuses_a_reason_kind_that_is_not_allowed_or_has_no_exception(tmp_path):
    bad = _series(tmp_path, EXPR, dict(exception="why", reason_kind="whatever", pm="approvato"))
    assert any("reason_kind" in p and "whatever" in p for p in map(str, hl.problems(bad)))
    other = tmp_path / "other"
    other.mkdir()
    lone = _series(other, EXPR, dict(reason_kind="skip"))
    assert any("reason_kind" in p and "no exception" in p for p in map(str, hl.problems(lone)))


def test_the_debt_never_holds_a_port06_rule():
    v = hc.Violation("C12", "f/x", "a.cpp", "void F() {", "-a\n+b", hc._key("C12", "f/x", "a.cpp", "void F() {", "-a\n+b"), "no exception")
    assert hc.update_debt([], [v], init=True) == []
    msgs = [str(x) for x in hc.debt_problems([v], [], None)]
    assert len(msgs) == 1 and "C12" in msgs[0] and "no exception" in msgs[0] and "debt list" not in msgs[0].split(":")[-1]
    listed = [str(x) for x in hc.debt_problems([v], [hc.entry_of(v)], None)]
    assert len(listed) == 1 and "never debt" in listed[0]


def test_a_backport_folder_is_exempt(tmp_path):
    root = _series(tmp_path, EXPR)
    (root / FOLDER / "BACKPORT.json").write_text("{}", encoding="utf-8")
    assert hc.rewrite_violations(root) == []


def test_the_series_violations_are_all_port06_rules():
    """On a series whose rewrites are not all fixed yet the check is red by design (port-06 merges together with the engine
    change that fixes them); the violations it reports are the port-06 rules only, never debt."""
    root = Path(__file__).resolve().parents[2]
    assert all(v.rule in hc.PORT06_RULES for v in hc.rewrite_violations(root))
    assert not any(v.rule in hc.PORT06_RULES for v in hc.load_debt(root / "tools" / "hook-debt.json") if isinstance(v, hc.Violation))
