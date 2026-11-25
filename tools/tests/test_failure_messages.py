"""repo-04 (docs/decisions/repo-04-every-failure-says-where-what-fix-rule.md): every failure of the series tools is built by
`tools/failure.py fail()`, so it says where, what, how to fix and which rule.

The scan reads the syntax tree of each series tool (SCOPE) and lists, one line per site as `file:line`:

  1. every message that is not built through `fail()` (the patterns are in PATTERNS below);
  2. every cut of a message (a `[:N]`, `[-N:]`, `[a:b]` slice) in text a failure prints;
  3. every bare `assert`;
  4. every `fail()` call whose rule is not the id of a file in docs/decisions/ (or cannot be read as one), or has an empty field.

Not in SCOPE: tools/hook_tests_judge.py (the CI judge, handed over by another coordinator); tools/regen_checksums.py (a generator
the series tools call, not one of them); tools/tests (a test may assert).

What the scan cannot see: a message built far from where it is stored (a text kept in a variable, a dict or a constant and added
to a problem list by a name the scan does not know), a function that returns a message and is not named like one (see
RETURNS_MESSAGE), a cut made by `textwrap` or by `str.partition`, a list of problems built by a call to a helper in another file,
a message printed by a program that is not Python (workflows), and the wording itself: the scan proves the constructor is used,
not that `fix` is a good fix.

    python -m pytest tools/tests/test_failure_messages.py
"""
import ast
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import failure  # noqa: E402
from failure import FailureError, fail  # noqa: E402

REPO = TOOLS.parent
RULE = "repo-04-every-failure-says-where-what-fix-rule"
SCOPE = ("engine.py", "hook_contract.py", "hooks_list.py", "export_gate.py", "layout.py", "births.py", "prebuild.py",
         "backport_replay.py", "churn.py", "folders.py", "range_diff.py", "failure.py", "gtest_list.py")
# The one place that may hold the template of a failure line: failure.py's own renderer.
TEMPLATE = {("failure.py", "_render")}

PROBLEM_NAMES = {"found", "problems", "problem", "bad", "errors"}
# Problem lists that carry another name: (file, function, name). A list with such a name elsewhere is not a problem list.
OTHER_PROBLEM_LISTS = {
    ("births.py", "judge", "what"),
    ("births.py", "_entry_against_tree", "out"),
    ("churn.py", "differences", "out"),
    ("hook_contract.py", "churn_violations", "out"),
    ("backport_replay.py", "_replay", "notes"),
}
# Problem lists that share a name with a list that is not one: (file, function, name).
NOT_PROBLEM_LISTS = {("births.py", "_signature", "found")}
# Calls that return the text of a problem, per file. (churn.py's `say` is a progress callback, not one of them.)
MESSAGE_BUILDERS = {"folders.py": {"say"}, "range_diff.py": {"say"}}
RETURNS_MESSAGE = re.compile(r"say|rule_c\d+|_exception_of|quiet_anchor_problem|\w+_problem")   # functions whose return is a message

PATTERNS = {
    "append": "text added to a problem list (found, problems, problem, bad, errors, or a list in OTHER_PROBLEM_LISTS): .append(), "
              ".extend(), `+= [...]`, `= [...]`, a list comprehension",
    "fail-text": "a text that starts with FAIL, anywhere, or print('FAIL', ...)",
    "raise": "raise <Exception>(text) of any class, sys.exit(text), parser.error(text)",
    "builder": "Finding(FAIL, ...), violate(..., detail) with a detail that is not '', say(...): the templates that carry a problem",
    "return": "a text returned by say, rule_cNN, _exception_of, quiet_anchor_problem or a *_problem function",
}


# --------------------------------------------------------------------------------------------------- the scan
TEXT_METHODS = {"format", "join", "strip", "lstrip", "rstrip", "replace", "decode", "ljust", "rjust"}


def is_text(n) -> bool:
    """Is this expression a piece of text built here (a literal, an f-string, `%`, `+`, format, join, a cut of one)?"""
    if isinstance(n, ast.Constant):
        return isinstance(n.value, str) and bool(n.value)
    if isinstance(n, ast.JoinedStr):
        return True
    if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mod, ast.Add)):
        return is_text(n.left) or is_text(n.right)
    if isinstance(n, ast.IfExp):
        return is_text(n.body) or is_text(n.orelse)
    if isinstance(n, ast.BoolOp):
        return any(is_text(v) for v in n.values)
    if isinstance(n, ast.Subscript):
        return is_text(n.value)
    if isinstance(n, ast.Call):
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in TEXT_METHODS:
            return True
        return isinstance(f, ast.Name) and f.id == "str" and not any(is_fail_call(a) for a in n.args)
    return False


