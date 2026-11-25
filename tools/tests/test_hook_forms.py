"""No hook has the form `unknown` (rule C21), and the forms that take what `unknown` used to hold: scope, rewire, parameter, excepted,
and the extended registration, member, guard, notice, anchor and declared-value (docs/STRUCTURE.md, hook forms; G60..G67).

Each form is shown with a fixture that passes and a red case that does not; C21 is shown on a small series and on the real one.

    python -m pytest tools/tests/test_hook_forms.py
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402
import hook_contract as hc  # noqa: E402
import hooks_list as hl  # noqa: E402

FOLDER = "fingerprint/x"
FN = "nsresult Foo::Bar(int aArg) {"
MARK = "  // STEALTH-HOOK(fingerprint/x)"
HASH = "  # STEALTH-HOOK(fingerprint/x)"
BODY = ["   int x = 1;", "   DoIt(x);", "   return NS_OK;", " }"]
PART_TWO = "green after part 2 moves the inline logic into our code"


def patch(file, lines, section=FN, start=10):
    old = sum(1 for l in lines if l[0] in " -")
    new = sum(1 for l in lines if l[0] in " +")
    return ("diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@ -%d,%d +%d,%d @@ %s\n%s\n"
            % (file, file, file, file, start, old, start, new, section, "\n".join(lines)))


def top(*added, file="dom/Foo.cpp"):
    """Lines added as the first statements of the function FN."""
    return patch(file, ["   // lead", " ", " " + FN, *["+" + a for a in added], *BODY])


def mid(*added, file="dom/Foo.cpp"):
    """Lines added in the middle of the function FN, after `int x = 1;`."""
    return patch(file, ["   // lead", " " + FN, "   int x = 1;", *["+" + a for a in added], "   DoIt(x);", "   DoIt(x);", "   return NS_OK;", " }"])


def forms_of(text):
    return [h.form for h in hc.analyse_patch(FOLDER, text)[0]]


def rules(text):
    return sorted({v.rule for v in hc.analyse_patch(FOLDER, text)[1]})


def one_form(text, form):
    assert forms_of(text) == [form], forms_of(text)
    assert rules(text) == [], rules(text)


# --------------------------------------------------------------------------- C21 on a small series
def series(tmp_path, text, entries=None):
    d = tmp_path / FOLDER
    d.mkdir(parents=True, exist_ok=True)
    (d / "hooks.patch").write_text(text, encoding="utf-8", newline="")
    (tmp_path / "SERIES").write_text(FOLDER + "\n", encoding="utf-8")
    entries = entries if entries is not None else hl.expected(tmp_path, FOLDER)
    for e in entries:
        e["test"] = "wrapper:tests/test_a.py::test_b"
    (d / "HOOKS.json").write_text(hl.render(entries), encoding="utf-8", newline="")
    return tmp_path


def c21(root):
    return [v for v in hc.contract_violations(root) if v.rule == "C21"]


UNKNOWN = "  x = DoOther(x, y);" + MARK       # none of the forms: no call of ours, a plain assignment


def test_c21_a_line_with_no_form_and_no_exception_row_is_red(tmp_path):
    root = series(tmp_path, top(UNKNOWN))
    assert forms_of(top(UNKNOWN)) == ["unknown"]
    (v,) = c21(root)
    msg = hc.violation_failure(v)
    assert msg.where.startswith("%s/hooks.patch, dom/Foo.cpp" % FOLDER) and msg.rule == hc.D_HOOK02
    assert "C21" in msg.what and "no form takes it and its entry has no exception row" in msg.what and "x = DoOther(x, y);" in msg.what
    assert "write the line as one of the forms" in msg.fix and "`excepted`" in msg.fix


def test_c21_the_complete_exception_row_makes_the_form_excepted_and_green(tmp_path):
    root = series(tmp_path, top(UNKNOWN))
    entries = hl.expected(root, FOLDER)
    entries[0].update(exception="no form carries this line", reason_kind="expression", pm="approvato")
    series(tmp_path, top(UNKNOWN), entries)
    assert c21(root) == []
    assert hl.expected(root, FOLDER)[0]["form"] == "excepted"
    hl.write_all(root)
    assert json.loads((root / FOLDER / "HOOKS.json").read_text(encoding="utf-8"))[0]["form"] == "excepted"
    assert [p for p in hl.problems(root)] == []          # the committed form is the one the series generates with the hand fields


@pytest.mark.parametrize("fields, lacks", [
    ({"exception": "why", "pm": "approvato"}, "`reason_kind`"),
    ({"exception": "why", "reason_kind": "expression"}, "`pm: \"approvato\"`"),
    ({"reason_kind": "expression", "pm": "approvato"}, "`exception`"),
    ({"exception": "why", "reason_kind": "whatever", "pm": "approvato"}, "`reason_kind`"),
    ({"exception": "  ", "reason_kind": "macro", "pm": "approvato"}, "`exception`"),
])
def test_c21_excepted_without_a_complete_exception_row_is_red(tmp_path, fields, lacks):
    root = series(tmp_path, top(UNKNOWN))
    entries = hl.expected(root, FOLDER)
    entries[0].update(fields)
    series(tmp_path, top(UNKNOWN), entries)
    assert hl.expected(root, FOLDER)[0]["form"] == "unknown"
    (v,) = c21(root)
    assert "its exception row is incomplete" in hc.violation_failure(v).what and lacks in hc.violation_failure(v).what


def test_c21_a_committed_form_excepted_with_an_incomplete_row_is_a_failure_of_the_list(tmp_path):
    root = series(tmp_path, top(UNKNOWN))
    entries = hl.expected(root, FOLDER)
    entries[0]["form"] = "excepted"
    entries[0]["exception"] = "why"
    series(tmp_path, top(UNKNOWN), entries)
    text = "\n".join(str(p) for p in hl.problems(root))
    assert "C21" in text and "has the form `excepted` and its exception row is incomplete" in text and "`reason_kind`" in text


def test_c21_is_never_debt_and_no_declared_exception_leaves_it_out(tmp_path):
    assert "C21" in hc.RULES and "C21" in hc.HOOK02_NEVER_DEBT and "C21" in hc.NEVER_DEBT_RULES
    root = series(tmp_path, top(UNKNOWN))
    (v,) = c21(root)
    assert hc.update_debt([], [v], init=True) == []
    assert "never debt" in str(hc.debt_problems([v], [hc.entry_of(v)], None)[0])
    # an exception that is no reason_kind does not cover the line (the form stays unknown, C21 stays)
    entries = hl.expected(root, FOLDER)
    entries[0].update(exception="why", pm="approvato")
    series(tmp_path, top(UNKNOWN), entries)
    assert len(c21(root)) == 1


# The 18 lines of the real series that no form of this commit takes: the inline logic that part 2 moves into our code, and two that wait
# for a declaration (one line has no `reason_kind`, one is a mid-function scope with no `anchor`: T2). They are the work list of part 2.
PART_TWO_LINES = {
    ("automation/element-atoms", "export const ATOM_SOURCES = ATOMS;"),
    ("automation/hybrid-xrays", "priv->hybridXrays = options.hybridXrays;"),
    ("automation/hybrid-xrays", "// STEALTH-HOOK(automation/hybrid-xrays)"),
    ("automation/hybrid-xrays", 'ParseBoolean("hybridXrays", &hybridXrays) &&'),
    ("automation/hybrid-xrays", "!targetCompartmentPrivate->hybridXrays &&"),
    ("automation/hybrid-xrays", "else if (mozilla::StealthCallerObjectApplies()) wrapper = mozilla::StealthCallerObjectWrapper();"),
    ("fingerprint/fonts/bundle", 'if CONFIG["OS_TARGET"] == "WINNT":'),
    ("fingerprint/fonts/font-list", 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "gtk":'),
    ("fingerprint/fonts/font-list", 'CXXFLAGS += CONFIG["CAIRO_FT_CFLAGS"]'),
    ("fingerprint/webgpu/adapter-declaration", "static std::string_view ToJsKey(const Limit limit);"),
    ("fingerprint/webrtc/declared-network", "let stealth_if = addrs.first().copied();"),
    ("network/doh", "static_cast<TRRLoadInfo*>(loadInfo.get())->mOriginAttributes = mOriginAttributes;"),
    ("network/doh", "NS_IMETHODIMP nsUrlClassifierHashCompleterBase::GetUserContextId(uint32_t* aId)"),
    ("network/doh", 'DEFINES["MOZ_PROXY_BYPASS_PROTECTION"] = True'),
    ("network/proxy-udp", "RefPtr<net::PcUdpProxy> mUdpProxy;"),
    ("network/proxy-udp", "RefPtr<net::PcUdpProxy> NrSocketProxyConfig::UdpProxy() const"),
    ("network/proxy-udp", "explicit NrSocket(const std::shared_ptr<NrSocketProxyConfig>& aProxyConfig)"),
    ("platform/launch-counter", 'try { ChromeUtils.importESModule("resource:///modules/StealthLaunchCounter.sys.mjs")'),
}


def test_c21_on_the_real_series_is_exactly_the_work_list_of_part_two():
    got = {(v.folder, " ".join(v.text.split("  // STEALTH-HOOK")[0].split("  # STEALTH-HOOK")[0].split())) for v in c21_of_series()}
    want = {(f, " ".join(t.split())) for f, t in PART_TWO_LINES}
    assert {(f, t) for f, t in got if not any(t.startswith(w) for fw, w in want if fw == f)} == set()
    assert len(got) == len(PART_TWO_LINES) == 18, sorted(got)
    assert {f for f, _ in got} == {f for f, _ in want}


def c21_of_series():
    return c21(engine.ROOT)


@pytest.mark.xfail(strict=True, reason=PART_TWO)
def test_c21_the_series_has_no_hook_of_the_form_unknown():
    assert c21_of_series() == []


def test_no_entry_of_the_series_has_a_form_that_is_not_in_the_table():
    forms = {e["form"] for f in hl.folders(engine.ROOT) for e in hl.expected(engine.ROOT, f)}
    assert forms <= set(hc.FORMS), sorted(forms - set(hc.FORMS))
    for f in hl.folders(engine.ROOT):
        assert [e["form"] for e in hl.load(engine.ROOT, f)] == [e["form"] for e in hl.expected(engine.ROOT, f)], f


def test_every_excepted_entry_of_the_series_has_its_complete_row():
    seen = 0
    for f in hl.folders(engine.ROOT):
        for e in hl.load(engine.ROOT, f):
            if e["form"] == "excepted":
                seen += 1
                assert hc.excepted_lacks(e) == [], (f, e["line"])
    assert seen >= 15


# --------------------------------------------------------------------------- scope (G60)
def test_scope_is_a_local_of_a_stealth_type_as_the_first_statement():
    for line in ("  StealthKeyBirthScope stealthBirth(mStealthKeyBirth);", "  const StealthWebGLParameterAnswer a(*this, aArg, rv);",
                 "  mozilla::net::StealthLookupContextScope s(aPrincipal);"):
        one_form(top(line + MARK), "scope")


def test_scope_red_cases_mid_function_it_is_an_anchor_and_a_foreign_type_is_no_scope():
    one_form(mid("  StealthKeyBirthScope s(this, aArg);" + MARK), "anchor")        # the anchor rules: its anchor and why (T2)
    assert forms_of(top("  KeyBirthScope s(this, aArg);" + MARK)) == ["unknown"]
    assert "C5" in rules(top("  StealthKeyBirthScope s(this && aArg);" + MARK))      # the arguments are judged for logic
    assert "C1" in rules(top("  StealthKeyBirthScope s(this,", "                       aArg);" + MARK))


# --------------------------------------------------------------------------- rewire (G61)
def test_rewire_is_a_line_of_ours_that_passes_a_variable_through_one_call_of_ours_and_assigns_it_back():
    for line, file in (("  x = StealthX(this, x);", "dom/Foo.cpp"), ("  snapshot = CanvasUtils::StealthProject(this, snapshot.forget());", "dom/Foo.cpp"),
                       ("  aMsg = StealthTrimApiKeys(aMsg);", "toolkit/Foo.sys.mjs"), ("  to = StealthOwnPeer(&my_addr_, to);", "dom/Foo.cpp")):
        one_form(mid(line + MARK, file=file), "rewire")
    py = patch("python/mozbuild/jar.py", ["     try:", "         pass", "+            out = stealth_long_path(out)" + HASH, "     if x:", "         pass", "     y = 1"], section="class JarMaker:")
    one_form(py, "rewire")


def test_rewire_red_a_rewrite_of_a_mozilla_line_is_no_rewire_it_is_a_rewrite_under_c12():
    rewrite = patch("dom/Foo.cpp", ["   // lead", " " + FN, "   int x = 1;", "-  x = Compute();", "+  x = StealthX(this, x);" + MARK,
                                    "   DoIt(x);", "   DoIt(x);", "   return NS_OK;", " }"])
    assert "rewire" not in forms_of(rewrite)
    assert "C6" in rules(rewrite)
    root_rules = hc.analyse_rewrites(FOLDER, rewrite, [])
    assert [v.rule for v in root_rules] == ["C12"], [v.rule for v in root_rules]


def test_rewire_red_the_variable_is_not_passed_or_the_call_is_wrapped_in_more():
    for line in ("  x = StealthX(this, y);", "  x = 1 + StealthX(this, x);", "  x = StealthX(this, x) + 1;", "  x = Other(x);",
                 "  int x = StealthX(this, x);", "  x = StealthX(this, x), y = 2;"):
        assert "rewire" not in forms_of(mid(line + MARK)), line
    assert "C5" in rules(mid("  x = StealthX(this, x && y);" + MARK))


def test_a_rewire_names_the_variable_it_reassigns_so_c16_does_not_count_it():
    assert "rewire" in hc.EXEMPT_FOR_LOCALS


# --------------------------------------------------------------------------- parameter (G62): the recogniser is C15's
DEF_OLD, DEF_NEW = "ShadowRoot* Element::GetShadowRootForBindings() const {", "ShadowRoot* Element::GetShadowRootForBindings(nsIPrincipal& aSubject) const {"


def rewrite(file, old, new, section="void Element::GetSlot(nsAString& aName) {"):
    return patch(file, ["   // lead", " ", "-" + old, "+" + new + MARK, "   Body();", "   More();", "   Last();"], section=section)


def test_parameter_is_one_trailing_parameter_of_ours_in_a_c_or_idl_declaration():
    one_cases = [
        (rewrite("dom/Foo.cpp", DEF_OLD, DEF_NEW), "parameter"),
        (rewrite("dom/Foo.h", "  ShadowRoot* GetShadowRootForBindings() const;", "  ShadowRoot* GetShadowRootForBindings(nsIPrincipal& aSubject) const;"), "parameter"),
        (rewrite("dom/Foo.cpp", "  nsresult Send(int aX, nsICb* aCb) {", "  nsresult Send(int aX, nsICb* aCb, double aLatency) {"), "parameter"),
        (rewrite("dom/nsIFoo.idl", "  void send(in long aX, in nsICb aCb);", "  void send(in long aX, in nsICb aCb, [optional] in double aLatency);"), "parameter"),
        (rewrite("dom/Foo.webidl", '  [BinaryName="shadowRootForBindings"]', '  [NeedsSubjectPrincipal, BinaryName="shadowRootForBindings"]'), "parameter"),
    ]
    for text, form in one_cases:
        assert forms_of(text) == [form], text
        assert "C12" in {v.rule for v in hc.analyse_rewrites(FOLDER, text, [])}, "a parameter is judged by C12 and C15 as before"


def test_parameter_over_two_lines_every_line_of_the_block_has_the_form():
    two = patch("dom/Foo.cpp", ["   // lead", " ", "-  nsresult Send(int aX, nsICb* aCb) {", "+  nsresult Send(int aX, nsICb* aCb,", "+                double aLatency) {" + MARK,
                                "   Body();", "   More();", "   Last();"])
    assert forms_of(two) == ["parameter", "parameter"]
    idl = patch("dom/nsIFoo.idl", ["   // lead", " ", "-  void send(in long aX, [optional] in nsICb aCb);", "+  void send(in long aX, [optional] in nsICb aCb,",
                                   "+            [optional] in double aLatency);" + MARK, "   void other();", "   void more();", "   void last();"], section="")
    assert forms_of(idl) == ["parameter", "parameter"]


def test_parameter_red_cases():
    for old, new in (("  nsresult Send(int aX) {", "  nsresult Send(int aX, int aY, int aZ) {"),         # two parameters
                     ("  nsresult Send(int aX) {", "  nsresult Send(int aNew, int aX) {"),               # not trailing
                     ("  nsresult Send(int aX) {", "  nsresult Send(int aX, Foo(3)) {"),                   # not a declaration
                     ("  nsresult Send(int aX) {", "  nsresult Send(int aX, a + b) {"),
                     ("  Send(aX);", "  Send(aX, aY);")):                                               # a call, not a declaration
        assert "parameter" not in forms_of(rewrite("dom/Foo.cpp", old, new)), (old, new)
    assert "parameter" not in forms_of(rewrite("dom/Foo.webidl", '  [BinaryName="b"]', '  [SomethingElse, BinaryName="b"]'))
    assert "parameter" not in forms_of(rewrite("dom/Foo.cpp", "  operator hb_face_t*() const { return mFace; }", "  operator hb_face_t*() const& { return mFace; }"))
    assert "parameter" not in forms_of(rewrite("dom/Foo.py", "  def send(aX):", "  def send(aX, aNew):"))


def test_parameter_and_rule_c15_are_one_recogniser(monkeypatch):
    text = rewrite("dom/Foo.cpp", DEF_OLD, DEF_NEW)
    (r,) = [x for x in hc._analyse_patch(FOLDER, text)[2]]
    assert hc.rule_c15(r, None) is not None and forms_of(text) == ["parameter"]
    ok = {"reason_kind": "declaration", "exception": "no side state can carry it: a side state is the timing ratio the pm refused"}
    assert hc.rule_c15(r, ok) is None
    # C15 reads the insertion through parameter_insertions, and so does the form: with it silenced both go
    monkeypatch.setattr(hc, "parameter_insertions", lambda rem_t, add_t: [])
    assert hc.rule_c15(r, None) is None and forms_of(text) == ["unknown"]


def test_parameter_still_needs_its_exception_row_and_reads_green_with_it(tmp_path):
    text = rewrite("dom/Foo.cpp", DEF_OLD, DEF_NEW)
    root = series(tmp_path, text)
    got = {v.rule for v in hc.contract_violations(root)}
    assert {"C12", "C15"} <= got
    entries = hl.expected(root, FOLDER)
    entries[0].update(exception="a parameter of ours in a Mozilla signature: no side state can carry it", reason_kind="declaration", pm="approvato")
    series(tmp_path, text, entries)
    assert hc.contract_violations(root) == [] and hl.expected(root, FOLDER)[0]["form"] == "parameter"


# --------------------------------------------------------------------------- registration (G64)
def test_registration_of_a_file_of_ours_in_a_build_file_a_test_manifest_a_rust_file_and_a_doc():
    build = patch("dom/moz.build", [" UNIFIED_SOURCES += [", '     "a.cpp",', " ]", '+include("StealthX.mozbuild")' + HASH, " ", " X = 1", " Y = 2", " Z = 3"], section="")
    one_form(build, "registration")
    one_form(build.replace('"StealthX.mozbuild"', '"stealth.build"'), "registration")
    toml = patch("dom/test/xpcshell.toml", [' ["test_a.js"]', " ", '+["test_stealth_x.js"]' + HASH, " ", ' ["test_b.js"]', " ", ' ["test_c.js"]'], section="")
    one_form(toml, "registration")
    rust = [" use a::b;", " ", "+%s" + MARK, " ", " fn f() {}", " fn g() {}", " fn h() {}"]
    for line in ("pub mod stealth_x;", '#[path = "stealth_x.rs"] mod stealth_x;', "#[cfg(test)] mod stealth_tests;"):
        one_form(patch("gfx/src/lib.rs", [l % () if "%s" not in l else l % line for l in rust], section=""), "registration")
    md = patch("CLAUDE.md", ["+@STEALTH_CLAUDE.md <!-- STEALTH-HOOK(fingerprint/x) -->", " @AGENTS.md"], section="")
    one_form(md, "registration")
    link = patch("README.md", ["+[Notes of this fork: STEALTH_README.md](STEALTH_README.md) <!-- STEALTH-HOOK(fingerprint/x) -->", " ", " ![Banner](./b.svg)"], section="")
    one_form(link, "registration")


def test_registration_red_the_include_the_test_the_module_or_the_link_is_not_ours():
    build = patch("dom/moz.build", [" UNIFIED_SOURCES += [", '     "a.cpp",', " ]", '+include("/ipc/chromium/chromium-config.mozbuild")' + HASH, " ", " X = 1", " Y = 2", " Z = 3"], section="")
    assert forms_of(build) == ["unknown"]
    assert forms_of(build.replace("/ipc/chromium/chromium-config.mozbuild", "other.mozbuild")) == ["unknown"]
    toml = patch("dom/test/xpcshell.toml", [' ["test_a.js"]', " ", '+["test_other.js"]' + HASH, " ", ' ["test_b.js"]', " ", ' ["test_c.js"]'], section="")
    assert forms_of(toml) == ["unknown"]
    rust = patch("gfx/src/lib.rs", [" use a::b;", " ", "+pub mod other_x;" + MARK, " ", " fn f() {}", " fn g() {}", " fn h() {}"], section="")
    assert forms_of(rust) == ["unknown"]                                    # a module that is not named stealth_
    assert forms_of(rust.replace("pub mod other_x;", "pub mod stealth_x;")) == ["registration"]
    assert forms_of(rust.replace("pub mod other_x;", "pub fn stealth_x() {}")) == ["unknown"]
    assert forms_of(patch("CLAUDE.md", ["+@OTHER.md <!-- STEALTH-HOOK(fingerprint/x) -->", " @AGENTS.md"], section="")) == ["unknown"]
    assert forms_of(patch("README.md", ["+[Notes](OTHER.md) <!-- STEALTH-HOOK(fingerprint/x) -->", " ", " ![Banner](./b.svg)"], section="")) == ["unknown"]


def test_registration_a_forward_declaration_inside_one_namespace_is_a_forward_declaration_g40():
    text = patch("dom/Foo.h", [" #include <memory>", " ", " namespace mozilla {", "+namespace net { class PcUdpProxy; }" + MARK, " class Y {", " };", " int z;"], section="")
    one_form(text, "registration")
    assert forms_of(text.replace("class PcUdpProxy;", "class PcUdpProxy { int x; };")) != ["registration"]


# --------------------------------------------------------------------------- member (G65)
def test_member_a_data_member_of_ours_with_no_initializer_or_only_a_call_of_ours():
    cls = ["   RefPtr<A> mA;", "   RefPtr<B> mB;", "%s", "   bool mC = false;", "   bool mD = false;", "   bool mE = false;", "   bool mF = false;"]
    for line in ("StealthLinkClickAfter mStealth;", "uint32_t mStealthId = mozilla::net::StealthCurrentContext();", "StealthStandIn mStealth;",
                 "static StealthHostPorts sStealthPorts;"):
        text = patch("dom/Foo.cpp", [l if "%s" not in l else "+  " + line + MARK for l in cls], section="class Foo {")
        one_form(text, "member")


def test_member_red_cases_a_name_of_mozillas_or_an_initializer_that_is_more_than_a_call_of_ours():
    cls = ["   RefPtr<A> mA;", "   RefPtr<B> mB;", "%s", "   bool mC = false;", "   bool mD = false;", "   bool mE = false;", "   bool mF = false;"]

    def cpp(line):
        return patch("dom/Foo.cpp", [l if "%s" not in l else "+  " + line + MARK for l in cls], section="class Foo {")
    assert forms_of(cpp("RefPtr<net::PcUdpProxy> mUdpProxy;")) == ["unknown"]               # neither the type nor the name is ours
    assert forms_of(cpp("uint32_t mStealthId = Compute();")) == ["unknown"]               # the initializer is Mozilla's call
    assert forms_of(cpp("uint32_t mStealthId = StealthId() + 1;")) == ["unknown"]
    assert forms_of(cpp("StealthLinkClickAfter local;")) == ["unknown"]                    # in a .cpp a member is named mX
    assert "C5" in rules(cpp("uint32_t mStealthId = StealthId() && x;"))


def test_member_a_one_line_accessor_of_ours():
    def header(line):
        return patch("dom/Foo.h", [" class Foo {", "   void A();", "+  " + line + MARK, "   void C();", "   void D();", "   int e;"], section="class Foo {")
    for line in ("bool StealthIsHybrid() const { return hybridXrays; }", "StealthHostPorts& StealthPorts() { return host_ports_; }",
                 "int StealthCount() const { return mState->mCount; }"):
        one_form(header(line), "member")
    for line in ("bool IsHybrid() const { return hybridXrays; }", "bool StealthIsHybrid() const { return Compute(hybridXrays); }",
                 "bool StealthIsHybrid(int a) const { return hybridXrays; }"):
        assert forms_of(header(line)) == ["unknown"], line


def test_member_a_rust_field_of_ours_is_paired_with_its_initializer():
    field, init = "    stealth_fonts: stealth_shared::Remembered,", "            stealth_fonts: stealth_shared::Remembered::empty(),"
    first = patch("gfx/wr/render_backend.rs", ["     dl_stores: DlStores,", "+" + field + MARK, "     held: Vec<u8>,", "     other: u32,", "     last: u32,"],
                  section="pub struct RenderBackend {")
    second = patch("gfx/wr/render_backend.rs", ["             dl_stores: DlStores::default(),", "+" + init + MARK, "             held: Vec::new(),", "             other: 0,", "             last: 0,"],
                   section="impl RenderBackend {", start=200)
    both = first + "@@" + second.split("\n@@", 1)[1]           # two hunks of one file
    assert forms_of(both) == ["member", "member"] and rules(both) == []
    alone = patch("gfx/wr/render_backend.rs", ["     dl_stores: DlStores,", "+" + field + MARK, "     held: Vec<u8>,", "     other: u32,", "     last: u32,"],
                  section="pub struct RenderBackend {")
    assert forms_of(alone) == ["unknown"]               # a field with no initializer in the file


# --------------------------------------------------------------------------- JavaScript (G66, G33) and Python
JS_METHOD = ["   complete(aHash, aUrl, aCallback) {", "%s", "     if (!aUrl) {", "       throw new Error();", "     }"]


def js(line, file="toolkit/Foo.sys.mjs"):
    return patch(file, ["   // lead", " ", *[l if l != "%s" else "+" + line for l in JS_METHOD]], section="export class HashCompleter {")


def test_js_guard_notice_and_anchor():
    one_form(js("    if (stealthComplete(this, aHash, aUrl, aCallback)) { return; }  // STEALTH-HOOK(fingerprint/x)"), "guard")
    one_form(js("    if (StealthComplete(this, aHash)) { return null; }  // STEALTH-HOOK(fingerprint/x)"), "guard")
    one_form(js("    stealthNotify(this, aHash);  // STEALTH-HOOK(fingerprint/x)"), "notice")
    one_form(js("    StealthNotify(this, aHash);  // STEALTH-HOOK(fingerprint/x)"), "notice")
    end = patch("toolkit/Foo.sys.mjs", [" export function a() {", "   return 1;", " }", " ", "+if (stealthInstall(this)) { return; }  // STEALTH-HOOK(fingerprint/x)"], section="", start=40)
    assert forms_of(end) == ["anchor"] and rules(end) == []        # the last line of a module: G33, it carries its anchor and why (T2)


def test_js_red_cases_the_name_logic_and_the_try_catch_that_is_no_notice():
    assert "C10" in rules(js("    if (complete(this, aHash)) { return; }  // STEALTH-HOOK(fingerprint/x)"))
    assert "C5" in rules(js("    if (stealthComplete(this) && aHash) { return; }  // STEALTH-HOOK(fingerprint/x)"))
    assert forms_of(js("    if (stealthComplete(this)) { doIt(); return; }  // STEALTH-HOOK(fingerprint/x)")) == ["unknown"]
    # the lower-case name is JavaScript's: a C++ file keeps `Stealth<What>` (rule C10)
    assert "C10" in rules(top("  if (stealthComplete(this)) return NS_OK;" + MARK))
    # `try { ... import ... fire(); } catch {}` is more than one call: no notice
    tried = js('    try { ChromeUtils.importESModule("resource:///modules/StealthX.sys.mjs").StealthX.fire(); } catch {}  // STEALTH-HOOK(fingerprint/x)')
    assert forms_of(tried) == ["unknown"]


def test_python_declared_value_and_rewire():
    two = patch("python/mozbuild/data.py", ["     unified_prefix = context.relsrcdir", "-    if len(unified_prefix) > 20:", '-        p = unified_prefix[-20:].split("/", 1)[-1]',
                                          "+    if len(unified_prefix) > 30:" + HASH, '+        p = unified_prefix[-30:].split("/", 1)[-1]' + HASH,
                                          '     q = p.replace("/", "_")', "     r = 1", "     s = 2"], section="class UnifiedSources(BaseSources):")
    assert forms_of(two) == ["declared-value", "declared-value"] and rules(two) == []
    assert hc.analyse_rewrites(FOLDER, two, []) == []           # two literals changed, line for line: a form, no exception needed
    one = patch("python/mozbuild/data.py", ["     a = 1", "-    if x > 20:", "+    if x > 30:" + HASH, "     b = 2", "     c = 3", "     d = 4"], section="def f():")
    assert forms_of(one) == ["declared-value"]
    not_literal = patch("python/mozbuild/data.py", ["     a = 1", "-    if x > 20:", "-    y = 1", "+    if x > limit:" + HASH, "+    y = 1" + HASH, "     b = 2", "     c = 3", "     d = 4"],
                        section="def f():")
    assert "declared-value" not in forms_of(not_literal)


# --------------------------------------------------------------------------- the tables
def test_every_new_form_has_its_row_its_code_and_its_decision_text():
    table = {form: (where, looks) for form, where, looks in hc.FORMS_TABLE}
    for form, code in (("scope", "G60"), ("rewire", "G61"), ("parameter", "G62"), ("excepted", "G63")):
        assert form in hc.FORMS and form in table and code in table[form][1], form
        assert code in hc.EXPLAIN
    for code in ("G64", "G65", "G66", "G67"):
        assert code in hc.EXPLAIN
    assert "G64" in table["registration"][1] and "G65" in table["member"][1] and "G66" in table["guard"][1]
    assert "unknown" not in table and hc.FORMS[-1] == "unknown"


def test_hand_fields_survive_the_new_forms(tmp_path):
    text = top("  x = StealthX(this, x);" + MARK)
    root = series(tmp_path, text)
    entries = hl.expected(root, FOLDER)
    assert entries[0]["form"] == "rewire"
    entries[0].update(anchor="int x = 1;", why="the variable is born there")
    series(tmp_path, text, entries)
    again = hl.expected(root, FOLDER)[0]
    assert (again["anchor"], again["why"], again["test"]) == ("int x = 1;", "the variable is born there", "wrapper:tests/test_a.py::test_b")
