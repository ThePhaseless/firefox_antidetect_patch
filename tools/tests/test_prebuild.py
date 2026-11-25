"""tools/prebuild.py: each of its checks (1 to 11) shown red on a synthetic tree and green on the fixed one, and
the text helpers they stand on.

    python -m pytest -q tools/tests/test_prebuild.py
"""
import sys
from pathlib import Path

import pytest

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


def test_restored_check_5_only_names_of_ours_never_a_name_the_tag_has():
    base = "class F {\n  int mA;\n  nsPresContext* mCtx;\n  int StealthFlag;\n  int mStealthFlag;\n};\n"
    tag_f = "class F {\n  int mA;\n};\n"
    use = {"dom/Own.cpp": "int G(F* f, nsPresContext* c) { return c ? 1 : 0; }\n"}

    def project(tag_extra):
        tag = {"dom/F.h": tag_f, **tag_extra}
        head = {"dom/F.h": tag_f, **use}
        return pb.Project(pb.MemTree(tag), pb.MemTree(head), pb.MemTree({"dom/F.h": base, **use}))
    # red: nobody has nsPresContext in the tag, it appears only in lines of ours: the use is reported
    found = pb.check_restored(project({}))
    assert [f.what.split("`")[1] for f in found] == ["nsPresContext"], [f.what for f in found]
    # green: the tag has it in a file the head does not touch (Mozilla's name, as CanvasUtils or to_vec)
    assert pb.check_restored(project({"layout/base/nsPresContext.h": "class nsPresContext {};\n"})) == []
    # a Stealth name is ours whatever the tag says
    own_use = {"dom/Own.cpp": "int G(F* f) { return f->StealthFlag; }\n"}
    p = pb.Project(pb.MemTree({"dom/F.h": tag_f, "dom/Other.h": "int StealthFlag;\n"}),pb.MemTree({"dom/F.h": tag_f, **own_use}), pb.MemTree({"dom/F.h": base, **own_use}))
    assert [f.what.split("`")[1] for f in pb.check_restored(p)] == ["StealthFlag"]
    assert pb.OURS_NAME.match("Stealth") and pb.OURS_NAME.match("stealth_x") and pb.OURS_NAME.match("nr_stealth_x")
    assert not pb.OURS_NAME.match("nsPresContext") and not pb.OURS_NAME.match("mStealthFlag")


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
    f = pb.Finding.failed(1, pb.fail("dom/F.cpp:3", "something is wrong", "do this", pb.RULE_LINK))
    assert f.line() == "FAIL dom/F.cpp:3: something is wrong. Fix: do this. Rule: docs/decisions/hook-02-shape-and-contract.md"
    assert (f.level, f.where, f.what, f.fix) == ("FAIL", "dom/F.cpp:3", "something is wrong", "do this")
    assert f.as_dict()["rule"] == "hook-02-shape-and-contract"
    # a WARN is a note, not a failure: it has no fix and no rule, and the run does not go red for it
    assert pb.Finding("WARN", 1, "dom/F.cpp:3", "the text does not say").line() == "WARN dom/F.cpp:3: cannot tell: the text does not say"


def test_a_fail_finding_built_without_fail_is_refused_with_a_failure():
    with pytest.raises(TypeError) as err:
        pb.Finding("FAIL", 1, "dom/F.cpp:3", "something is wrong", "do this").line()
    assert "built without a fail()" in str(err.value) and ". Fix: build it with Finding.failed" in str(err.value)


def test_every_fail_of_the_checks_names_a_rule_and_a_fix_and_is_not_cut():
    tag, head = fixture()
    head["dom/StealthX.cpp"] = "// no body\n"
    for f in pb.run(project(tag, head), checks=(1,))["findings"]:
        if f.level == "FAIL":
            text = f.line()
            assert text.startswith("FAIL ") and ". Fix: " in text and text.endswith("Rule: docs/decisions/hook-02-shape-and-contract.md")
            assert f.fix and f.failure.rule == "hook-02-shape-and-contract"


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