def call_name(n):
    if not isinstance(n, ast.Call):
        return None
    f = n.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


# fail() is the constructor; hook_contract.violation_failure and rule_failure return a Failure whose decision comes from the RULES table
# (a Failure refuses a decision with no file, and test_every_rule_of_the_table_names_a_decision_file reads the table), so a call of
# either is a message built by the constructor, like a call of fail().
FAILURE_BUILDERS = {"fail", "violation_failure", "rule_failure"}


def is_fail_call(n) -> bool:
    return isinstance(n, ast.Call) and call_name(n) in FAILURE_BUILDERS


def is_message(n, builders=frozenset()) -> bool:
    """A text, or a call of one of `builders`: and not a message that fail() builds."""
    if is_fail_call(n):
        return False
    if isinstance(n, ast.Call) and call_name(n) == "str" and n.args and is_fail_call(n.args[0]):
        return False
    return is_text(n) or (isinstance(n, ast.Call) and call_name(n) in builders) or (
        isinstance(n, ast.Tuple) and any(is_message(e, builders) for e in n.elts))


def leading_literal(n) -> str:
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr) and n.values and isinstance(n.values[0], ast.Constant):
        return str(n.values[0].value)
    if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mod, ast.Add)):
        return leading_literal(n.left)
    if isinstance(n, ast.IfExp):
        return leading_literal(n.body)
    return ""


def has_cut(n) -> list:
    """Every slice with a bound inside the expression."""
    return [s for s in ast.walk(n) if isinstance(s, ast.Subscript) and isinstance(s.slice, ast.Slice)
            and (s.slice.lower is not None or s.slice.upper is not None)]


