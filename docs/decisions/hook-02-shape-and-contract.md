# hook-02: shape and contract

**Rule.** Every hook outside the backport folders follows ten points; `tools/hook_contract.py` enforces them as rules C1-C11, C16 (point 3) and C17 (point 7).
1. One line with no logic: the call and, in a guard, the `return`. No `&&`, `||`, ternary or arithmetic (C1, C5).
2. The marker `STEALTH-HOOK(<folder of the function>)` on the same line, in the file's comment syntax, and nothing else in the comment (C2, C3).
3. Arguments: `this`, the function's parameters, or the wrapped expression. A private field with no public accessor is passed by reference or pointer and named in `HOOKS.json`, so a rename by Mozilla fails at compile time. No locals, except in an anchor (C16: a name that the lines the hunks show of the function declare as a local, passed or used by a hook that is not an anchor; with `check --against <tag> --source <path>` the whole function is read from the base file, otherwise a local declared out of view is not seen).
4. No Mozilla line removed or changed, except the single line of the rewriting forms (C6).
5. A guard or notice is the first statement of the body. Never inside a Mozilla list, never the last line of a block: one untouched Mozilla line must stay between our line and what Mozilla appends at each release (C9).
6. No comment in a Mozilla file besides the marker (C4).
7. The called function is named `Stealth<What>` and defined in a file of ours in the same folder (C10). It lives in the global namespace (C files, Rust FFI) or in `mozilla`, in any namespace nested in it (`mozilla::StealthX`, `mozilla::net::StealthX`, `mozilla::stealth::StealthX`) or as a member of a class of ours; never in the top-level namespace of anyone else (`JS`, `js`, `xpc`, a library's or a module's). A rewrite may replace Mozilla's `JS::Foo(` by `mozilla::StealthFoo(` or `StealthFoo(` (G29: the qualifier changes only when the new last component is `Stealth*`, Mozilla's arguments stay). C17 reads the first component of a qualifier; an unqualified name is judged by where our own sources declare it, which `engine.py hook-locals` looks up in CI, because the namespace around the hook in Mozilla's file does not say.
8. Never a whole Mozilla file deleted or replaced (C7); never a value of ours in a Mozilla numbered space ([hook-05](hook-05-no-values-in-mozilla-numbered-spaces.md), C11).
9. Every hook has its entry in the folder's `HOOKS.json`.
10. Every hook names a test with a negative control ([hook-04](hook-04-one-test-per-hook.md)).

Mozilla's lines stay as Mozilla wrote them. Mozilla code that must not run stays in the tree, made unreachable by a guard at its only entry and proven by a test. The allowed forms (guard, notice, wrap-expression, wrap-function, wrap-call, declared-value, registration, member, shadow, anchor) are in [STRUCTURE.md](../STRUCTURE.md); any other shape is a violation.

**Why.** Git merges without a conflict when an untouched line separates our change from Mozilla's. A removed or rewritten line conflicts at a port like an added one, and a copy of it in our file stops following Mozilla. Lists and block ends are where Mozilla adds lines at every release. The marker lets `check` and the tools find every hook.

**Files.** `tools/hook_contract.py`, `tools/hooks_list.py`, `tools/hook-names.json`, `<folder>/hooks.patch`, `<folder>/HOOKS.json`.

**Don't.**
- Write a hook that is not one of the forms, or that has no marker.
- Delete or replace a Mozilla file, or delete a Mozilla block, to stop it from running.
- Put a hook in a list or on the last line of a block; take a place one line above.
