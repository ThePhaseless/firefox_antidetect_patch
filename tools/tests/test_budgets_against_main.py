"""A budget is never higher than on main: the rule, each case shown failing on its input.

problems() checks the patches against the branch's own budgets, so a branch could raise a
budget in the same commit. budget_raise_problems compares with main's budgets (read from
origin/main, never from the branch).

    python -m pytest tools/tests
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

MAIN_HOOK = {"a/A.cpp": 4}
MAIN_REMOVED = {"a/A.cpp": 2}


def _found(hook, removed):
    return engine.budget_raise_problems(hook, removed, MAIN_HOOK, MAIN_REMOVED)


def test_raising_an_existing_hook_budget_fails():
    found = _found({"a/A.cpp": 5}, {"a/A.cpp": 2})
    assert len(found) == 1 and "a/A.cpp" in found[0] and "above main's 4" in found[0], found


def test_lowering_or_removing_is_fine():
    assert _found({"a/A.cpp": 3}, {"a/A.cpp": 1}) == []
    assert _found({}, {}) == []
    assert _found({"a/A.cpp": 4}, {"a/A.cpp": 2}) == []


def test_a_new_file_hook_of_5_is_fine_6_fails():
    assert _found({"a/A.cpp": 4, "b/B.cpp": 5}, {"a/A.cpp": 2}) == []
    found = _found({"a/A.cpp": 4, "b/B.cpp": 6}, {"a/A.cpp": 2})
    assert len(found) == 1 and "b/B.cpp" in found[0] and "at most 5" in found[0], found


def test_raising_an_existing_removed_budget_fails():
    found = _found({"a/A.cpp": 4}, {"a/A.cpp": 3})
    assert len(found) == 1 and "removed budget 3 is above main's 2" in found[0], found


def test_a_new_removed_entry_for_a_file_already_patched_on_main_fails():
    main_removed = {}
    found = engine.budget_raise_problems({"a/A.cpp": 4}, {"a/A.cpp": 1}, MAIN_HOOK, main_removed)
    assert len(found) == 1 and "above main's 0" in found[0], found


def test_a_brand_new_file_removes_at_most_5():
    ok = {"b/B.cpp": 5}
    assert _found({"a/A.cpp": 4, "b/B.cpp": 5}, {**ok, "a/A.cpp": 2}) == []
    found = _found({"a/A.cpp": 4, "b/B.cpp": 5}, {"b/B.cpp": 6, "a/A.cpp": 2})
    assert len(found) == 1 and "b/B.cpp" in found[0] and "at most 5" in found[0], found


def test_the_budgets_as_committed_are_not_above_main():
    main_hook, main_removed = engine.load_main_budgets()
    hook = json.loads(engine.BUDGET.read_text(encoding="utf-8"))
    removed = json.loads(engine.REMOVED_BUDGET.read_text(encoding="utf-8"))
    assert engine.budget_raise_problems(hook, removed, main_hook, main_removed) == []
