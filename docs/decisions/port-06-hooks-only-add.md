# port-06: a hook only adds; a rewrite needs a reason that holds

**Rule.** A hunk adds lines in one of the fixed forms ([hook-02](hook-02-shape-and-contract.md)). A rewrite of Mozilla text is allowed only where no form can carry the value. It is one of the rewriting forms already defined (wrap-expression, wrap-call, wrap-function, declared-value, shadow), or a declared exception in `HOOKS.json` (`exception`, `pm: "approvato"`) with one of four `reason_kind`s:
- `expression`: a value inside an expression Mozilla builds;
- `declaration`: a signature or declaration, e.g. an IDL parameter;
- `macro`: a preprocessor condition or macro; an `#if` rewrite counts as macro;
- `skip`: Mozilla's statements must not run, because they read the host or have an effect a page sees, and no guard at a function start can skip them; every removed Mozilla line stays verbatim (whitespace aside) among the lines the hunk adds, inside our guard.

A rewrite fails even with an exception when it fits a form: Mozilla's expression survives intact inside our line, or the change adds `||`, `&&` or `?:` around it (it is a wrap-expression and is declared as one); or a parameter is added to a C++ signature or call that is not IDL, IPDL or WebIDL. A parameter we need deep in Mozilla's call chain is carried by our own state set by a guard at the entry (a thread-local, or a member of our side object), not threaded through Mozilla's signatures; a C++ parameter stays only as `declaration` with an exception that says why no side state can carry it.

**Enforced by.** `tools/hook_contract.py`, on every hooks.patch outside the backport folders:
- C12: a block of Mozilla lines removed that is none of the forms and has no declared exception with a `reason_kind` in the four (a deletion is a rewrite too);
- C13: a `skip` whose removed lines are not all kept verbatim among the added lines of its hunk (the message names the line);
- C14: the rewrite fits wrap-expression (the two cases above; a `skip` and a preprocessor line are never read as a wrap);
- C15: a parameter added to a C++ signature or call, unless `reason_kind` is `declaration` and the exception text names the side state it rules out.

C12 to C15 are never in `tools/hook-debt.json` ([hook-03](hook-03-budgets-and-debt-only-go-down.md)): `check` refuses a debt entry of these rules, and a declared exception does not leave them out. `tools/hooks_list.py` keeps `reason_kind` as a hand field and refuses a value outside the four or one without `exception`. Tests: `tools/tests/test_port06_rewrites.py`.

**Why.** Over nine releases a rewrite of Mozilla text conflicted 3.6 times more often than an added line. Of today's rewrites outside the forms, 14 can be add-only and 14 more are one parameter threaded through signatures; the rest are real exceptions that must say what kind.

**Files.** `tools/hook_contract.py` (`analyse_rewrites`, `rule_c12` to `rule_c15`, `rewrite_violations`, `REASON_KINDS`), `tools/hooks_list.py`, `tools/tests/test_port06_rewrites.py`, `<folder>/HOOKS.json`.

**Don't.**
- Rewrite a Mozilla line when a form carries the value: wrap it, rename the call, or add a line.
- Thread a parameter through Mozilla's signatures: set a thread-local or a member of our side object at the entry, and read it where the value is needed.
- Declare a `skip` and re-write the Mozilla line inside the guard: the skipped text stays as Mozilla wrote it.
- Put a C12 to C15 violation in the debt list, or pick a `reason_kind` for what its text does not say.
