"""A budget is never higher than on main: the rule, each case shown failing on its input.

problems() checks the patches against the branch's own budgets, so a branch could raise a
budget in the same commit. budget_raise_problems compares with main's budgets (read from
origin/main, never from the branch).

    python -m pytest tools/tests
"""
import inspect
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
    # as check judges them: main's budgets and the raises this branch declares
    main_raises = engine.load_main_raises()
    raises = json.loads(engine.RAISES.read_text(encoding="utf-8")) if engine.RAISES.is_file() else []
    assert engine.budget_raise_problems(hook, removed, main_hook, main_removed,
                                        engine.new_raise_rows(raises, main_raises)) == []


# The ceiling of a file against main is main's own value (5 lines for a file new to the series), nothing else lifts it:
# the one-off realignment file of the firefox-69 line is gone (repo-07: one fact, one place).
def test_no_one_off_budget_file_is_left_and_the_engine_has_no_door_for_one():
    assert not (engine.BUDGET.parent / "budget-realign-69.json").exists()
    assert not [p.name for p in engine.BUDGET.parent.glob("*realign*")]
    assert "realign" not in inspect.signature(engine.budget_raise_problems).parameters
    assert not any("realign" in name.lower() for name in dir(engine))
    # one budget file per kind of ceiling: the hook, the removed and the register of declared raises
    assert sorted(p.name for p in engine.BUDGET.parent.glob("*budget*.json")) == [
        "hook-budget-raises.json", "hook-budget.json", "removed-budget.json"]


def test_the_ceiling_of_every_file_against_main_is_main_s_own_value():
    # Every Mozilla file of main's budgets: its value passes, one line more fails (no row lifts it), for both ceilings;
    # a file new to the series has 5. This is the effective ceiling the realignment file used to lift, now equal to main's.
    main_hook, main_removed = engine.load_main_budgets()
    for path, n in sorted(main_hook.items()):
        assert engine.budget_raise_problems({path: n}, {}, main_hook, main_removed) == [], path
        assert len(engine.budget_raise_problems({path: n + 1}, {}, main_hook, main_removed)) == 1, path
        m = main_removed.get(path, 0)
        assert engine.budget_raise_problems({}, {path: m}, main_hook, main_removed) == [], path
        assert len(engine.budget_raise_problems({}, {path: m + 1}, main_hook, main_removed)) == 1, path
    assert engine.budget_raise_problems({"new/File.cpp": 5}, {"new/File.cpp": 5}, main_hook, main_removed) == []
    assert len(engine.budget_raise_problems({"new/File.cpp": 6}, {}, main_hook, main_removed)) == 1


# The register of declared raises: tools/hook-budget-raises.json, read from main, only grows.
RAISE = {"file": "a/A.cpp", "from": 4, "to": 6, "folder": "f/x", "reason": "a hook that is a wanted growth",
         "decided_by": "pm", "date": "2026-11-22", "test": "wrapper:tests/test_a.py::test_b"}


def _raised(hook, branch_rows, main_rows):
    return (engine.raises_list_problems(branch_rows, main_rows)
            + engine.budget_raise_problems(hook, MAIN_REMOVED, MAIN_HOOK, MAIN_REMOVED,
                                           engine.new_raise_rows(branch_rows, main_rows)))


def test_a_raise_with_the_row_the_branch_adds_is_fine():
    assert _raised({"a/A.cpp": 6}, [RAISE], []) == []


def test_a_raise_without_a_row_fails():
    found = _raised({"a/A.cpp": 6}, [], [])
    assert len(found) == 1 and "above main's 4" in found[0], found


def test_a_row_whose_from_or_to_do_not_match_fails():
    for row, hook in ((dict(RAISE, **{"from": 3}), 6), (dict(RAISE, to=7), 6), (RAISE, 5), (RAISE, 7)):
        found = _raised({"a/A.cpp": hook}, [row], [])
        assert any("raises from" in p and "main's budget is 4" in p for p in found), (row, hook, found)


def test_a_row_with_an_empty_or_missing_field_or_a_bad_value_fails():
    for field in ("file", "folder", "reason", "decided_by", "date", "test"):
        found = engine.raises_list_problems([dict(RAISE, **{field: " "})], [])
        assert any("empty field" in p for p in found), (field, found)
    missing = dict(RAISE)
    del missing["test"]
    assert any("exactly the fields" in p for p in engine.raises_list_problems([missing], []))
    assert any("YYYY-MM-DD" in p for p in engine.raises_list_problems([dict(RAISE, date="22/11")], []))
    for frm, to in ((6, 6), (6, 4), ("4", 6), (4, 6.0), (-1, 2)):
        found = engine.raises_list_problems([dict(RAISE, **{"from": frm, "to": to})], [])
        assert any("two whole numbers" in p for p in found), (frm, to, found)


def test_a_row_of_main_removed_fails():
    found = _raised({"a/A.cpp": 4}, [], [RAISE])
    assert len(found) == 1 and "gone or changed" in found[0], found


def test_a_row_of_main_with_another_enforcing_field_fails():
    # fails on the old code too (a changed row was "gone or changed"); here it must stay red
    for field, value in (("from", 3), ("to", 7), ("file", "b/B.cpp"), ("folder", "f/y"),
                         ("date", "2026-11-23"), ("test", "wrapper:tests/test_c.py::test_d")):
        found = engine.raises_list_problems([dict(RAISE, **{field: value})], [RAISE])
        assert any("gone or changed" in p for p in found), (field, found)