class Scan:
    """What one file shows: `sites` (pattern, line) of messages not built by fail(), `cuts`, `asserts`, `rules` (fail() calls
    with a rule that is not a decision file or a field that is empty)."""

    def __init__(self, name: str, text: str):
        self.name = name
        self.builders = MESSAGE_BUILDERS.get(name, set())
        self.tree = ast.parse(text)
        self.sites, self.cuts, self.asserts, self.rules = set(), set(), set(), set()
        self.parent = {c: p for p in ast.walk(self.tree) for c in ast.iter_child_nodes(p)}
        self.constants = {}
        for stmt in self.tree.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        self.constants[target.id] = stmt.value.value
        self.messages = []          # (function node or None, expression that carries a message)
        self.run()

    def msg(self, e) -> bool:
        return is_message(e, self.builders)

    def function(self, n):
        while n in self.parent:
            n = self.parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n
        return None

    def skip(self, n) -> bool:
        f = self.function(n)
        return f is not None and (self.name, f.name) in TEMPLATE

    def site(self, pattern: str, n, carried=()):
        if self.skip(n):
            return
        self.sites.add((n.lineno, pattern))
        for expr in carried:
            self.messages.append((self.function(n), expr))

    def is_problem_list(self, recv, n) -> bool:
        name = ast.unparse(recv)
        f = self.function(n)
        if f is not None and (self.name, f.name, name) in NOT_PROBLEM_LISTS:
            return False
        return name in PROBLEM_NAMES or (f is not None and (self.name, f.name, name) in OTHER_PROBLEM_LISTS)

    def run(self):
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Assert):
                if not self.skip(n):
                    self.asserts.add(n.lineno)
            elif isinstance(n, ast.Call):
                self.call(n)
            elif isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add) and self.is_problem_list(n.target, n):
                self.list_value(n.value, n)
            elif isinstance(n, ast.Assign) and any(self.is_problem_list(t, n) for t in n.targets):
                self.list_value(n.value, n)
            elif isinstance(n, ast.Return) and n.value is not None:
                f = self.function(n)
                if f is not None and RETURNS_MESSAGE.fullmatch(f.name) and self.msg(n.value):
                    self.site("return", n, [n.value])
            if isinstance(n, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.IfExp)) and is_text(n):
                self.fail_text(n)
        self.cut_sites()

    def list_value(self, v, n):
        elts = v.elts if isinstance(v, (ast.List, ast.Tuple)) else [v.elt] if isinstance(v, ast.ListComp) else []
        for e in elts:
            if self.msg(e):
                self.site("append", e, [e])

    def fail_text(self, n):
        parent = self.parent.get(n)
        if isinstance(parent, (ast.BinOp, ast.IfExp, ast.JoinedStr, ast.Expr)) or isinstance(parent, ast.Compare):
            return                          # the outer expression decides; an Expr is a docstring
        if leading_literal(n).startswith("FAIL"):
            lit = leading_literal(n)
            if lit.startswith("FAIL ") or lit.startswith("FAIL:") or lit == "FAIL":
                if not (isinstance(parent, ast.Call) and call_name(parent) == "print") and lit == "FAIL":
                    return                  # the level marker (FAIL, WARN = ...), not a message
                self.site("fail-text", n, [n])

    def call(self, n):
        name = call_name(n)
        if name == "fail":
            self.fail_call(n)
        elif name in ("append", "extend") and isinstance(n.func, ast.Attribute) and n.args \
                and self.is_problem_list(n.func.value, n):
            arg = n.args[0]
            elts = arg.elts if (name == "extend" and isinstance(arg, (ast.List, ast.Tuple))) \
                else [arg.elt] if isinstance(arg, (ast.ListComp, ast.GeneratorExp)) else [arg]
            for e in elts:
                if self.msg(e):
                    self.site("append", e, [e])
        elif name == "print" and n.args and (isinstance(n.args[0], ast.Constant) and n.args[0].value == "FAIL"):
            self.site("fail-text", n, list(n.args))
        elif name == "Finding" and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "FAIL":
            self.site("builder", n, list(n.args[2:]))
        elif name == "violate":
            carried = [n.args[4]] if len(n.args) > 4 else [k.value for k in n.keywords if k.arg == "detail"]
            if any(not (isinstance(c, ast.Constant) and c.value == "") for c in carried):
                self.site("builder", n, carried)
        elif name in self.builders:
            self.site("builder", n, list(n.args))
        elif name in ("exit", "error") and n.args and self.msg(n.args[0]):
            self.site("raise", n, [n.args[0]])
        if isinstance(self.parent.get(n), ast.Raise) and self.parent[n].exc is n and n.args:
            if any(self.msg(a) for a in n.args) or any(self.msg(k.value) for k in n.keywords):
                self.site("raise", n, list(n.args))

    def fail_call(self, n):
        args = dict(zip(("where", "what", "fix", "rule"), n.args))
        args.update({k.arg: k.value for k in n.keywords if k.arg})
        rule = args.get("rule")
        if len(args) < 4 or any(isinstance(a, ast.Starred) for a in n.args):
            self.rules.add((n.lineno, "fail() is not called with where, what, fix and rule"))
            return
        for field in ("where", "what", "fix"):
            v = args[field]
            if isinstance(v, ast.Constant) and not (isinstance(v.value, str) and v.value.strip()):
                self.rules.add((n.lineno, "fail() has an empty `%s`" % field))
        lit = rule.value if isinstance(rule, ast.Constant) and isinstance(rule.value, str) else \
            self.constants.get(rule.id) if isinstance(rule, ast.Name) else None
        if lit is None:
            self.rules.add((n.lineno, "the rule of fail() is neither a text nor a constant of this file: its file cannot be checked"))
        elif not failure.rule_exists(lit):
            self.rules.add((n.lineno, "the rule %r names no file docs/decisions/%s.md" % (lit, lit)))

    def cut_sites(self):
        """A cut inside a message, or inside what a name used by a message was given in the same function."""
        for func, expr in self.messages:
            seen, todo = set(), [expr]
            while todo:
                e = todo.pop()
                for s in has_cut(e):
                    self.cuts.add((s.lineno, s.col_offset))
                if func is None:
                    continue
                for name in {x.id for x in ast.walk(e) if isinstance(x, ast.Name)} - seen:
                    seen.add(name)
                    for a in ast.walk(func):
                        if isinstance(a, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in a.targets):
                            todo.append(a.value)


