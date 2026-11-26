"""repo-04 (docs/decisions/repo-04-every-failure-says-where-what-fix-rule.md): the one constructor of a failure.

    from failure import fail
    problem = fail("fingerprint/a/FOLDER.json", "relation 'x' is not product or defect", "write one of the two shapes",
                   "series-02-every-folder-states-its-relation-to-mozilla")
    print(problem)
    FAIL fingerprint/a/FOLDER.json: relation 'x' is not product or defect. Fix: write one of the two shapes. Rule: docs/decisions/series-02-every-folder-states-its-relation-to-mozilla.md

`where`, `what` and `fix` are non-empty text; `rule` is the id of a file in docs/decisions/ and the file has to exist (it is looked
up under the repository root when the failure is built, once per id). Nothing is cut: the four fields print whole. A field that
is empty, or a rule with no file, raises FailureError at construction, so a message that does not say where, what, how to fix it
and which rule is never printed.

tools/tests/test_failure_messages.py finds every message of the series tools that is not built here.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = "docs/decisions"
SELF_RULE = "repo-04-every-failure-says-where-what-fix-rule"
RULE_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+")


class FailureError(ValueError):
    """A failure that cannot be built: a field is empty or the rule names no decision file. Its text is itself a failure."""


def _render(where: str, what: str, fix: str, rule: str) -> str:
    """The only template of a failure line."""
    return "FAIL %s: %s. Fix: %s. Rule: %s/%s.md" % (where, what, fix, DECISIONS, rule)


@lru_cache(maxsize=None)
def rule_exists(rule: str) -> bool:
    """Is `rule` the id of a decision file under the repository root? (cached: one lookup per id)"""
    return bool(RULE_ID.fullmatch(rule)) and (ROOT / DECISIONS / (rule + ".md")).is_file()


class Failure(str):
    """One failure: a text that already is the whole line (`FAIL where: what. Fix: fix. Rule: path`), with its four fields kept.

    It is a `str` so that every consumer of a list of problems (a join, a regex, `in`, a JSON dump, a test that reads the line) takes it
    as the line it is and nothing adds a second `FAIL` in front: `str(problem)` is the problem. The fields are read-only."""

    __slots__ = ("where", "what", "fix", "rule")

    def __new__(cls, where: str, what: str, fix: str, rule: str):
        values = {"where": where, "what": what, "fix": fix, "rule": rule}
        for name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise FailureError(_render(
                    "tools/failure.py fail()", "the field `%s` is %r, and a failure needs a non-empty text there" % (name, value),
                    "pass where (a file, folder or command), what (the broken state), fix (the next step) and rule (a decision id)",
                    SELF_RULE))
        if not rule_exists(rule):
            raise FailureError(_render(
                "tools/failure.py fail()", "the rule %r names no file %s/%s.md" % (rule, DECISIONS, rule),
                "pass the id of a file in %s/, the decision that forbids the state, without the .md" % DECISIONS,
                SELF_RULE))
        self = super().__new__(cls, _render(where, what, fix, rule))
        for name, value in values.items():
            object.__setattr__(self, name, value)
        return self

    def __setattr__(self, name, value):
        raise FailureError(_render(
            "tools/failure.py Failure", "the field `%s` is set after the failure was built" % name,
            "build another failure with fail(): a Failure is read-only", SELF_RULE))

    def __getnewargs__(self):
        return (self.where, self.what, self.fix, self.rule)

    def __str__(self) -> str:
        return str.__str__(self)


def fail(where: str, what: str, fix: str, rule: str) -> Failure:
    """One failure: where it is, what is wrong, how to fix it, and the decision that says so."""
    return Failure(where, what, fix, rule)