def test_a_row_of_main_with_other_free_text_is_green():
    # fails on the old code: the reworded row was "gone or changed" and, as a new row, "raises from"
    for field in engine.RAISE_TEXT_FIELDS:
        row = dict(RAISE, **{field: "the same decision, in English"})
        assert _raised({"a/A.cpp": 4}, [row], [RAISE]) == [], field
        assert engine.new_raise_rows([row], [RAISE]) == [], field
        # a lowered budget and a reworded row together stay green; a raise still needs its own new row
        found = _raised({"a/A.cpp": 6}, [row], [RAISE])
        assert len(found) == 1 and "above main's 4" in found[0], (field, found)


def test_a_row_main_already_has_opens_nothing_on_the_branch():
    # main's row was its own raise: once on main, it lifts nothing more
    found = _raised({"a/A.cpp": 6}, [RAISE], [RAISE])
    assert len(found) == 1 and "above main's 4" in found[0], found


def test_main_without_the_register_lets_no_row_open_the_door():
    found = _raised({"a/A.cpp": 6}, [RAISE], None)
    assert len(found) == 1 and "above main's 4" in found[0], found


def test_two_rows_for_one_file_a_row_for_a_file_main_does_not_patch_and_a_row_that_raises_nothing_fail():
    second = dict(RAISE, reason="again")
    assert any("two rows" in p for p in _raised({"a/A.cpp": 6}, [RAISE, second], []))
    assert any("main does not patch" in p for p in _raised({"a/A.cpp": 4, "b/B.cpp": 3}, [dict(RAISE, file="b/B.cpp", **{"from": 0, "to": 3})], []))
    assert any("raises from" in p for p in _raised({"a/A.cpp": 4}, [RAISE], []))


def test_today_s_uses_stay_green_with_the_register():
    rows = [RAISE]
    # budgets equal to or below main's, with or without a row of main
    assert _raised({"a/A.cpp": 4}, rows, rows) == [] and _raised({"a/A.cpp": 3}, [], []) == []


def test_the_register_as_committed_is_well_formed_and_only_grows_against_main():
    rows = json.loads(engine.RAISES.read_text(encoding="utf-8"))
    engine.load_main_budgets()
    assert isinstance(rows, list) and engine.raises_list_problems(rows, engine.load_main_raises()) == []


# The removed budget goes above main's the same way: a row of the register with `budget: "removed"`.
RAISE_REMOVED = dict(RAISE, **{"from": 2, "to": 3, "budget": "removed", "reason": "a one-line rewrite in an allowed form replaces a longer hook"})


def _removed_raised(removed, branch_rows, main_rows):
    return (engine.raises_list_problems(branch_rows, main_rows)
            + engine.budget_raise_problems({"a/A.cpp": 4}, removed, MAIN_HOOK, MAIN_REMOVED,
                                           engine.new_raise_rows(branch_rows, main_rows)))


def test_a_removed_raise_with_its_row_is_fine_and_without_it_fails():
    # fails on the old code: the row had a field it did not know, and the value was above main's
    assert _removed_raised({"a/A.cpp": 3}, [RAISE_REMOVED], []) == []
    found = _removed_raised({"a/A.cpp": 3}, [], [])
    assert len(found) == 1 and "removed budget 3 is above main's 2" in found[0], found


def test_a_removed_row_whose_from_or_to_do_not_match_fails():
    for row, value in ((dict(RAISE_REMOVED, **{"from": 1}), 3), (dict(RAISE_REMOVED, to=4), 3), (RAISE_REMOVED, 4), (RAISE_REMOVED, 2)):
        found = _removed_raised({"a/A.cpp": value}, [row], [])
        assert any("raises the removed budget" in p and "main's is 2" in p for p in found), (row, value, found)


def test_a_file_without_a_removed_budget_on_main_raises_from_zero():
    row = dict(RAISE_REMOVED, file="b/B.cpp", **{"from": 0, "to": 3})
    main_hook = {"a/A.cpp": 4, "b/B.cpp": 2}
    found = engine.budget_raise_problems({"b/B.cpp": 2}, {"b/B.cpp": 3}, main_hook, MAIN_REMOVED, [row])
    assert found == [], found
    found = engine.budget_raise_problems({"b/B.cpp": 2}, {"b/B.cpp": 3}, main_hook, MAIN_REMOVED, [])
    assert len(found) == 1 and "above main's 0" in found[0], found


def test_a_hook_row_and_a_removed_row_of_one_file_are_two_raises_and_two_removed_rows_are_not():
    assert engine.budget_raise_problems({"a/A.cpp": 6}, {"a/A.cpp": 3}, MAIN_HOOK, MAIN_REMOVED, [RAISE, RAISE_REMOVED]) == []
    again = dict(RAISE_REMOVED, reason="again")
    assert any("two rows" in p for p in engine.budget_raise_problems({"a/A.cpp": 4}, {"a/A.cpp": 3}, MAIN_HOOK, MAIN_REMOVED, [RAISE_REMOVED, again]))


def test_a_removed_row_does_not_lift_the_hook_budget_nor_the_other_way_round():
    found = engine.budget_raise_problems({"a/A.cpp": 6}, {"a/A.cpp": 3}, MAIN_HOOK, MAIN_REMOVED, [RAISE_REMOVED])
    assert any("hook budget 6 is above main's 4" in p for p in found), found
    found = engine.budget_raise_problems({"a/A.cpp": 6}, {"a/A.cpp": 3}, MAIN_HOOK, MAIN_REMOVED, [RAISE])
    assert any("removed budget 3 is above main's 2" in p for p in found), found


def test_a_row_with_another_budget_than_hook_or_removed_fails():
    found = engine.raises_list_problems([dict(RAISE, budget="lines")], [])
    assert any("the budget 'lines'" in p for p in found), found
    assert engine.raises_list_problems([dict(RAISE, budget="hook")], []) == []
