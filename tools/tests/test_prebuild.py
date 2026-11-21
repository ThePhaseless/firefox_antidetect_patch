"""tools/prebuild.py: each of its seven checks shown red on a synthetic tree and green on the fixed one, and
the text helpers they stand on.

    python -m pytest -q tools/tests/test_prebuild.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prebuild as pb  # noqa: E402

HOST_TAG = """\
#include "Foo.h"

namespace mozilla::dom {

int Foo::Run(int aX) {
  int y = aX + 1;
  return y;
}

}  // namespace mozilla::dom
"""

HOST_HEAD = """\
#include "Foo.h"
#include "StealthX.h"  // STEALTH-HOOK(a/b)

namespace mozilla::dom {

int Foo::Run(int aX) {
  if (StealthDoIt(aX, 2)) return 0;  // STEALTH-HOOK(a/b)
  int y = aX + 1;
  return y;
}

}  // namespace mozilla::dom
"""

HEADER = """\
#ifndef StealthX_h
#define StealthX_h
namespace mozilla::dom {
bool StealthDoIt(int aA, int aB);
}  // namespace mozilla::dom
#endif
"""

SOURCE = """\
#include "StealthX.h"
namespace mozilla::dom {
bool StealthDoIt(int aA, int aB) { return aA == aB; }
}  // namespace mozilla::dom
"""

MOZBUILD_TAG = 'SOURCES += ["Other.cpp"]\n'
MOZBUILD_HEAD = 'SOURCES += ["Other.cpp"]\nSOURCES += ["StealthX.cpp"]  # STEALTH-HOOK(a/b)\n'


def project(tag, head, base=None, hooks=None, scope=None):
    return pb.Project(pb.MemTree(tag), pb.MemTree(head), pb.MemTree(base) if base is not None else None,
                      scope=scope, hooks_entries=hooks or [])


def fixture(**over):
    """A tag and a head where a Mozilla host calls a function of ours; `over` replaces head files (None drops one)."""
    tag = {"dom/Foo.cpp": HOST_TAG, "dom/Foo.h": "class Foo {};\n", "dom/moz.build": MOZBUILD_TAG}
    head = {"dom/Foo.cpp": HOST_HEAD, "dom/Foo.h": "class Foo {};\n", "dom/moz.build": MOZBUILD_HEAD,
            "dom/StealthX.h": HEADER, "dom/StealthX.cpp": SOURCE}
    for k, v in over.items():
        if v is None:
            head.pop(k, None)
        else:
            head[k] = v
    return tag, head


def levels(found):
    return sorted((f.level, f.check) for f in found)


def texts(found):
    return " | ".join(f.line() for f in found)


# ============================================================================================ helpers
def test_blank_keeps_offsets_and_drops_comments_strings_and_directives():
    src = '#include "a.h"\nint x = 1; // StealthFoo(\nconst char* s = "StealthBar(";\n/* StealthBaz( */ int y;\n'
    out = pb.blank(src)
    assert len(out) == len(src) and out.count("\n") == src.count("\n")
    assert "Stealth" not in out and "int x = 1;" in out and "int y;" in out


def test_blank_handles_raw_strings():
    src = 'auto s = R"x(a // not a comment ) ")x"; int z;\n'
    out = pb.blank(src)
    assert len(out) == len(src) and "comment" not in out and out.rstrip().endswith("; int z;")


def test_split_args_and_param_range():
    assert pb.split_args("a, f(b, c), {d, e}, g<int, int>(h)") == ["a", "f(b, c)", "{d, e}", "g<int, int>(h)"]
    assert pb.split_args("") == []
    assert pb.param_range("") == (0, 0)
    assert pb.param_range("void") == (0, 0)
    assert pb.param_range("int a, int b") == (2, 2)
    assert pb.param_range("int a, int b = 3") == (1, 2)
    assert pb.param_range("const char* aFmt, ...") == (1, None)
    assert pb.param_range("Guards&... guards") == (0, None)
    assert pb.param_range("std::map<int, int> a, int b = f(1, 2)") == (1, 2)


def test_scan_finds_namespaces_bodies_and_usings():
    src = "using namespace mozilla::gfx;\nnamespace a::b {\nclass C {\n void f() { x(); }\n};\nvoid g() {}\n}\n"
    sc = pb.CppScan("x.cpp", src)
    off = src.index("x();")
    assert sc.body_at(off) is not None
    assert sc.namespaces_at(off) == ["a", "b"]
    assert sc.scope_at(off) == ["a", "b", "C"]
    assert sc.usings[0][1] == ["mozilla", "gfx"]


def test_scan_survives_a_macro_before_the_namespace_and_extern_c():
    src = 'NS_IMPL_FOO(Canvas)\n\nnamespace mozilla::dom {\nextern "C" {\nint StealthA(int a);\n}\n}\n'
    sc = pb.CppScan("x.cpp", src)
    d = pb.find_decls(sc, {"StealthA"})
    assert len(d) == 1 and d[0].scope == ["mozilla", "dom"] and not d[0].is_def


def test_find_decls_tells_a_declaration_from_a_definition_and_a_call():
    src = "bool StealthA(int a);\nbool StealthA(int a) { return StealthB(a); }\nstatic int v = StealthC(1);\n"
    sc = pb.CppScan("x.cpp", src)
    got = {(d.name, d.is_def) for d in pb.find_decls(sc, {"StealthA", "StealthB", "StealthC"})}
    assert got == {("StealthA", False), ("StealthA", True)}


# ============================================================================================ 1. hook links
def test_link_green():
    tag, head = fixture()
    found = pb.check_hook_links(project(tag, head))
    assert found == [], texts(found)


def test_link_no_declaration_is_red():
    tag, head = fixture(**{"dom/StealthX.h": None, "dom/StealthX.cpp": "bool StealthOther() { return true; }\n"})
    head["dom/Foo.cpp"] = HOST_HEAD.replace('#include "StealthX.h"  // STEALTH-HOOK(a/b)\n', "")
    found = pb.check_hook_links(project(tag, head))
    assert any("no declaration" in f.what for f in found), texts(found)


def test_link_host_that_does_not_include_the_header_is_red_and_fixed_by_the_include():
    tag, head = fixture()
    head["dom/Foo.cpp"] = HOST_HEAD.replace('#include "StealthX.h"  // STEALTH-HOOK(a/b)\n', "")
    found = pb.check_hook_links(project(tag, head))
    assert any("does not include it" in f.what for f in found), texts(found)
    tag, head = fixture()
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_include_through_a_header_of_ours_is_enough():
    tag, head = fixture()
    head["dom/Foo.cpp"] = HOST_HEAD.replace('#include "StealthX.h"', '#include "StealthY.h"')
    head["dom/StealthY.h"] = '#include "StealthX.h"\n'
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_declaration_without_a_body_is_red():
    tag, head = fixture(**{"dom/StealthX.cpp": "// nothing\n"})
    found = pb.check_hook_links(project(tag, head))
    assert any("no body" in f.what for f in found), texts(found)


def test_link_a_cpp_no_moz_build_names_is_red_and_an_include_of_it_is_green():
    tag, head = fixture(**{"dom/moz.build": MOZBUILD_TAG})
    found = pb.check_hook_links(project(tag, head))
    assert any("no moz.build names" in f.what for f in found), texts(found)
    head["dom/Other.cpp"] = '#include "StealthX.cpp"\n'
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_a_definition_in_the_header_needs_no_moz_build():
    tag, head = fixture(**{"dom/StealthX.cpp": None, "dom/moz.build": MOZBUILD_TAG,
                           "dom/StealthX.h": HEADER.replace("bool StealthDoIt(int aA, int aB);",
                                                            "inline bool StealthDoIt(int aA, int aB) { return aA == aB; }")})
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_argument_count_red_green_and_default_arguments():
    tag, head = fixture()
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "StealthDoIt(aX)")
    found = pb.check_hook_links(project(tag, head))
    assert any("1 argument" in f.what for f in found), texts(found)
    head["dom/StealthX.h"] = HEADER.replace("int aB)", "int aB = 3)")
    head["dom/StealthX.cpp"] = SOURCE
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_arguments_spanning_lines_and_nested_calls_are_counted_once():
    tag, head = fixture()
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "StealthDoIt(Max(aX,\n                         3),\n                  2)")
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_an_overload_with_the_right_count_is_enough():
    tag, head = fixture()
    head["dom/StealthX.h"] = HEADER.replace("bool StealthDoIt(int aA, int aB);",
                                            "bool StealthDoIt(int aA);\nbool StealthDoIt(int aA, int aB);")
    head["dom/StealthX.cpp"] = SOURCE.replace("bool StealthDoIt(int aA, int aB)", "bool StealthDoIt(int aA) { return aA; }\nbool StealthDoIt(int aA, int aB)")
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "StealthDoIt(aX)")
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_namespace_the_call_cannot_reach_is_red_and_the_qualified_call_is_green():
    tag, head = fixture()
    # declared in mozilla::gfx, called from mozilla::dom without a name for gfx
    head["dom/StealthX.h"] = HEADER.replace("mozilla::dom", "mozilla::gfx")
    head["dom/StealthX.cpp"] = SOURCE.replace("mozilla::dom", "mozilla::gfx")
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "StealthDoIt(1, 2)")
    found = pb.check_hook_links(project(tag, head))
    assert any(f.level == "FAIL" and "neither names" in f.what for f in found), texts(found)
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "gfx::StealthDoIt(aX, 2)")
    assert pb.check_hook_links(project(tag, head)) == []
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "layers::StealthDoIt(aX, 2)")
    assert any(f.level == "FAIL" for f in pb.check_hook_links(project(tag, head)))


def test_link_using_namespace_opens_the_namespace():
    tag, head = fixture()
    head["dom/StealthX.h"] = HEADER.replace("mozilla::dom", "mozilla::gfx")
    head["dom/StealthX.cpp"] = SOURCE.replace("mozilla::dom", "mozilla::gfx")
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "StealthDoIt(1, 2)").replace(
        "namespace mozilla::dom {", "using namespace mozilla::gfx;\n\nnamespace mozilla::dom {")
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_an_unqualified_call_with_arguments_may_be_found_by_adl_so_it_is_a_warning():
    tag, head = fixture()
    head["dom/StealthX.h"] = HEADER.replace("mozilla::dom", "mozilla::gfx")
    head["dom/StealthX.cpp"] = SOURCE.replace("mozilla::dom", "mozilla::gfx")
    found = pb.check_hook_links(project(tag, head))
    assert levels(found) == [("WARN", 1)], texts(found)


def test_link_a_name_listed_as_own_function_in_hooks_json_is_checked_too():
    tag, head = fixture()
    head["dom/Foo.cpp"] = HOST_HEAD.replace("StealthDoIt(aX, 2)", "DoThing(aX, 2)")
    assert pb.check_hook_links(project(tag, head)) == []
    hooks = [{"file": "dom/Foo.cpp", "own_function": ["DoThing"]}]
    found = pb.check_hook_links(project(tag, head, hooks=hooks))
    assert any("DoThing" in f.what and "no declaration" in f.what for f in found), texts(found)


def test_link_an_added_include_of_a_missing_header_of_ours_is_red():
    tag, head = fixture()
    head["dom/Foo.cpp"] = HOST_HEAD.replace('"StealthX.h"', '"StealthMissing.h"')
    found = pb.check_hook_links(project(tag, head))
    assert any("names no file of ours" in f.what for f in found), texts(found)


def test_link_a_local_variable_with_a_stealth_name_is_not_a_call():
    tag, head = fixture()
    head["dom/Foo.cpp"] = HOST_HEAD.replace("  int y = aX + 1;", "  const Thing stealthAnswer(aX, 3);\n  int y = aX + 1;")
    assert pb.check_hook_links(project(tag, head)) == []


def test_link_js_module_must_import_and_the_count_must_match():
    tag = {"toolkit/A.sys.mjs": "export const A = {\n  run(x) {\n    return x;\n  },\n};\n"}
    head = {"toolkit/A.sys.mjs": 'import { stealthGo } from "resource://x/StealthGo.sys.mjs";\nexport const A = {\n  run(x) {\n    if (stealthGo(x, 1)) { return 0; }  // STEALTH-HOOK(a/b)\n    return x;\n  },\n};\n',
            "toolkit/StealthGo.sys.mjs": "export function stealthGo(a, b) {\n  return a === b;\n}\n"}
    assert pb.check_hook_links(project(tag, head)) == []
    bad = dict(head, **{"toolkit/A.sys.mjs": head["toolkit/A.sys.mjs"].replace('import { stealthGo } from "resource://x/StealthGo.sys.mjs";\n', "")})
    found = pb.check_hook_links(project(tag, bad))
    assert any("neither imports nor declares" in f.what for f in found), texts(found)
    bad = dict(head, **{"toolkit/A.sys.mjs": head["toolkit/A.sys.mjs"].replace("stealthGo(x, 1)", "stealthGo(x)")})
    found = pb.check_hook_links(project(tag, bad))
    assert any("1 argument" in f.what for f in found), texts(found)


# ============================================================================================ 2. rename consistency
WRAP_TAG = {
    "dom/Foo.h": "class Foo {\n public:\n  nsresult Bar(int aX) const;\n};\n",
    "dom/Foo.cpp": "nsresult Foo::Bar(int aX) const {\n  return NS_OK;\n}\n",
    "dom/Baz.cpp": "void Baz() {\n  Do();\n}\n",
}
WRAP_HEAD = {
    "dom/Foo.h": "class Foo {\n public:\n  nsresult Bar(int aX) const;\n  nsresult Bar_Mozilla(int aX) const;  // STEALTH-HOOK(a/b)\n};\n",
    "dom/Foo.cpp": "nsresult Foo::Bar_Mozilla(int aX) const {  // STEALTH-HOOK(a/b)\n  return NS_OK;\n}\n",
    "dom/Baz.cpp": "void Baz() {\n  Do();\n}\n",
    "dom/StealthFoo.cpp": "nsresult Foo::Bar(int aX) const {\n  return Bar_Mozilla(aX);\n}\n",
}


def wrap_project(**over):
    head = dict(WRAP_HEAD)
    head.update(over)
    return project(WRAP_TAG, {k: v for k, v in head.items() if v is not None})


def test_rename_green():
    found = pb.check_rename(wrap_project())
    assert found == [], texts(found)


def test_rename_class_header_not_renamed_is_red():
    found = pb.check_rename(wrap_project(**{"dom/Foo.h": WRAP_TAG["dom/Foo.h"]}))
    assert any("no changed Mozilla header declares" in f.what for f in found), texts(found)


def test_rename_ours_missing_is_red():
    found = pb.check_rename(wrap_project(**{"dom/StealthFoo.cpp": None}))
    assert any("no file of ours defines" in f.what for f in found), texts(found)


def test_rename_parameter_list_and_trailing_qualifier_must_match():
    found = pb.check_rename(wrap_project(**{"dom/StealthFoo.cpp": "nsresult Foo::Bar(long aX) const {\n  return Bar_Mozilla(aX);\n}\n"}))
    assert any("differs from ours" in f.what for f in found), texts(found)
    found = pb.check_rename(wrap_project(**{"dom/StealthFoo.cpp": "nsresult Foo::Bar(int aX) {\n  return Bar_Mozilla(aX);\n}\n"}))
    assert any("differs from ours" in f.what for f in found), texts(found)
    # parameter names are not part of the signature
    assert pb.check_rename(wrap_project(**{"dom/StealthFoo.cpp": "nsresult Foo::Bar(int aOther) const {\n  return Bar_Mozilla(aOther);\n}\n"})) == []


def test_rename_direct_caller_in_a_mozilla_file_is_red_unless_hooks_json_allows_it():
    caller = "void Baz() {\n  Do();\n  foo->Bar_Mozilla(1);  // STEALTH-HOOK(a/b)\n}\n"
    found = pb.check_rename(wrap_project(**{"dom/Baz.cpp": caller}))
    assert any("called from a Mozilla file" in f.what for f in found), texts(found)
    head = dict(WRAP_HEAD, **{"dom/Baz.cpp": caller})
    hooks = [{"file": "dom/Baz.cpp", "line": "  foo->Bar_Mozilla(1);  // STEALTH-HOOK(a/b)", "calls_mozilla": True}]
    assert pb.check_rename(project(WRAP_TAG, head, hooks=hooks)) == []


def test_rename_of_a_name_that_hooks_json_lists_is_checked_too():
    tag = {"dom/F.cpp": "int Old(int a) {\n  return a;\n}\n"}
    head = {"dom/F.cpp": "int Moz_Body(int a) {  // STEALTH-HOOK(a/b)\n  return a;\n}\n"}
    assert pb.check_rename(project(tag, head)) == []          # not a *_Mozilla name: nothing to check
    found = pb.check_rename(project(tag, head, hooks=[{"file": "dom/F.cpp", "renamed": "Moz_Body"}]))
    assert any("no file of ours defines" in f.what for f in found), texts(found)


# ============================================================================================ 3. Mozilla tokens
TOK_TAG = {"dom/F.cpp": "void F() {\n  int a = 1;\n  Do(a);\n  return;\n}\n"}


def tokens_found(head_text, hooks=None, tag=None):
    f, changes = pb.check_mozilla_tokens(project(tag or TOK_TAG, {"dom/F.cpp": head_text}, hooks=hooks))
    return f, changes


def test_tokens_a_pure_hook_line_changes_no_mozilla_line():
    f, changes = tokens_found("void F() {\n  StealthF();  // STEALTH-HOOK(a/b)\n  int a = 1;\n  Do(a);\n  return;\n}\n")
    assert f == [] and changes == []


def test_tokens_a_marker_added_to_mozillas_own_line_is_not_a_change():
    f, changes = tokens_found("void F() {\n  int a = 1;  // STEALTH-HOOK(a/b)\n  Do(a);\n  return;\n}\n")
    assert f == [] and changes == []


def test_tokens_a_rewritten_mozilla_line_is_red():
    f, changes = tokens_found("void F() {\n  int a = StealthValue(7);  // STEALTH-HOOK(a/b)\n  Do(a);\n  return;\n}\n", tag=TOK_TAG)
    assert len(changes) == 1 and changes[0]["text"] == "int a = 1;"
    # a declared value is one of the three forms: allowed
    f2, c2 = tokens_found("void F() {\n  int a = 2;  // STEALTH-HOOK(a/b)\n  Do(a);\n  return;\n}\n")
    assert f2 == [] and c2[0]["allowed"] == "form"
    assert f and "Mozilla line changed" in f[0].what


def test_tokens_a_wrapped_expression_is_allowed_and_counted():
    tag = {"dom/F.cpp": "int F() {\n  return Compute(3);\n}\n"}
    f, changes = tokens_found("int F() {\n  return StealthWrap(Compute(3));  // STEALTH-HOOK(a/b)\n}\n", tag=tag)
    assert f == [] and len(changes) == 1 and changes[0]["form"] == "wrap-expression"


def test_tokens_a_removed_line_is_red_and_an_exception_with_the_pm_clears_it():
    head = "void F() {\n  int a = 1;\n  return;\n}\n"
    f, changes = tokens_found(head)
    assert len(f) == 1 and "Do(a);" in f[0].what
    hooks = [{"file": "dom/F.cpp", "kind": "delete", "form": "unknown", "line": "", "removed": "  Do(a);",
              "exception": "pm 21/11: the call is gone with the feature"}]
    f, changes = tokens_found(head, hooks=hooks)
    assert f == [] and changes[0]["allowed"] == "exception"
    hooks[0]["exception"] = "because"
    f, _ = tokens_found(head, hooks=hooks)
    assert len(f) == 1 and "pm approved" in f[0].what


def test_tokens_a_deleted_mozilla_file_is_red():
    f, changes = pb.check_mozilla_tokens(project(TOK_TAG, {}))
    assert len(f) == 1 and "whole file deleted" in f[0].what
    assert changes[0]["lines"] == 5


def test_tokens_whitespace_and_line_ending_changes_are_not_changes():
    f, changes = tokens_found("void F() {\n    int   a = 1;\n  Do(a);\n  return;\n}\n")
    assert f == [] and changes == []


# ============================================================================================ 4. equivalence
def klass(path, a, b):
    return pb.classify_pair(path, a, b)["class"]


def test_equivalence_comments_whitespace_and_markers_are_identical():
    a = "int F() {\n  return 1;\n}\n"
    b = "int  F() {  // STEALTH-HOOK(a/b)\n  /* note */ return 1; // why\n}\n"
    assert klass("x.cpp", a, b) == "identical"
    assert klass("x.cpp", a, a) == "identical"


def test_equivalence_a_changed_token_is_changed_with_its_runs():
    a = "int F() {\n  return 1;\n}\nint G() { return 2; }\n"
    b = "int F() {\n  return 3;\n}\nint G() { return 4; }\n"
    r = pb.classify_pair("x.cpp", a, b)
    assert r["class"] == "changed" and r["runs"] == 2


def test_equivalence_a_string_literal_is_a_token_and_a_comment_inside_it_is_not_a_comment():
    assert klass("x.cpp", 'auto s = "a // b";\n', 'auto s = "a // c";\n') == "changed"
    assert klass("x.cpp", 'auto s = "a";\n', 'auto s = "a"; // x\n') == "identical"
    assert klass("x.cpp", 'auto s = R"x(a // b)x";\n', 'auto s = R"x(a // c)x";\n') == "changed"


def test_equivalence_moved_or_added_includes_are_include_order():
    a = '#include "a.h"\n#include "b.h"\nint F() { return 1; }\n'
    b = '#include "b.h"\n#include "c.h"\n#include "a.h"\nint F() { return 1; }\n'
    assert klass("x.cpp", a, b) == "include-order"
    assert klass("x.cpp", a, b.replace("return 1", "return 2")) == "changed"


def test_equivalence_js_imports_and_template_literals():
    a = 'import { a } from "x";\nimport { b } from "y";\nconst s = `a // ${b}`;\n'
    b = 'import { b } from "y";\nimport { a } from "x";\nconst s = `a // ${b}`;\n'
    assert klass("m.sys.mjs", a, b) == "include-order"
    assert klass("m.sys.mjs", a, b.replace("${b}", "${c}")) == "changed"
    assert klass("m.sys.mjs", "let a = 1; // x\n", "let a = 1;\n") == "identical"


def test_equivalence_hash_comment_languages():
    assert klass("moz.build", 'SOURCES += ["a.cpp"]  # x\n', 'SOURCES += ["a.cpp"]\n') == "identical"
    assert klass("moz.build", 'SOURCES += ["a.cpp"]\n', 'SOURCES += ["b.cpp"]\n') == "changed"
    assert klass("t.py", 'x = "a # b"\n', 'x = "a # c"\n') == "changed"
    assert klass("t.py", "import os\nimport re\nx = 1\n", "import re\nimport os\nx = 1\n") == "include-order"
    assert klass("t.yml", "a: 1  # c\n", "a: 1\n") == "identical"


def test_equivalence_rust_use_lines_and_added_removed():
    assert klass("l.rs", "use a::b;\nuse c::d;\nfn f() {}\n", "use c::d;\nuse a::b;\nfn f() {}\n") == "include-order"
    assert klass("l.rs", "fn f() {} // x\n", "fn f() {}\n") == "identical"
    assert klass("l.rs", None, "fn f() {}\n") == "added"
    assert klass("l.rs", "fn f() {}\n", None) == "removed"


def test_equivalence_over_two_trees_lists_only_the_files_that_differ():
    base = {"a.cpp": "int a() { return 1; }\n", "b.cpp": "int b() { return 1; }\n", "c.cpp": "int c;\n"}
    head = {"a.cpp": "int a() { return 1; }  // x\n", "b.cpp": "int b() { return 2; }\n", "c.cpp": "int c;\n"}
    rows = pb.check_equivalence(project({}, head, base))
    assert {r["file"]: r["class"] for r in rows} == {"a.cpp": "identical", "b.cpp": "changed"}


# ============================================================================================ 5. restored files
def restored_project(head_f, extra_head=None, base_f=None):
    tag = {"dom/F.h": "class F {\n  int mA;\n};\n"}
    base = {"dom/F.h": base_f or "class F {\n  int mA;\n  int mStealthFlag;\n};\n"}
    head = {"dom/F.h": head_f}
    for t in (base, head):
        t.update(extra_head or {})
    return pb.Project(pb.MemTree(tag), pb.MemTree(head), pb.MemTree(base))


def test_restored_file_with_a_use_of_a_name_only_the_old_hunk_had_is_red():
    use = {"dom/Own.cpp": "int G(F* f) { return f->mStealthFlag; }\n"}
    found = pb.check_restored(restored_project("class F {\n  int mA;\n};\n", use))
    assert len(found) == 1 and "mStealthFlag" in found[0].what and found[0].where == "dom/Own.cpp"


def test_restored_file_green_when_nothing_uses_the_name_or_ours_defines_it():
    assert pb.check_restored(restored_project("class F {\n  int mA;\n};\n")) == []
    use = {"dom/Own.cpp": "int G(F* f) { return StealthValue(); }\n", "dom/Own.h": "int StealthValue();\n"}
    base = "class F {\n  int mA;\n  int StealthValue();\n};\n"
    assert pb.check_restored(restored_project("class F {\n  int mA;\n};\n", use, base)) == []


def test_restored_file_still_changed_in_the_head_is_not_a_restored_file():
    use = {"dom/Own.cpp": "int G(F* f) { return f->mStealthFlag; }\n"}
    p = restored_project("class F {\n  int mA;\n  int mStealthFlag;\n};\n", use)
    assert pb.check_restored(p) == []


# ============================================================================================ 6. our files
def own_project(head, tag=None):
    return pb.Project(pb.MemTree(tag or {"dom/Other.cpp": "int o;\n"}), pb.MemTree(dict(head, **{"dom/Other.cpp": "int o;\n"})))


def test_our_cpp_must_be_named_by_a_build_file_or_included():
    head = {"dom/StealthA.cpp": "int a;\n", "dom/moz.build": 'SOURCES += ["Other.cpp"]\n'}
    found = pb.check_our_files(own_project(head))
    assert [f.where for f in found] == ["dom/StealthA.cpp"]
    head["dom/moz.build"] = 'SOURCES += ["Other.cpp"]\nSOURCES += ["StealthA.cpp"]\n'
    assert pb.check_our_files(own_project(head)) == []
    head["dom/moz.build"] = 'UNIFIED_SOURCES += [\n    "StealthA.cpp",\n]\n'
    assert pb.check_our_files(own_project(head)) == []


def test_our_cpp_named_by_a_build_file_in_a_parent_directory_or_a_common_build():
    head = {"dom/sub/StealthA.cpp": "int a;\n", "dom/moz.build": 'SOURCES += ["sub/StealthA.cpp"]\n'}
    assert pb.check_our_files(own_project(head)) == []
    head = {"dom/sub/StealthA.cpp": "int a;\n", "dom/sub/moz.build": 'include("common.build")\n', "dom/sub/common.build": 'SOURCES += ["StealthA.cpp"]\n'}
    assert pb.check_our_files(own_project(head)) == []


def test_our_modules_need_a_build_file_but_tests_do_not():
    head = {"juggler/A.js": "var a;\n", "juggler/moz.build": ""}
    assert [f.where for f in pb.check_our_files(own_project(head))] == ["juggler/A.js"]
    head["juggler/jar.mn"] = "  content/juggler/A.js (A.js)\n"
    assert pb.check_our_files(own_project(head)) == []
    head = {"juggler/tests/x.test.mjs": "1;\n"}
    assert pb.check_our_files(own_project(head)) == []


def test_our_js_included_by_the_preprocessor_is_shipped():
    head = {"modules/init/StealthPrefs.js": "pref;\n"}
    tag = {"modules/greprefs.js": "pref;\n", "dom/Other.cpp": "int o;\n"}
    p = pb.Project(pb.MemTree(tag), pb.MemTree(dict(head, **{"modules/greprefs.js": "#include init/StealthPrefs.js\n", "dom/Other.cpp": "int o;\n"})))
    assert pb.check_our_files(p) == []
    assert pb.check_our_files(own_project(head))[0].where == "modules/init/StealthPrefs.js"


def test_our_rust_files_need_a_mod_line_even_behind_an_attribute():
    tag = {"gfx/src/server.rs": "fn s() {}\n"}
    head = {"gfx/src/server.rs": '#[path = "stealth_x.rs"] mod stealth_x;\nfn s() {}\n', "gfx/src/stealth_x.rs": "pub fn f() {}\n"}
    assert pb.check_our_files(pb.Project(pb.MemTree(tag), pb.MemTree(head))) == []
    head["gfx/src/server.rs"] = "fn s() {}\n"
    found = pb.check_our_files(pb.Project(pb.MemTree(tag), pb.MemTree(head)))
    assert [f.where for f in found] == ["gfx/src/stealth_x.rs"]


def test_our_files_may_not_share_a_basename():
    head = {"dom/a/StealthW.h": "1;\n", "dom/b/StealthW.h": "2;\n"}
    found = pb.check_our_files(own_project(head))
    assert len(found) == 1 and "G19" in found[0].what
    assert pb.check_our_files(own_project({"dom/a/StealthW.h": "1;\n", "dom/b/StealthV.h": "2;\n"})) == []


# ============================================================================================ 7. gtest filter
WORKFLOW = """\
on:
  workflow_dispatch:
    inputs:
      gtest_filter:
        # note
        description: "gtests=true only"
        default: 'StealthA.*:TestStealthB.*:StealthC.One'
      relaunch_of:
        default: ''