def scan_source(name: str, text: str) -> Scan:
    return Scan(name, text)


def scan_tools(root: Path = TOOLS) -> dict:
    return {name: Scan(name, (root / name).read_text(encoding="utf-8")) for name in SCOPE}


def site_lines(results: dict, attr: str) -> list:
    """One line per site, `tools/<file>:<line>: <what>`; a line that two patterns see (a `found.append(say(...))`) is one site."""
    out = []
    for name, sc in results.items():
        by_line = {}
        for item in sorted(getattr(sc, attr)):
            line, what = (item, "bare assert") if attr == "asserts" else (item[0], "cut of a message" if attr == "cuts" else item[1])
            by_line.setdefault(line, [])
            if what not in by_line[line]:
                by_line[line].append(what)
        out += ["tools/%s:%d: %s" % (name, line, ", ".join(whats)) for line, whats in sorted(by_line.items())]
    return out


def per_file(lines: list) -> str:
    counts = Counter(l.split(":")[0] for l in lines)
    return ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items()))


def report(where: str, what: str, fix: str, lines: list):
    pytest.fail(str(fail(where, what, fix, RULE)) + "\n" + "\n".join(lines), pytrace=False)


# --------------------------------------------------------------------------------------------------- the rules
@pytest.fixture(scope="module")
def results():
    return scan_tools()


def test_every_message_is_built_by_fail(results):
    lines = site_lines(results, "sites")
    if lines:
        report("tools/ (the series tools)",
               "%d failure messages are not built through fail(): %s" % (len(lines), per_file(lines)),
               "replace each site below with fail(where, what, fix, rule) from tools/failure.py, where `fix` is the next command or the "
               "edit to make and `rule` the decision id; a site is a text added to a problem list, a FAIL print, a raise with text, "
               "or a message builder", lines)


def test_no_message_is_cut(results):
    lines = site_lines(results, "cuts")
    if lines:
        report("tools/ (the series tools)",
               "%d slice cuts of a text a failure prints: %s" % (len(lines), per_file(lines)),
               "print the whole text: delete the [:N] / [-N:] cut at each site below (a long text is a reason to split it, not to cut it)",
               lines)


def test_no_bare_assert(results):
    lines = site_lines(results, "asserts")
    if lines:
        report("tools/ (the series tools)",
               "%d bare asserts: a failed assert prints no where, no fix and no rule: %s" % (len(lines), per_file(lines)),
               "turn each site below into `if not <condition>: raise SystemExit(str(fail(...)))`, or return the fail(...) to the caller",
               lines)


def test_every_fail_call_names_a_decision(results):
    lines = site_lines(results, "rules")
    if lines:
        report("tools/ (the series tools)",
               "%d fail() calls with a rule that names no decision or with an empty field: %s" % (len(lines), per_file(lines)),
               "give each call below the id of a file in docs/decisions/ (without .md) and a non-empty where, what and fix",
               lines)


def test_the_scan_covers_the_files_it_names():
    missing = [n for n in SCOPE if not (TOOLS / n).is_file()]
    if missing:
        report("tools/tests/test_failure_messages.py SCOPE", "the scan names files that do not exist: %s" % ", ".join(missing),
               "delete the name from SCOPE, or restore the file", [])


# --------------------------------------------------------------------------------------------------- the scan on small sources
def lines_of(text: str, attr: str, name: str = "x.py") -> list:
    name = {"x.py": "folders.py"}.get(name, name)      # `say` is a builder in folders.py and range_diff.py
    sc = scan_source(name, text)
    return sorted(getattr(sc, attr))


