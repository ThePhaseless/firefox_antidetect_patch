# Structure

Where each kind of change goes. The engine is Firefox as a patch series on a Mozilla tag (`UPSTREAM.json`): one folder per feature, applied in the order of `SERIES`.

## The layers

| Layer | What it is | Where | Registered in |
|---|---|---|---|
| Our own files | `Stealth*` code and its tests, stored byte for byte | `<folder>/src/<tree path>` | Nothing: the folder that holds `<folder>/src/<path>` owns it; a new file is placed once with `export --own` |
| Hooks | One-line changes to Mozilla files, each with `STEALTH-HOOK(<folder>)` on the line | `<folder>/hooks.patch` | the `inventory` of the folder's `MANIFEST.json` (one record per Mozilla file that the folder holds lines of) and `layout.FEATURES` |
| Backports | Upstream code carried until the tag has it | `platform/backports/<name>/` (a Mozilla commit, or the upstream commits of a vendored crate that no feature of ours needs); vendored code under `third_party/rust/` in the folder that needs it | `BACKPORT.json` in the folder |

A folder holds `hooks.patch`, `src/`, `MANIFEST.json`, `FEATURE.md`, `HOOKS.json` and `FOLDER.json`; a folder with a `BACKPORT.json` has no `HOOKS.json` and no `FOLDER.json`. Rules: [backport-01](decisions/backport-01-upstream-code-as-is.md), [series-02](decisions/series-02-every-folder-states-its-relation-to-mozilla.md).

## Which folder

| The change is | Folder |
|---|---|
| What a page can observe | `fingerprint/<surface>/<name>` |
| What the automation protocol needs from Gecko | `automation/<name>` |
| Proxies, SOCKS, DNS over HTTPS | `network/<name>` |
| A service turned off at birth ([stillborn-01](decisions/stillborn-01-only-what-changes-the-installed-browser.md)) | `stillborn/<name>` |
| The build, branding, CI, repository tooling | `platform/<name>` |
| A Mozilla commit carried ahead | `platform/backports/<name>/` |
| A fix tied to one Firefox version, with its reason to expire | `port/<name>` |

The groups are the order the series is applied in (`layout.GROUP_ORDER`). A new Mozilla file we modify needs an inventory record and a `layout.FEATURES` entry; a new file of ours that no folder holds under `src/` yet is placed once, `export --own <path or dir/>=<folder>`, and the folder that holds it owns it from then on. `export` stops until both exist.

## Which rung

Take the first that gives the same result.

| Rung | What | Mozilla files touched |
|---|---|---|
| 1 | A pref Firefox already reads, a value declared by the core, a build option | none |
| 2 | Our own code | one registration line |
| 3 | A guard or a notice at the top of a function | one line |
| 4 | A wrap of a function or of an expression | one line rewritten |
| 5 | An anchor inside a function, only for a value Mozilla computes halfway | one line, with `anchor` and `why` in `HOOKS.json` |

Rules: [hook-01](decisions/hook-01-own-code-first.md), [hook-02](decisions/hook-02-shape-and-contract.md).

## Hook forms

The value of `form` in `HOOKS.json`. Any other shape is a contract violation. The table is written from `FORMS_TABLE` in `tools/hook_contract.py` by `python tools/engine.py docs --write`.

<!-- generated:hook-forms begin: written by `python tools/engine.py docs --write` from tools/hook_contract.py; do not edit -->
| Form | Where | Looks like |
|---|---|---|
| `guard` | First statement of a function | `if (StealthX(this, aArg, &rv)) return rv;`; with a value to return (G15) the guard returns it |
| `notice` | First statement of a function | `StealthX(this, aArg);` |
| `wrap-expression` | The line where the value is born | Mozilla's expression, unchanged, inside our call (the whole expression, or a sub-expression of the line, with our extra leading arguments such as `this, `): `return StealthX(<expression>);`; over several lines (G53) one line of ours opens the call with the marker on it, Mozilla's lines between stay unchanged, and the closing line is Mozilla's plus our `)` and the marker |
| `wrap-function` | The signature line | Mozilla's `Foo` becomes `Foo_Mozilla` (G1) or another suffix such as `FooAsDrawn`; our `Foo` calls it and treats the result, and the one-line declarations and the internal calls take the same new name (G2); or the called function is replaced and exactly one plain argument of ours is added (G29, G9) |
| `wrap-call` | The line of a call | The called identifier `Foo` becomes `StealthFoo`, same arguments (G29); or one argument of ours, a Stealth call, is added to a call of Mozilla's line (G9) |
| `declared-value` | The line that gives a default | The value on Mozilla's line is replaced: a literal in place of a literal, or one STEALTH_ macro in place of one literal or one macro of Mozilla's |
| `registration` | Includes, build files, declarative files | `#include "StealthX.h"` in a block of ours after Mozilla's; `VAR += ["StealthX.cpp"]` after the closing `]` of a `moz.build`; one line in `.ipdl`, `.webidl`, `components.conf`, `jar.mn`; a forward declaration `class X;` or a file-scope declaration of a function of ours (G40) |
| `member` | A Mozilla class | One declaration after an existing member, never the last in the block |
| `shadow` | Top of a function | `const auto GetX = StealthGetX;` (G21: our value under a Mozilla name) |
| `anchor` | Right after a named Mozilla statement, mid-function (last resort) | `StealthX(this, &locale);` or `if (StealthX(this)) return rv;`; as the last line of a block or of a JS module (G30, G33) it carries its `anchor` and `why` in HOOKS.json |
<!-- generated:hook-forms end -->

