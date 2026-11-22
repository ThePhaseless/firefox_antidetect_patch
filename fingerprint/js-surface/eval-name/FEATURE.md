# fingerprint/js-surface/eval-name

Category: spoof
Prefs: none read directly
Test: the wrapper's e2e tests/test_the_evaluated_code_has_no_debugger_name_e2e.py (`page.evaluate('new Error().stack')` has no `debugger eval`; a filename given by the caller passes untouched)

## What it does

Juggler's `Runtime.evaluate` runs the page's code through the debugger
(`Debugger.Frame.eval`, `Debugger.Object.executeInGlobal`). Without a filename of its
own, Mozilla names that code "debugger eval code" and gives it the introduction type
"debugger eval". A page reads the first through `Error.stack` (the filename of a
frame) and the second through the introduction data of a script, so the two strings
tell a driven browser from a user's one. The evaluated code gets the names of ordinary
eval code instead: "eval code" and "eval". A filename given by the caller still wins.
A grep of js/src/debugger finds no other 'debugger eval' string literal; the other hits
are comments.

## Hooks in Mozilla files

All in `js/src/debugger/Frame.cpp`, function `EvaluateInEnv`:

- (declared value) the second line of `const char* filename = ...` is Mozilla's conditional expression with our literal in the default branch: `evalOptions.filename() ? evalOptions.filename() : "eval code";` (Mozilla's literal was "debugger eval code").
- (declared value) `.setIntroductionType("eval")` in the same CompileOptions builder chain (Mozilla's literal was "debugger eval"); the multi-line comment that follows in Mozilla's chain stays.

Two lines of Mozilla's stay rewritten (a literal cannot be wrapped): a change of Mozilla's on either is the conflict signal at the next port. The marker sits on each of the two lines.

Why: Juggler's `Runtime.evaluate` runs the page's code through the debugger; without a filename of its own Mozilla names that code "debugger eval code" and gives it the introduction type "debugger eval". A page reads both through `Error.stack` and the introduction data of a script, so they tell a driven browser from a user's one. A filename given by the caller still wins. (This explanation used to be a three-line comment above the filename in Mozilla's file; it lives here now.)

## Our own files

None.
