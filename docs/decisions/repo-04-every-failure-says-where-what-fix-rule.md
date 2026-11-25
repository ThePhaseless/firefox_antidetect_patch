# repo-04: every failure says where, what, how to fix, and which rule

**Rule.** Every check, judge and rule test reports a problem through one constructor, `fail(where, what, fix, rule)` in `tools/failure.py`, printed `FAIL <where>: <what>. Fix: <how>. Rule: docs/decisions/<id>.md`.
- `where` is a file, folder, hook or command; `what` is the state that is wrong; `fix` is the next command or the edit to make; `rule` is the id of an existing file in `docs/decisions/`. The constructor refuses an empty field and a rule with no file.
- No bare `assert` in a tool, no message without a fix, no text cut short (no `[:N]` on a text a failure prints), no fix that the rules forbid (a fix that adds a debt entry, a budget raise or a declared exception to silence the check is not a fix).
- A rule test reports its own failure the same way, and lists every site it found, one line per site as `file:line`.

**Enforced by.** `tools/tests/test_failure_messages.py` reads the syntax tree of every series tool (`engine.py`, `hook_contract.py`, `hooks_list.py`, `export_gate.py`, `layout.py`, `births.py`, `prebuild.py`, `backport_replay.py`, `churn.py`, `folders.py`, `range_diff.py`, `failure.py`) and fails on a message not built by `fail()`, a cut of a message, a bare `assert`, and a `fail()` call whose rule names no decision. `hook_tests_judge.py` belongs to the CI judge and is not in that scan.

**Why.** In the measurement of the tools, 567 messages: none named its decision, 71% gave no fix. Agents were fast where a stop printed the next command and slow where it printed only the symptom: they read the code to guess the rule, then guessed a fix, and the fix was sometimes the one the rules forbid.

**Files.** `tools/failure.py` (the constructor), `tools/tests/test_failure_messages.py` (the scan and the unit tests of `fail()`), every file of the scan.

**Don't.**
- Print a problem with `print("FAIL ...")`, `raise SystemExit("...")` or a text appended to a list: build it with `fail()`.
- Write a `fix` that says "see the docs" or "see the script": say the command or the edit.
- Cut a text to fit a line; print it whole.
- Add a file to the scan's exemptions to make the scan green.
