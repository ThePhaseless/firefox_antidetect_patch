"""repo-04 and the one-table rule for the hook contract (docs/decisions/hook-02-shape-and-contract.md):

  * the hook rules are written once, in the RULES table of tools/hook_contract.py, with a fix and a decision that exists; the forms
    in FORMS_TABLE and the meaning of each G code in EXPLAIN; the docs carry them as generated sections that this test compares with
    the generator (`python tools/engine.py docs --check`);
  * every message of tools/hook_contract.py and tools/hooks_list.py is built by fail(): where, what, fix, rule, whole;
  * neither file names a place outside the repository, and every G code a file names is explained.

    python -m pytest tools/tests/test_hook_rules_table.py
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import failure  # noqa: E402
import hook_contract as hc  # noqa: E402
import hooks_list as hl  # noqa: E402

ROOT = TOOLS.parent
FILES = {name: (TOOLS / name).read_text(encoding="utf-8") for name in ("hook_contract.py", "hooks_list.py")}
PREBUILD = (TOOLS / "prebuild.py").read_text(encoding="utf-8")      # prints G19
RULE_IDS = ["C%d" % i for i in range(1, 19)] + ["T1", "T2", "T3"]


# --------------------------------------------------------------------------- the RULES table
def test_the_rules_are_the_hook_rules_c1_to_c18_and_t1_to_t3():
    assert list(hc.RULES) == RULE_IDS


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_each_rule_has_a_text_a_fix_and_a_decision_that_exists(rule_id):
    rule = hc.RULES[rule_id]
    assert rule.id == rule_id and rule.text.strip() and rule.fix.strip()
    assert failure.rule_exists(rule.decision), "%s names no file in docs/decisions/: %s" % (rule_id, rule.decision)
    filled = hc.rule_fix(rule_id, "fingerprint/x", "dom/Foo.cpp", "StealthName")     # every placeholder is one the table fills in
    assert "{" not in filled and "}" not in filled
    if rule.shows:
        assert "{detail}" in rule.shows, rule_id


def test_the_decisions_of_hooks_list_are_the_ones_of_hook_contract():
    assert (hl.D_HOOK02, hl.D_HOOK04, hl.D_PORT06) == (hc.D_HOOK02, hc.D_HOOK04, hc.D_PORT06)


def test_every_rule_id_the_code_names_is_in_the_table():
    named = set()
    for text in FILES.values():
        named |= set(re.findall(r'"((?:C\d+)|(?:T[123]))"', text))
    assert named and named <= set(hc.RULES), sorted(named - set(hc.RULES))


def test_a_fix_never_adds_to_the_debt_list():
    """hook-debt never adds an entry, so no fix of a rule may tell anyone to put the hook in the list."""
    for rule in hc.RULES.values():
        assert "hook-debt" not in rule.fix and "debt list" not in rule.fix, rule.id


# --------------------------------------------------------------------------- the generated sections
def test_the_generated_sections_are_what_the_generator_writes():
    texts, found = hc.generated_docs(ROOT)
    assert found == []
    for rel, text in texts.items():
        assert hc._read(ROOT / rel) == text, "%s: run python tools/engine.py docs --write" % rel
    assert hc.docs_main(ROOT, ["--check"]) == 0


def test_the_docs_carry_each_rule_form_and_code_only_through_a_generated_section():
    structure = (ROOT / "docs" / "STRUCTURE.md").read_text(encoding="utf-8")
    hook02 = (ROOT / "docs" / "decisions" / "hook-02-shape-and-contract.md").read_text(encoding="utf-8")
    for rule in hc.RULES.values():
        if rule.decision == hc.D_HOOK02:
            assert hc._cell(rule.text) in hook02 and hc._cell(rule.text) not in hook02.split("<!-- generated:hook-02-rules end -->")[1]
    for form, _, _ in hc.FORMS_TABLE:
        assert "| `%s` |" % form in structure
    assert set(form for form, _, _ in hc.FORMS_TABLE) == set(hc.FORMS) - {"unknown"}
    outside = re.sub(r"<!-- generated:[\w-]+ begin.*?<!-- generated:[\w-]+ end -->", "", hook02 + structure, flags=re.S)
    assert not re.search(r"\bC\d+-C\d+\b", outside), "a doc restates a range of rules outside a generated section"


def test_the_generated_text_is_ascii_and_has_one_line_per_row():
    for make in (hc.forms_section, hc.rules_index_section, hc.codes_section, lambda: hc.rules_section(hc.D_HOOK02)):
        body = make()
        body.encode("ascii")
        assert all(line.startswith("|") and line.endswith("|") for line in body.splitlines()), body


@pytest.fixture
def copy_of_docs(tmp_path):
    for rel in hc.GENERATED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    return tmp_path


def test_docs_check_is_red_on_an_edited_section_and_write_repairs_it(copy_of_docs, capsys):
    path = copy_of_docs / "docs" / "decisions" / "hook-02-shape-and-contract.md"
    path.write_text(path.read_text(encoding="utf-8").replace("| C2 |", "| C2 (edited) |"), encoding="utf-8", newline="")
    assert hc.docs_main(copy_of_docs, ["--check"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL docs/decisions/hook-02-shape-and-contract.md: ") and "docs --write" in out
    assert "Rule: docs/decisions/" in out
    assert hc.docs_main(copy_of_docs, ["--write"]) == 0
    assert hc.docs_main(copy_of_docs, ["--check"]) == 0


def test_docs_check_is_red_when_a_marker_is_missing_and_on_a_bad_argument(copy_of_docs, capsys):
    path = copy_of_docs / "docs" / "STRUCTURE.md"
    path.write_text(path.read_text(encoding="utf-8").replace("<!-- generated:message-codes end -->", ""), encoding="utf-8", newline="")
    assert hc.docs_main(copy_of_docs, ["--check"]) == 1
    assert "the section `message-codes` has no begin and end markers" in capsys.readouterr().out
    assert hc.docs_main(copy_of_docs, []) == 2
    assert "not --write or --check" in capsys.readouterr().out


# --------------------------------------------------------------------------- the messages
def violation(rule, detail="", text="x = StealthY(this);", folder="fingerprint/x", file="dom/Foo.cpp", function="void Foo::Bar()"):
    return hc.Violation(rule, folder, file, function, text, hc._key(rule, folder, file, function, text), detail)


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_a_violation_of_each_rule_is_a_failure_with_where_what_fix_and_rule_whole(rule_id):
    long_text = "y = StealthLong(" + ", ".join("a%d" % i for i in range(120)) + ");"
    long_detail = "d" * 400
    got = hc.violation_failure(violation(rule_id, long_detail, long_text))
    text = str(got)
    assert isinstance(got, failure.Failure) and text.startswith("FAIL fingerprint/x/hooks.patch, dom/Foo.cpp, void Foo::Bar(): ")
    assert text.endswith("Rule: docs/decisions/%s.md" % hc.RULES[rule_id].decision)
    assert long_text in text, "the hook line is cut"
    assert rule_id in got.what and hc.RULES[rule_id].text in got.what
    assert " Fix: " in text and not hc.RULES[rule_id].fix.startswith(" ")


def test_c10_names_the_called_function_and_t3_names_the_test():
    c10 = str(hc.violation_failure(violation("C10", "nsContentUtils::DoThing")))
    assert "it calls `nsContentUtils::DoThing`" in c10 and "rename `nsContentUtils::DoThing` to Stealth<What>" in c10
    t3 = str(hc.violation_failure(violation("T3", "gtest:Nope.One")))
    assert "it names the test `gtest:Nope.One`" in t3 and "make a round run `gtest:Nope.One`" in t3


def test_c6_names_its_forms_and_says_how_many_lines_it_removed():
    c6 = hc.violation_failure(violation("C6", "3 Mozilla lines removed, 1 added", "-a\n-b\n-c\nd();"))
    for form in hc.REWRITE_FORMS:
        assert form in c6.what and form in c6.fix
    assert "3 Mozilla lines removed, 1 added" in c6.what and "`-a -b -c d();`" in c6.what


def test_a_violation_not_in_the_debt_says_the_rule_s_fix_not_the_debt_list():
    v = violation("C5", "", "x = StealthX(this) + 1;")
    (msg,) = hc.debt_problems([v], [], None)
    assert str(msg) == str(hc.violation_failure(v))
    assert "debt" not in msg.fix and "StealthX(this) + 1;" in msg.what
    for one in hc.debt_problems([v], [hc.entry_of(violation("C5", "", "other();"))], None):
        assert isinstance(one, failure.Failure) and str(one).startswith("FAIL ")


def test_the_debt_messages_are_failures_of_hook_03():
    v = violation("C2", "", "one();")
    stale = hc.debt_problems([], [hc.entry_of(v)], None)
    assert len(stale) == 1 and stale[0].where == "tools/hook-debt.json" and stale[0].rule == hc.D_HOOK03
    grown = hc.debt_problems([v], [hc.entry_of(v)], [])
    assert len(grown) == 1 and v.key in grown[0].what and grown[0].rule == hc.D_HOOK03


def test_hooks_list_messages_are_failures_that_name_the_hook(tmp_path):
    folder = "fingerprint/x"
    (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "SERIES").write_text(folder + "\n", encoding="utf-8")
    (tmp_path / folder / "hooks.patch").write_text("", encoding="utf-8")
    (tmp_path / folder / "HOOKS.json").write_text('[{"file": "dom/A.cpp", "function": "void A()", "kind": "add", "line": "StealthA(this);",'
                                                  ' "form": "notice", "test": "gtest:Nope.One", "exception": "", "pm": "x"}]\n', encoding="utf-8")
    found = hl.problems(tmp_path)
    assert found and all(isinstance(f, failure.Failure) for f in found)
    text = "\n".join(str(f) for f in found)
    assert "FAIL fingerprint/x/HOOKS.json, dom/A.cpp, void A(): the hook `StealthA(this);`" in text      # lists a hook hooks.patch has not
    assert "G35" in text and "Rule: docs/decisions/port-06-hooks-only-add.md" in text
    assert all(f.fix.strip() and f.what.strip() and f.where.strip() for f in found)
    why = hl.reference_problem(tmp_path, "gtest:Nope.One", where="fingerprint/x/HOOKS.json, dom/A.cpp, void A()")
    assert isinstance(why, failure.Failure) and "the test `gtest:Nope.One` does not resolve" in why.what and why.rule == hc.D_HOOK04
    assert hl.reference_problem(tmp_path, "whatever:x").what.endswith("is none of gtest:, node:, py:, xpcshell:, cargo:, wrapper:")


# --------------------------------------------------------------------------- nothing outside the repository, every code explained
@pytest.mark.parametrize("name", sorted(FILES))
def test_no_file_names_a_place_outside_the_repository(name):
    text = FILES[name]
    assert "coord/" not in text and "coord\\" not in text
    assert not re.search(r"(?<![\w-])[A-Za-z]:[\\/]", text), "a drive path"
    assert not re.search(r"(?i)\bfeder|camoufox|/home/|/Users/", text)


def test_every_g_code_a_file_names_is_explained_and_every_explained_code_is_named():
    named = set()
    for text in FILES.values():
        named |= set(re.findall(r"\bG\d+\b", text))
    assert named <= set(hc.EXPLAIN), sorted(named - set(hc.EXPLAIN))
    for code in hc.EXPLAIN:
        uses = sum(len(re.findall(r"\b%s\b" % code, text)) for text in list(FILES.values()) + [PREBUILD])
        assert uses >= 2, "%s is explained but no code names it" % code      # its own key counts once
    for text in (hc.forms_section(), "\n".join(str(hc.violation_failure(violation(r, "d"))) for r in hc.RULES)):
        assert set(re.findall(r"\bG\d+\b", text)) <= set(hc.EXPLAIN)
    for code, meaning in hc.EXPLAIN.items():
        assert re.fullmatch(r"G\d+", code) and meaning.strip().endswith(".")


def test_every_g_code_prebuild_prints_is_explained():
    import ast
    printed = set()
    for node in ast.walk(ast.parse(PREBUILD)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            printed |= set(re.findall(r"\bG\d+\b", node.value))
    assert "G19" in printed and printed <= set(hc.EXPLAIN), sorted(printed - set(hc.EXPLAIN))