@pytest.mark.parametrize("text, pattern", [
    ("def f():\n    found = []\n    found.append('bad thing')\n", "append"),
    ("def f(p):\n    problems = []\n    problems.append('%s is bad' % p)\n", "append"),
    ("def f(p):\n    found = []\n    found += ['%s is bad' % x for x in p]\n", "append"),
    ("def f(p):\n    found = []\n    found.extend(['%s is bad' % p])\n", "append"),
    ("def f(p):\n    found = ['%s is bad' % p]\n", "append"),
    ("def f(p):\n    found = []\n    found.append(say('a', 'b', 'c'))\n", "append"),
    ("def f(p):\n    print('FAIL %s' % p)\n", "fail-text"),
    ("def f(p):\n    print('FAIL', p)\n", "fail-text"),
    ("def f(p):\n    return 'FAIL ' + p\n", "fail-text"),
    ("def f(p):\n    raise SystemExit('refused: %s' % p)\n", "raise"),
    ("def f(p):\n    raise KeyError('no folder %s' % p)\n", "raise"),
    ("def f(p):\n    raise MyError(say('a', 'b', 'c'))\n", "raise"),
    ("def f(p):\n    raise SystemExit(str(p))\n", "raise"),
    ("import sys\ndef f(p):\n    sys.exit('refused')\n", "raise"),
    ("def f(ap, p):\n    ap.error('%s needs --x' % p)\n", "raise"),
    ("def f():\n    return Finding(FAIL, 1, 'w', 'what', 'fix')\n", "builder"),
    ("def f(rule):\n    def violate(rule, file, function, txt, detail='', hs=()):\n        pass\n    violate(rule, 'f', 'g', 't', 'detail')\n", "builder"),
    ("def say(a, b, c):\n    return '%s: %s' % (a, b)\n", "return"),
    ("def rule_c13(r):\n    return 'a rewrite %s' % r\n", "return"),
    ("def quiet_anchor_problem(v):\n    return 'it is not an object'\n", "return"),
])
def test_the_scan_sees_each_pattern(text, pattern):
    assert pattern in {p for _, p in lines_of(text, "sites")}, "the scan misses the pattern %r in %r" % (pattern, text)


@pytest.mark.parametrize("text", [
    "def f(p):\n    found = []\n    found.append(fail('w', 'what', 'fix', %r))\n" % RULE,
    "def f(p):\n    raise SystemExit(str(fail('w', 'what', 'fix', %r)))\n" % RULE,
    "def f(p):\n    raise SystemExit(fail('w', 'what', 'fix', %r))\n" % RULE,
    "def f(p):\n    print(fail('w', 'what', 'fix', %r))\n" % RULE,
    "def f(p):\n    out = []\n    out.append('not a problem list')\n    return out\n",
    "def f(p):\n    lines = ['info %s' % p]\n    print('ok: %s' % p)\n    return lines\n",
    "FAIL, WARN = 'FAIL', 'WARN'\n",
    "def f():\n    '''FAIL is the word the docstring uses'''\n",
    "def f(p):\n    raise SystemExit(2)\n",
    # violation_failure and rule_failure (hook_contract.py) take the decision from RULES: the scan accepts them
    "def f(v):\n    found = []\n    found.append(violation_failure(v))\n    return found\n",
    "def f(v):\n    problems = [violation_failure(x) for x in v]\n    return problems\n",
    "def f(v):\n    found = []\n    found.append(rule_failure('C12', 'w', 'what', 'fix'))\n    return found\n",
    "def f(v):\n    raise SystemExit(str(violation_failure(v)))\n",
    "def f(v):\n    print(violation_failure(v))\n",
])
def test_the_scan_leaves_what_fail_builds(text):
    assert lines_of(text, "sites") == []


@pytest.mark.parametrize("text", [
    "def f(v):\n    found = []\n    found.append('%s is bad' % v)\n    return found\n",
    "def f(v):\n    found = []\n    found.append('FAIL ' + str(violation_failure(v)))\n    return found\n",
    "def f(v):\n    return 'FAIL ' + str(rule_failure('C12', 'w', 'x', 'y'))\n",
])
def test_the_scan_still_sees_a_text_next_to_violation_failure(text):
    assert lines_of(text, "sites") != []


def test_every_rule_of_the_table_names_a_decision_file():
    import hook_contract
    missing = sorted(rid for rid, r in hook_contract.RULES.items() if not failure.rule_exists(r.decision))
    assert missing == [], str(fail("tools/hook_contract.py RULES", "the rules %s name no file in docs/decisions/" % ", ".join(missing),
                                   "give each rule the id of its decision file, without the .md", RULE))