## Hook rules

Every rule of the contract is one entry of `RULES` in `tools/hook_contract.py`, with its broken state, its fix and the decision it belongs to; the decision's file holds it. This table says which decision holds which rules.

<!-- generated:hook-rules begin: written by `python tools/engine.py docs --write` from tools/hook_contract.py; do not edit -->
| Decision | Rules |
|---|---|
| [hook-02](decisions/hook-02-shape-and-contract.md) | C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C16, C17, C20 |
| [hook-05](decisions/hook-05-no-values-in-mozilla-numbered-spaces.md) | C11 |
| [port-06](decisions/port-06-hooks-only-add.md) | C12, C13, C14, C15 |
| [port-07](decisions/port-07-quiet-anchors.md) | C18 |
| [hook-04](decisions/hook-04-one-test-per-hook.md) | T1, T2, T3 |
<!-- generated:hook-rules end -->

## Message codes

A message of the hook tools may name a G code: a case the code accepts. Each one is explained here and nowhere else (`EXPLAIN` in `tools/hook_contract.py`).

<!-- generated:message-codes begin: written by `python tools/engine.py docs --write` from tools/hook_contract.py; do not edit -->
| Code | Meaning |
|---|---|
| G1 | A function signature or a macro of Mozilla's is renamed on one line, `Foo` to `Foo_Mozilla` or to another suffix (wrap-function). |
| G2 | The one-line declarations and the internal calls of a renamed `Foo` are rewritten to the same new name as part of the same wrap. |
| G9 | One plain argument of ours, a Stealth call, is added to a call on Mozilla's line (wrap-call, wrap-function). |
| G15 | A guard with a value: `if (StealthX(this, aArg, &rv)) return rv;`, the guard returns the value our function computed. |
| G19 | No two files of ours share a basename: among the C, C++, JavaScript and Rust files of ours (but lib.rs, mod.rs, main.rs and build.rs), two with the same name in any folders fail prebuild, as soon as one of them is in scope. |
| G20 | A test must also be run by a round: the candidate workflow's gtest filter, a node job, a python step or a cargo step runs it (rule T3). |
| G21 | A shadow: `const auto GetX = StealthGetX;` at the top of a function gives Mozilla's name our value. |
| G23 | An anchor on the last statement of a block, declared with its `anchor` and `why`, is not a C9. |
| G29 | A call wrap: the called identifier `Foo` of Mozilla's line becomes `StealthFoo` with the same arguments; the qualifier may change only when the new last component is Stealth-named. |
| G30 | An anchor may be the last line of a block; it carries its `anchor` and `why` in HOOKS.json (rule T2). |
| G33 | An anchor may be the last line of a JS module; it carries its `anchor` and `why` in HOOKS.json (rule T2). |
| G35 | A declared exception: a HOOKS.json entry with the hand fields `exception` (the reason) and `pm: "approvato"` is a rewritten line no form can express; its violations of C1..C11, T1, T2 and T3 are left out and counted. |
| G40 | A forward declaration `class X;` or a file-scope declaration of a function of ours is a registration. |
| G41 | tools/hook-names.json lists the functions that existed when rule C10 came; a hook may call them without the Stealth prefix, and a new function takes a Stealth name. |
| G50 | In a preprocessed pref file or a JSON file, where a trailing comment is impossible, a marker comment alone on the line before a directive is the marker of the directive: one hook. |
| G51 | Per Mozilla file, the lines the head removes or rewrites (the `-` lines of the diff against the tag) are not more than the base's, unless a HOOKS.json entry of the file carries `replaces` (one rewritten line standing for several hooks); prebuild check 8. |
| G53 | A wrap-expression over several lines: one line of ours opens the call (marker on it), Mozilla's lines between stay unchanged, the closing line is Mozilla's plus our `)` and the marker. |
<!-- generated:message-codes end -->

## HOOKS.json