# ---- 8. removed lines (rule G51)
G51_TAG = "int a = 1;\nint b = 2;\nint c = 3;\nint d = 4;\n"
G51_BASE = "int a = 1;\nint b = 22;\nint c = 3;\nint d = 4;\n"  # one line rewritten
G51_HEAD_MORE = "int a = 11;\nint b = 22;\nint c = 3;\nint d = 44;\n"  # three lines rewritten
G51_HEAD_LESS = G51_TAG  # none: back to the tag


def g51(head_text, hooks=None, scope=None):
    tag, base, head = {"dom/F.cpp": G51_TAG}, {"dom/F.cpp": G51_BASE}, {"dom/F.cpp": head_text}
    return project(tag, head, base, hooks=hooks, scope=scope)


def test_removed_lines_more_than_the_base_is_red_and_fewer_or_equal_is_green():
    red = pb.check_removed_lines(g51(G51_HEAD_MORE))
    assert [(f.level, f.check, f.where) for f in red] == [("FAIL", 8, "dom/F.cpp")]
    assert "1 on the base, 3 on the head" in red[0].what
    assert pb.check_removed_lines(g51(G51_BASE)) == []
    assert pb.check_removed_lines(g51(G51_HEAD_LESS)) == []


def test_removed_lines_a_replaces_note_on_the_file_clears_it_and_another_file_does_not():
    assert pb.check_removed_lines(g51(G51_HEAD_MORE, hooks=[{"file": "dom/F.cpp", "replaces": ["a/x", "a/y"]}])) == []
    assert len(pb.check_removed_lines(g51(G51_HEAD_MORE, hooks=[{"file": "dom/Other.cpp", "replaces": ["a/x"]}]))) == 1


def test_removed_lines_a_deleted_file_counts_all_its_lines_and_scope_limits_the_files():
    tag, base = {"dom/F.cpp": G51_TAG}, {"dom/F.cpp": G51_BASE}
    assert [r[:3] for r in pb.removed_rows(project(tag, {}, base))] == [("dom/F.cpp", 1, 4)]
    assert pb.check_removed_lines(project(tag, {}, base))[0].level == "FAIL"
    assert pb.check_removed_lines(g51(G51_HEAD_MORE, scope={"other/File.cpp"})) == []


def test_removed_lines_needs_a_base_and_run_reports_check_8():
    tag, head = fixture()
    res = pb.run(project(tag, head), (8,))
    assert res["findings"] == []
    assert "prebuild 8 removed lines not more than the base: skipped (needs --base)" in pb.report(res, project(tag, head), (8,))
    res = pb.run(g51(G51_HEAD_MORE), (8,))
    assert [f.check for f in res["findings"]] == [8]
    assert "prebuild 8 removed lines not more than the base: 1 FAIL" in pb.report(res, g51(G51_HEAD_MORE), (8,))


# ============================================================================================ 9. binding headers
# Every fixture of checks 9 to 11 goes through run(): a prebuild without the check returns no finding of that number, so each red case fails on it.
def only(project_, n):
    return [f for f in pb.run(project_, checks=(n,))["findings"] if f.check == n]


WEBGL_IDL = """\
[Exposed=(Window,Worker)]
interface WebGLRenderingContext {
};

[Exposed=(Window,Worker), LegacyNoInterfaceObject]
interface WEBGL_debug_renderer_info {
  const GLenum UNMASKED_VENDOR_WEBGL = 0x9245;
};

partial interface Navigator {
};
"""


def binding_fixture(include_line, hook_line=None):
    """A tag with some webidl files and a head with a file of ours (and, with hook_line, a Mozilla file) that includes a Binding header."""
    tag = {"dom/webidl/WebGLRenderingContext.webidl": WEBGL_IDL, "dom/webidl/Navigator.webidl": "interface Navigator {};\n",
           "dom/webidl/moz.build": 'GENERATED_WEBIDL_FILES = [\n    "CSSStyleProperties.webidl",\n]\nGENERATED_EVENTS_WEBIDL_FILES = [\n    "AddonEvent",\n]\n',
           "dom/Host.cpp": "int a;\nint b;\n"}
    head = dict(tag)
    head["gfx/StealthGl.cpp"] = "%s\nint StealthGl() { return 1; }\n" % include_line
    if hook_line:
        head["dom/Host.cpp"] = "int a;\n%s\nint b;\n" % hook_line
    return project(tag, head)