def test_the_scan_sees_a_cut_in_a_message_and_in_what_it_uses():
    direct = "def f(p):\n    found = []\n    found.append('%s' % p[:10])\n"
    named = "def f(p):\n    text = p.strip()[:80]\n    found = []\n    found.append('bad %s' % text)\n"
    joined = "def f(p):\n    raise SystemExit('%s' % ', '.join(p[:3]))\n"
    unrelated = "def f(p):\n    key = p[:12]\n    found = []\n    found.append(fail('w', 'x', 'y', %r))\n    return key\n" % RULE
    assert len(lines_of(direct, "cuts")) == 1
    assert len(lines_of(named, "cuts")) == 1
    assert len(lines_of(joined, "cuts")) == 1
    assert lines_of(unrelated, "cuts") == []


def test_the_scan_sees_a_bare_assert():
    assert lines_of("def f(x):\n    assert x\n", "asserts") == [2]
    assert lines_of("def f(x):\n    if not x:\n        raise SystemExit(1)\n", "asserts") == []


def test_the_scan_checks_the_rule_of_each_fail_call():
    bad = "def f():\n    fail('w', 'x', 'y', 'no-such-decision')\n"
    good = "def f():\n    fail('w', 'x', 'y', %r)\n" % RULE
    constant = "R = %r\ndef f():\n    fail('w', 'x', 'y', R)\n" % RULE
    dynamic = "def f(r):\n    fail('w', 'x', 'y', r)\n"
    empty = "def f():\n    fail('', 'x', 'y', %r)\n" % RULE
    short = "def f():\n    fail('w', 'x')\n"
    assert len(lines_of(bad, "rules")) == 1
    assert lines_of(good, "rules") == [] and lines_of(constant, "rules") == []
    assert len(lines_of(dynamic, "rules")) == 1
    assert len(lines_of(empty, "rules")) == 1
    assert len(lines_of(short, "rules")) == 1


def test_the_template_of_failure_py_is_the_only_one_allowed():
    template = "def _render(w):\n    return 'FAIL %s' % w\n"
    elsewhere = "def other(w):\n    return 'FAIL %s' % w\n"
    assert lines_of(template, "sites", "failure.py") == []
    assert lines_of(elsewhere, "sites", "failure.py") != []


# --------------------------------------------------------------------------------------------------- fail()
def test_fail_prints_where_what_fix_and_rule_whole():
    long = "x" * 5000
    got = fail("tools/engine.py:12", "the folder is red", "run `python tools/engine.py check`", "hook-02-shape-and-contract")
    assert str(got) == ("FAIL tools/engine.py:12: the folder is red. Fix: run `python tools/engine.py check`. "
                        "Rule: docs/decisions/hook-02-shape-and-contract.md")
    assert long in str(fail(long, long, long, "hook-02-shape-and-contract"))
    assert str(fail(long, long, long, "hook-02-shape-and-contract")).count(long) == 3


def test_fail_is_immutable():
    got = fail("w", "x", "y", "hook-02-shape-and-contract")
    with pytest.raises(Exception):
        got.where = "other"
    assert got == fail("w", "x", "y", "hook-02-shape-and-contract")


@pytest.mark.parametrize("args", [
    ("", "what", "fix", "hook-02-shape-and-contract"),
    ("where", "  ", "fix", "hook-02-shape-and-contract"),
    ("where", "what", "", "hook-02-shape-and-contract"),
    ("where", "what", "fix", ""),
    (None, "what", "fix", "hook-02-shape-and-contract"),
    ("where", "what", ["fix"], "hook-02-shape-and-contract"),
])
def test_fail_refuses_an_empty_field(args):
    with pytest.raises(FailureError) as err:
        fail(*args)
    text = str(err.value)
    assert text.startswith("FAIL ") and "Fix: " in text and text.endswith("Rule: docs/decisions/%s.md" % RULE)
    assert (REPO / "docs" / "decisions" / (RULE + ".md")).is_file()


@pytest.mark.parametrize("rule", ["no-such-decision", "hook-02-shape-and-contract.md", "../README", "docs/decisions/hook-02", "HOOK-02"])
def test_fail_refuses_a_rule_with_no_decision_file(rule):
    with pytest.raises(FailureError) as err:
        fail("where", "what", "fix", rule)
    assert repr(rule) in str(err.value) and "Fix: pass the id of a file in docs/decisions/" in str(err.value)


def test_every_decision_file_can_be_named():
    for path in sorted((REPO / "docs" / "decisions").glob("*.md")):
        assert str(fail("w", "x", "y", path.stem)).endswith("docs/decisions/%s.md" % path.stem), path.name
