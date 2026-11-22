# fingerprint/js-surface/stack-frames

Category: spoof
Prefs: none read directly
Test: gtest `StealthStackFrames.JugglersFrameIsNotInTheStackAPageReads` (`dom/base/test/gtest/TestStealthStackFrames.cpp`: a script named like Juggler's calls a page function that reads `new Error().stack`; the page's frame is in the string, Juggler's is not; red without the hook, green on the base); wrapper `tests/test_a_page_cannot_probe_the_juggler_e2e.py::test_no_stack_a_page_reads_names_the_juggler` (existing, untouched, not proof of the hook by itself); node `juggler/tests/not_a_chrome_package.test.mjs` ("the stack filter skips the prefix the build installs under": the literal of the header equals the path the build installs Juggler under); see REPORT.md for the negative control still to be settled (G6)

## What it does

Juggler's frames (`resource://gre/modules/juggler/...`) appear in no stack string a page can read (`Error.stack`, and every other stack string `BuildStackString` builds for content). A fingerprinting service can detect automation by looking for Juggler's frame sources in `Error.stack`; the filter is by the URL prefix of the frame's source, so it breaks silently if Juggler's resource path changes (`juggler/moz.build` is the owner of that path, and the node test above pins the literal to it).

The logic is in the existing header-only `js/src/vm/StealthStackFrames.h` (no line in `js/src/vm/moz.build`):

- `StealthIsJugglerFrameSource(JSAtom*)`: true when the source starts with the Juggler resource path; false for a null source. Does not GC, does not allocate.
- `StealthSkipJugglerFrame(MutableHandle<SavedFrame*> frame, Handle<SavedFrame*> nextFrame, bool* skippedAsync, bool skippedNextAsync)`: when the frame's source is Juggler's, it moves the walk to the next frame (`frame = nextFrame`, `*skippedAsync = skippedNextAsync`) and answers true; otherwise it changes nothing and answers false.

## Hooks in Mozilla files

All in `js/src/vm/SavedStacks.cpp`:

- Registration: `#include "vm/StealthStackFrames.h"` in a block of ours after Mozilla's includes (it was inside Mozilla's alphabetical block).
- Anchor, in the `do/while` of `js::BuildStackString`, right after Mozilla's `nextFrame = js::GetFirstSubsumedFrame(cx, principals, parent, SavedFrameSelfHosted::Exclude, skippedNextAsync);` and before the `switch (format)`: `if (StealthSkipJugglerFrame(&frame, nextFrame, &skippedAsync, skippedNextAsync)) continue;`. It is an anchor because it needs the walk's locals `frame`, `nextFrame`, `skippedAsync`, `skippedNextAsync` and a `continue` of Mozilla's loop, which no guard or notice at the head of the function can reach; a wrap-expression on `GetFirstSubsumedFrame` / `UnwrapSavedFrame` would be two rewritten lines with a rooting wrapper and would change the `!nextFrame` last-frame test of the V8 format. The `continue` stays in Mozilla's loop, on the hook line. The three effects are the ones the old five-line block had, in the same order and at the same place (the frames of `RootedField` are passed to the handles `StealthSkipJugglerFrame` takes through `&frame` and `nextFrame`).

Port note: the hook must stay after the statement that computes `nextFrame` and before the `switch (format)` that prints `frame`; if Mozilla changes how the walk advances (`frame = nextFrame; skippedAsync = skippedNextAsync;` at the loop's end), the three effects of `StealthSkipJugglerFrame` must follow.

- Registration of the gtest: `UNIFIED_SOURCES += ["TestStealthStackFrames.cpp"]` in `dom/base/test/gtest/moz.build`, one line of ours after Mozilla's list.

The suite `StealthStackFrames` must be in the default `gtest_filter` of release.yml (`StealthStackFrames.*`).

## Our own files

- `js/src/vm/StealthStackFrames.h` (existing)
- `dom/base/test/gtest/TestStealthStackFrames.cpp` (new)