def test_binding_header_of_an_interface_declared_inside_another_webidl_is_red_and_names_the_header_that_exists():
    found = only(binding_fixture('#include "mozilla/dom/WEBGL_debug_renderer_infoBinding.h"'), 9)
    assert [(f.level, f.where) for f in found] == [("FAIL", "gfx/StealthGl.cpp:1")], texts(found)
    assert "does not exist" in found[0].what and "mozilla/dom/WebGLRenderingContextBinding.h" in found[0].fix
    assert found[0].failure.rule == "hook-02-shape-and-contract"


def test_binding_header_that_a_webidl_file_generates_is_green():
    for name in ("WebGLRenderingContext", "Navigator", "CSSStyleProperties", "AddonEvent"):
        assert only(binding_fixture('#include "mozilla/dom/%sBinding.h"' % name), 9) == [], name
    assert only(binding_fixture("#include <mozilla/dom/NavigatorBinding.h>"), 9) == []


def test_binding_header_no_webidl_declares_is_red_and_says_so():
    found = only(binding_fixture('#include "mozilla/dom/NoSuchThingBinding.h"'), 9)
    assert len(found) == 1 and "no .webidl file of the tree declares NoSuchThing" in found[0].fix


def test_binding_header_a_partial_interface_does_not_generate_the_header_of_its_name():
    found = only(binding_fixture('#include "mozilla/dom/Navigator2Binding.h"'), 9)
    assert len(found) == 1 and "no .webidl file" in found[0].fix


def test_binding_header_on_a_hook_line_is_checked_too_and_a_comment_is_not():
    red = only(binding_fixture("// nothing", '#include "mozilla/dom/WEBGL_debug_renderer_infoBinding.h"  // STEALTH-HOOK(a/b)'), 9)
    assert [(f.level, f.where) for f in red] == [("FAIL", "dom/Host.cpp:2")], texts(red)
    assert only(binding_fixture('// #include "mozilla/dom/NoSuchThingBinding.h"'), 9) == []


# ============================================================================================ 10. this from a const member
CONST_TAG = """\
namespace mozilla {

bool ClientWebGLContext::ReadPixels(const A& aDesc, B& aRange) const {
  const auto& range = aRange;
  return true;
}

}  // namespace mozilla
"""
CONST_HOOK = "  bool succeeded = StealthDoReadPixels(this, aDesc, *range);  // STEALTH-HOOK(a/b)"
CONST_DECL = """\
namespace mozilla {
class ClientWebGLContext;
bool StealthDoReadPixels(%s aThis, const A& aDesc, const B& aRange);
}  // namespace mozilla
"""


def const_fixture(const=True, param="ClientWebGLContext*", hook=CONST_HOOK, decl=None):
    """A const (or not) member function of Mozilla's with a hook line at line 5, and our declaration of the function it calls."""
    tag = {"dom/Host.cpp": CONST_TAG if const else CONST_TAG.replace(") const {", ") {")}
    line_before = "  const auto& range = aRange;\n"
    head = {"dom/Host.cpp": tag["dom/Host.cpp"].replace(line_before, line_before + hook + "\n"),
            "dom/StealthRead.h": decl if decl is not None else CONST_DECL % param}
    return project(tag, head)


def test_this_passed_from_a_const_member_to_a_non_const_pointer_is_red():
    found = only(const_fixture(), 10)
    assert [(f.level, f.where) for f in found] == [("FAIL", "dom/Host.cpp:5")], texts(found)
    assert "const member function ClientWebGLContext::ReadPixels" in found[0].what and "parameter 1" in found[0].what
    assert "`const ClientWebGLContext*`" in found[0].fix
    assert found[0].failure.rule == "hook-02-shape-and-contract"