"""


def test_gtest_default_filter_is_read_from_the_workflow():
    assert pb.default_gtest_filter(WORKFLOW) == "StealthA.*:TestStealthB.*:StealthC.One"
    assert pb.default_gtest_filter("on: {}\n") is None


def test_gtest_filter_matching_follows_gtest_patterns():
    f = "A.*:B?.x:-A.bad"
    assert pb.gtest_matches(f, "A.good") and not pb.gtest_matches(f, "A.bad")
    assert pb.gtest_matches(f, "B1.x") and not pb.gtest_matches(f, "B12.x")
    assert pb.gtest_matches("*", "Any.thing")


def gtest_project(test_text):
    head = {".github/workflows/release.yml": WORKFLOW, "dom/test/TestA.cpp": test_text, "dom/Other.cpp": "int o;\n"}
    return pb.Project(pb.MemTree({"dom/Other.cpp": "int o;\n"}), pb.MemTree(head))


def test_gtest_a_suite_the_filter_misses_is_red_and_one_it_matches_is_green():
    found = pb.check_gtest_filter(gtest_project("TEST(StealthZ, One) {}\nTEST_F(StealthZ, Two) {}\n"))
    assert len(found) == 1 and "StealthZ" in found[0].what and "StealthZ.*" in found[0].fix
    assert pb.check_gtest_filter(gtest_project("TEST(StealthA, One) {}\nTEST_F(TestStealthB, Two) {}\n")) == []


def test_gtest_a_suite_matched_in_part_is_red():
    found = pb.check_gtest_filter(gtest_project("TEST(StealthC, One) {}\nTEST(StealthC, Two) {}\n"))
    assert len(found) == 1 and "1 of 2" in found[0].what


def test_gtest_a_test_in_a_comment_is_not_a_suite():
    assert pb.check_gtest_filter(gtest_project("// TEST(StealthZ, One) {}\nTEST(StealthA, One) {}\n")) == []


def test_gtest_no_default_in_the_workflow_is_red():
    p = gtest_project("TEST(StealthA, One) {}\n")
    p.head.files[".github/workflows/release.yml"] = b"on: {}\n"
    assert pb.check_gtest_filter(p)[0].level == "FAIL"


# ============================================================================================ the report
def test_a_finding_prints_in_the_style_of_engine_check():
    f = pb.Finding("FAIL", 1, "dom/F.cpp:3", "something is wrong", "do this")
    assert f.line() == "FAIL dom/F.cpp:3: something is wrong; do this"
    assert pb.Finding("WARN", 1, "dom/F.cpp:3", "the text does not say").line() == "WARN dom/F.cpp:3: cannot tell: the text does not say"


def test_the_run_exit_code_follows_the_fails_and_not_the_warnings():
    tag, head = fixture()
    res = pb.run(project(tag, head), checks=(1, 2, 3))
    assert not any(f.level == "FAIL" for f in res["findings"])
    head["dom/StealthX.cpp"] = "// no body\n"
    res = pb.run(project(tag, head), checks=(1,))
    assert any(f.level == "FAIL" for f in res["findings"])
    text = pb.report(res, project(tag, head), (1,))
    assert text.startswith("FAIL dom/Foo.cpp") and "\r" not in text


def test_the_folder_scope_limits_the_files_checked():
    tag, head = fixture()
    head["dom/StealthX.cpp"] = "// no body\n"
    assert any(f.level == "FAIL" for f in pb.check_hook_links(project(tag, head)))
    assert pb.check_hook_links(project(tag, head, scope={"other/File.cpp"})) == []
