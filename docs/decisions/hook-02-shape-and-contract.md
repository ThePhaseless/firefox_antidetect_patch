# hook-02: shape and contract

**Rule.** Every hook outside the backport folders breaks none of the rules below; `tools/hook_contract.py` enforces them. The table is written from `RULES` in that file by `python tools/engine.py docs --write`; the other rules of the contract belong to the decisions named in [STRUCTURE.md](../STRUCTURE.md).

<!-- generated:hook-02-rules begin: written by `python tools/engine.py docs --write` from tools/hook_contract.py; do not edit -->
| Rule | Broken state | Fix |
|---|---|---|
| C1 | a hook is more than one line (a run of added lines where a line has no marker of its own, or one statement over several lines) | write the hook as one line with its own marker `STEALTH-HOOK(<folder>)`, or move the code into a function of ours in <folder>/src and call it from one line |
| C2 | the marker STEALTH-HOOK(<folder>) is missing on the hook line | add the marker `STEALTH-HOOK(<folder>)` on the same line, in the file's comment syntax, with nothing else in the comment |
| C3 | the marker comment carries more than the marker | delete the extra text from the comment: it holds `STEALTH-HOOK(<folder>)` and nothing else |
| C4 | a comment line is added to a Mozilla file besides the marker | delete the comment line; the explanation goes in our own file, in FEATURE.md or in HOOKS.json |
| C5 | the hook has logic (&&, \|\|, a ternary or arithmetic) | move the condition into the function of ours that the hook calls; the hook keeps the call and, in a guard, the return |
| C6 | Mozilla lines are removed or changed, and the change is none of the rewriting forms (wrap-expression, wrap-call, wrap-function, declared-value, shadow) | keep Mozilla's lines as Mozilla wrote them and add our one line beside them, or write the change as one of the forms (wrap-expression, wrap-call, wrap-function, declared-value, shadow: docs/STRUCTURE.md, hook forms); Mozilla code that must not run stays in the tree behind a guard at its only entry |
| C7 | a whole Mozilla file is deleted or replaced | restore the Mozilla file and make its code unreachable by a guard at its only entry, proven by a test |
| C8 | an include of ours is inside Mozilla's include block | move `#include "Stealth...h"` to a block of ours after Mozilla's block, with a blank line between them |
| C9 | the hook is inside a Mozilla list or on the last line of a block | move the hook one line up, so one untouched Mozilla line stays between our line and what Mozilla appends at each release; an anchor on the last statement of a block or of a JS module declares `anchor` and `why` in HOOKS.json (G30, G33) |
| C10 | the called function is not named Stealth<What> and is not an existing function (G41: tools/hook-names.json) | rename `<detail>` to Stealth<What> and define it in a file of ours in <folder>; tools/hook-names.json is closed: a new function takes a Stealth name and never joins the list |
| C16 | a hook passes a local of Mozilla's function as an argument outside an anchor (read from the lines the hunks show, or with --against from the whole function) | pass `this`, a parameter of the function or the wrapped expression instead of the local, or make the hook an anchor (`anchor` and `why` in HOOKS.json) |
| C17 | a Stealth-named function sits in the top-level namespace of someone else (JS::, js::, xpc::, a library's): ours live in `mozilla` or the global namespace | define the function in `mozilla` (or a namespace nested in it, or as a member of a class of ours) and call it as `mozilla::StealthFoo(` or `StealthFoo(`; a rewrite may replace Mozilla's `JS::Foo(` by `mozilla::StealthFoo(` (G29) |
<!-- generated:hook-02-rules end -->

Arguments of a hook are `this`, the function's parameters or the wrapped expression, never a local of Mozilla's function (C16). A private field with no public accessor is passed by reference or pointer and named in `HOOKS.json`, so a rename by Mozilla fails at compile time. Every hook has its entry in the folder's `HOOKS.json` (`tools/hooks_list.py`) and names a test with a negative control ([hook-04](hook-04-one-test-per-hook.md)). A value of ours never takes a number in a Mozilla numbered space ([hook-05](hook-05-no-values-in-mozilla-numbered-spaces.md)).

Mozilla's lines stay as Mozilla wrote them. Mozilla code that must not run stays in the tree, made unreachable by a guard at its only entry and proven by a test. The allowed forms are in the hook forms table of [STRUCTURE.md](../STRUCTURE.md); any other shape is a violation.

**Why.** Git merges without a conflict when an untouched line separates our change from Mozilla's. A removed or rewritten line conflicts at a port like an added one, and a copy of it in our file stops following Mozilla. Lists and block ends are where Mozilla adds lines at every release. The marker lets `check` and the tools find every hook.

**Files.** `tools/hook_contract.py`, `tools/hooks_list.py`, `tools/hook-names.json`, `<folder>/hooks.patch`, `<folder>/HOOKS.json`.

**Don't.**
- Write a hook that is not one of the forms, or that has no marker.
- Delete or replace a Mozilla file, or delete a Mozilla block, to stop it from running.
- Put a hook in a list or on the last line of a block; take a place one line above.