def test_this_passed_from_a_const_member_to_a_const_parameter_is_green():
    assert only(const_fixture(param="const ClientWebGLContext*"), 10) == []
    assert only(const_fixture(param="ClientWebGLContext const*"), 10) == []


def test_this_passed_from_a_non_const_member_is_green():
    assert only(const_fixture(const=False), 10) == []


def test_star_this_into_a_non_const_reference_is_red_and_into_a_const_reference_or_a_copy_is_green():
    hook = "  bool succeeded = StealthDoReadPixels(*this, aDesc, *range);  // STEALTH-HOOK(a/b)"
    assert [f.level for f in only(const_fixture(hook=hook, param="ClientWebGLContext&"), 10)] == ["FAIL"]
    assert only(const_fixture(hook=hook, param="const ClientWebGLContext&"), 10) == []
    assert only(const_fixture(hook=hook, param="ClientWebGLContext"), 10) == []


def test_this_check_an_unreadable_case_is_a_note_that_names_the_hook_and_never_a_pass():
    note = only(const_fixture(decl="// no declaration of ours\n"), 10)
    assert [(f.level, f.where) for f in note] == [("NOTE", "dom/Host.cpp:5")], texts(note)
    assert "StealthDoReadPixels" in note[0].what and note[0].line().startswith("NOTE dom/Host.cpp:5: cannot tell: ")
    smart = only(const_fixture(param="RefPtr<ClientWebGLContext>"), 10)
    assert [f.level for f in smart] == ["NOTE"], texts(smart)
    template = ("namespace mozilla {\ntemplate <typename T>\nbool StealthDoReadPixels(T* aThis, const A& aDesc, const B& aRange);\n}\n")
    assert [f.level for f in only(const_fixture(decl=template), 10)] == ["NOTE"]


def test_this_check_a_hook_inside_a_macro_is_a_note():
    hook = "#define STEALTH_READ() StealthDoReadPixels(this, aDesc, *range) /* STEALTH-HOOK(a/b) */"
    note = only(const_fixture(hook=hook), 10)
    assert [f.level for f in note] == ["NOTE"] and "inside a macro" in note[0].what, texts(note)


def test_this_check_a_note_does_not_change_the_exit_code_and_the_report_counts_it():
    p = const_fixture(decl="// none\n")
    res = pb.run(p, checks=(10,))
    assert not any(f.level == "FAIL" for f in res["findings"])
    assert "prebuild 10 this from a const member: 0 FAIL, 0 WARN, 1 NOTE" in pb.report(res, p, (10,))


# ============================================================================================ 11. refcounted class on the stack
MODULE_RECORD_H = """\
namespace mozilla {
class ModuleRecord final {
 public:
  NS_INLINE_DECL_THREADSAFE_REFCOUNTING(ModuleRecord)
  explicit ModuleRecord(const wchar_t* aPath);

 private:
  ~ModuleRecord() = default;
};
class Plain {
 public:
  explicit Plain(int a);
  ~Plain();
};
class Hidden {
 public:
  explicit Hidden(int a);
 protected:
  ~Hidden() = default;
};
struct Open {
  Open();
};
}  // namespace mozilla
"""


def stack_fixture(body):
    tag = {"toolkit/xre/dllservices/UntrustedModulesData.h": MODULE_RECORD_H}
    head = dict(tag)
    head["toolkit/xre/gtest/TestStealthNt.cpp"] = '#include "UntrustedModulesData.h"\nTEST(StealthNt, A) {\n%s\n}\n' % body
    return project(tag, head)


def test_refcounted_class_built_on_the_stack_is_red_and_the_fix_builds_it_on_the_heap():
    found = only(stack_fixture("  mozilla::ModuleRecord control(ntdllNt);"), 11)
    assert [(f.level, f.where) for f in found] == [("FAIL", "toolkit/xre/gtest/TestStealthNt.cpp:3")], texts(found)
    assert "NS_INLINE_DECL_THREADSAFE_REFCOUNTING" in found[0].what and "private destructor" in found[0].what
    assert "RefPtr<ModuleRecord> control = new ModuleRecord(ntdllNt);" in found[0].fix and "MakeRefPtr<ModuleRecord>(ntdllNt)" in found[0].fix
    assert found[0].failure.rule == "hook-02-shape-and-contract"