One per folder without `BACKPORT.json`, beside `hooks.patch`, one entry per hook; a backport folder has one for the hooks of its files that are not upstream code (category `backport`), and none for the upstream files. A hook's entry is in the HOOKS.json of the folder whose `hooks.patch` holds it, and that is the folder its marker `STEALTH-HOOK(<folder>)` names: a line whose marker names another folder is rule C20 (the export writes each line into the `hooks.patch` of its marker's folder). `check` fails when it differs from what the series generates: a hook lost in a merge does not pass silently.

| Fields | Written by | Meaning |
|---|---|---|
| `file`, `function`, `kind`, `form`, `line`, `removed` | `export` or `hooks-list` | The Mozilla file, the host function (the function whose signature is nearest above the block: git's section header of the hunk, or in a C or C++ file a nearer signature inside the hunk), `add` / `rewrite` / `delete` / `file`, the form, the added line, the Mozilla line it replaces |
| `test` | Hand | The test that proves the hook (grammar below); a hook with none is debt T1 |
| `anchor`, `why` | Hand | Form `anchor` only: the Mozilla statement it follows, and why a guard or a wrap is not enough (debt T2) |
| `own_function`, `renamed`, `calls_mozilla` | Hand | Read by `prebuild`: our functions to link-check besides `Stealth*`, a renamed Mozilla body besides `*_Mozilla`, a direct call of a renamed body that is allowed |
| `quiet_anchor_why` | Hand | A hook in the churn band of `tools/churn.py`: `{kind: only-place, why}` or `{kind: deferred, quieter}`, why no quieter anchor serves (rule C18, [port-07](decisions/port-07-quiet-anchors.md)) |
| `exception`, `untestable`, `replaces` | Hand | A declared exception to the contract, a hook that cannot be tested, one rewritten line standing for several hooks; the first two count only together with the `pm` field |

A hook is identified by file, function, kind and normalized text. A hook whose text changes loses its hand fields and `check` asks for them again.

| `test` | Names | Checked by `check` |
|---|---|---|
| `gtest:<Suite>.<Name>` | A `TEST` or `TEST_F` under some folder's `src/` | It exists |
| `node:<path>[#<title>]` | A node test of the tree, with its title | The file exists, the title is in it |
| `py:<path>::<name>` | A python test of ours (`::invariant:<name>` and `::case:<name>` for a check that is not a function) | The file exists and defines the name |
| `wrapper:<path>::<test>` | A test of the wrapper | The format only |
| `cargo:<crate>::<test path>` | A rust test of a crate of ours | The format only |
| `xpcshell:<path>#<test>` | An xpcshell test | The file exists, the title is in it |

A test no round runs is debt T3. Rule: [hook-04](decisions/hook-04-one-test-per-hook.md).

## FOLDER.json

One per folder without `BACKPORT.json`, directly in the folder, written by hand, once. It says whether the change is ours for good or a defect of Mozilla's, so that a port knows which folders should die when Mozilla fixes the defect. Rule: [series-02](decisions/series-02-every-folder-states-its-relation-to-mozilla.md).

| Shape | Meaning |
|---|---|
| `{"relation": "product"}` | Ours for good: Mozilla would not make the change |
| `{"relation": "defect", "upstream": "not-filed"}` | A defect of Mozilla's that nobody has reported |
| `{"relation": "defect", "upstream": "https://bugzilla.mozilla.org/show_bug.cgi?id=<N>"}` | The same, with the bug Mozilla has |
| the defect shapes plus `"fixed_in": "FIREFOX_<N>_<M>_RELEASE"` | The release that ships Mozilla's fix: at or before `mozilla_tag` `check` is red, at or before the target of a port `port` stops |

No other key, no other value, no path and no other URL. A backport is derived from its `BACKPORT.json`, never written here. `export` neither creates nor edits the file.

## Budgets and debt

Rule: [hook-03](decisions/hook-03-budgets-and-debt-only-go-down.md).

| File | Counts | Moves by |
|---|---|---|
| `tools/hook-budget.json` | Our lines per Mozilla file and folder (key `<file>\|<folder>`) | `shrink-budget` lowers it; a raise above `origin/main` needs a row in `tools/hook-budget-raises.json` |
| `tools/removed-budget.json` | Mozilla lines removed or rewritten per file and folder (key `<file>\|<folder>`); a missing key counts 0 | `shrink-budget` |
| `tools/hook-debt.json` | Each place that breaks the contract today, keyed by rule, folder, file, function and a hash of the text (no line number) | `hook-debt` drops resolved entries and never adds one; `--summary` counts them |
| `tools/hook-names.json` | Existing function names a hook may call without the `Stealth` prefix | Fixed; a new function is named `Stealth<What>` |
| `tools/birth-ledger.json` | Every place the tree creates a network request, with its verdict ([port-03](decisions/port-03-births-ledger.md)) | Hand, with `tools/births.py` |

## tools

| File | What it is |
|---|---|
| `tools/engine.py` | The commands: `export`, `verify`, `check`, `port` and the rest |
| `tools/layout.py` | `GROUP_ORDER`; `FEATURES`: inventory feature name to folder; the owner of a file of ours, read from the `src/` trees (no table) |
| `<folder>/MANIFEST.json`, `inventory` | One record per Mozilla file the folder holds lines of (the folder is the one the record's feature maps to; there is no other copy and no `tools/inventory.json`, which `check` refuses): file, category, feature, prefs, anchor, notes (by hand; `check` refuses an empty anchor or notes, and a hookable that is not already-hook, movable or hard); added / removed / hunk counts of the folder's part of the file (written by `export` from the folder's `hooks.patch`, which also derives a record a new (file, folder) needs, with empty anchor and notes; `check` refuses a different value, and an `evidence` field: the lines are `hooks.patch` itself) |
| `tools/gtest-suites.json` | The gtest suites the `HOOKS.json` files name, sorted, each marked windows-only or linux-only where its tests are built on one platform; written by `gtest-list --write` |
| `tools/hook_contract.py`, `tools/hooks_list.py` | The contract and the `HOOKS.json` generator |
| `tools/folders.py`, `tools/range_diff.py` | The `FOLDER.json` check; the range-diff of a port |
| `tools/prebuild.py`, `tools/births.py` | Static checks before a build; the birth-point scan |
| `tools/tests/` | The tests of the series itself |

## Who writes what

| File | Written by |
|---|---|
| `<folder>/hooks.patch`, `<folder>/src/`, `<folder>/MANIFEST.json` (with the `sha256` of every file under `src/`) | `export` |
| `<folder>/MANIFEST.json`, `inventory`: `added`, `removed`, `hunks`, `inline_logic_lines` of each record | `export` (from `hooks.patch`) |
| `tools/hook-budget.json`, `tools/removed-budget.json`: the entry of a (file, folder) patched for the first time | `export`, at the counted value |
| `tools/gtest-suites.json` | `gtest-list --write`, and `export` |
| A folder that owns nothing any more | `export` removes it |
| `SERIES` | `export` |
| `UPSTREAM.json`: `exported_from`, `exported_tree` | `export` |
| `HOOKS.json`: machine fields | `export`, `hooks-list` |
| `.github/workflows/*.yml` at the root | `export`: copies of `platform/ci/src/.github/workflows/`, except `series.yml` and `noreply-identity.yml`; `check` requires them identical |
| `<folder>/FEATURE.md` | `export` creates it once from the inventory; then by hand |
| `HOOKS.json`: hand fields | By hand |
| `<folder>/FOLDER.json` | By hand (a folder without a `BACKPORT.json`); `export` never writes or edits it |
| `ports/range-diff.txt` | `range-diff --write`, at every port |
| `<folder>/BACKPORT.json` and the upstream diff beside it | By hand |
| `UPSTREAM.json`: `mozilla_tag`, `source_branch` | `port`: it writes both once its branch exists |
| `<folder>/MANIFEST.json`, `inventory`: feature, category, prefs, anchor, hookable, notes, verifier (`export` keeps them; a modified file with no record needs one written before the export) | By hand |
| `tools/layout.py`, `tools/hook-budget-raises.json`, `tools/hook-names.json`, `tools/birth-ledger.json` | By hand |
| `tools/hook-budget.json`, `tools/removed-budget.json` | By hand, downward; `shrink-budget` |
| `tools/hook-debt.json` | `hook-debt` only |
| `.github/workflows/series.yml`, `.github/workflows/noreply-identity.yml` | By hand |
| `AGENTS.md`, `docs/` | By hand |

## Every change

1. In the source repository, on the source branch: the change, its test, the commit.
2. Here: `export`. It first runs the node tests and the tree's python tests on the head's tree; then it writes the series into a scratch copy of the checkout, runs `engine.py check` and `tools/tests` (`-n auto`) on that copy, and only if all is green replaces the series of the checkout with it. A red leaves the checkout untouched. Two failures of `check` that only a later step can close (the empty text of a record the export derived, the churn rows of the hunks it moved) are printed as `TODO after export` and do not stop it; `check` itself still refuses them.
3. `verify`: it must say `identical`.
4. `hook-debt` drops the resolved debt; `shrink-budget` after logic moved; a (file, folder) new to the series gets its row in `tools/hook-budget.json` from `export` (at most 5 lines: more is a failure of `check`).
5. A folder `export` made anew has no `FOLDER.json`: write it (`product`, or `defect` with its `upstream`). Fill the hand fields of the touched `HOOKS.json` (`test`; `anchor` and `why` for an anchor) and the `Test:` line of `FEATURE.md`.
6. `check`, and `python -m pytest -q tools/tests`.
7. Commit here with the same title as the source commit.