def test_refcounted_class_on_the_stack_every_shape_of_the_declaration_is_found():
    for body in ("  ModuleRecord control(ntdllNt);", "  const mozilla::ModuleRecord control{ntdllNt};", "  mozilla::Hidden h(1);", "  mozilla::Hidden h;"):
        assert len(only(stack_fixture(body), 11)) == 1, body


def test_refcounted_class_on_the_heap_or_an_ordinary_class_on_the_stack_is_green():
    for body in ("  RefPtr<mozilla::ModuleRecord> control = new mozilla::ModuleRecord(ntdllNt);",
                 "  RefPtr<mozilla::ModuleRecord> control = MakeRefPtr<mozilla::ModuleRecord>(ntdllNt);",
                 "  mozilla::ModuleRecord* control = nullptr;", "  mozilla::Plain p(1);", "  mozilla::Open o;", "  int x;", "  return;",
                 "  other::ModuleRecord control(ntdllNt);"):
        assert only(stack_fixture(body), 11) == [], body


def test_refcounted_class_on_the_stack_in_a_comment_or_a_string_is_not_one():
    assert only(stack_fixture('  // mozilla::ModuleRecord control(ntdllNt);\n  const char* s = "ModuleRecord control(x);";'), 11) == []


# ============================================================================================ the three checks in the run
def test_the_default_run_and_the_report_name_checks_9_to_11():
    assert pb.CHECK_NAMES[9] and pb.CHECK_NAMES[10] and pb.CHECK_NAMES[11]
    tag, head = fixture()
    res = pb.run(project(tag, head))
    assert {9, 10, 11} <= set(res["times"])


def test_refcounted_class_with_the_name_of_a_class_in_a_source_file_or_defined_in_the_file_itself_is_the_one_the_file_means():
    # the real near miss: our test defines its own plain FakeChannel while another test's source file defines a refcounted one
    other = {"uriloader/preload/gtest/TestFetchPreloader.cpp": "class FakeChannel : public nsIChannel {\n NS_DECL_ISUPPORTS\n private:\n ~FakeChannel() = default;\n};\n"}
    own = '#include "UntrustedModulesData.h"\nstruct FakeChannel {\n  int x;\n};\nTEST(StealthNt, A) {\n  FakeChannel channel;\n}\n'

    def build(own_text, tag_extra):
        tag = {"toolkit/xre/dllservices/UntrustedModulesData.h": MODULE_RECORD_H, **tag_extra}
        return project(tag, {**tag, "toolkit/xre/gtest/TestStealthNt.cpp": own_text})

    assert only(build(own, other), 11) == []                                                    # defined here, not refcounted
    assert only(build(own.replace("int x;", "NS_INLINE_DECL_REFCOUNTING(FakeChannel)"), other), 11)[0].level == "FAIL"   # defined here, refcounted
    elsewhere = own.replace("struct FakeChannel {\n  int x;\n};\n", "")
    assert only(build(elsewhere, other), 11) == []                                              # a class of a source file is not seen from another file


def test_refcounted_class_two_headers_of_one_name_that_disagree_are_told_apart_by_the_includes_or_are_a_note():
    plain = {"dom/a/Thing.h": "class Thing { public: Thing(); };\n"}
    counted = {"dom/b/Thing.h": "class Thing { public: NS_INLINE_DECL_REFCOUNTING(Thing) private: ~Thing(); };\n"}

    def build(include):
        tag = {**plain, **counted}
        body = '%s\nTEST(StealthNt, A) {\n  Thing t;\n}\n' % include
        return project(tag, {**tag, "dom/gtest/TestStealthThing.cpp": body})

    assert [f.level for f in only(build('#include "dom/b/Thing.h"'), 11)] == ["FAIL"]
    assert only(build('#include "dom/a/Thing.h"'), 11) == []
    note = only(build('// no include'), 11)
    assert [f.level for f in note] == ["NOTE"] and "does not say which it means" in note[0].what
