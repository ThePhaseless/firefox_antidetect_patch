# fingerprint/js-surface/stack-frames

Category: spoof
Prefs: none read directly
Test: gtest `StealthStackFrames.JugglersFrameIsNotInTheStackAPageReads` (`dom/base/test/gtest/TestStealthStackFrames.cpp`: a script named like Juggler's calls a page function that reads `new Error().stack`; the page's frame is in the string, Juggler's is not; red without the hook, green on the base); gtest `StealthStackFrames.TheV8FormatKeepsTheNewlineOfTheLastShownFrameWhenJugglersFramesEndTheStack` (the V8 format of a stack that Juggler's frames end ends as the stack with the top level in a page file does, less its last frame); wrapper `tests/test_a_page_cannot_probe_the_juggler_e2e.py::test_no_stack_a_page_reads_names_the_juggler` (existing, untouched, not proof of the hook by itself); node `juggler/tests/not_a_chrome_package.test.mjs` ("the stack filter skips the prefix the build installs under": the literal of the header equals the path the build installs Juggler under); see REPORT.md for the negative control still to be settled (G6)

## What it does

Juggler's frames (`resource://gre/modules/juggler/...`) appear in no stack string a page can read (`Error.stack`, and every other stack string `BuildStackString` builds for content). A fingerprinting service can detect automation by looking for Juggler's frame sources in `Error.stack`; the filter is by the URL prefix of the frame's source, so it breaks silently if Juggler's resource path changes (`juggler/moz.build` is the owner of that path, and the node test above pins the literal to it).

The logic is in the existing header-only `js/src/vm/StealthStackFrames.h` (no line in `js/src/vm/moz.build`):

- `StealthIsJugglerFrameSource(JSAtom*)`: true when the source starts with the Juggler resource path; false for a null source. Does not GC, does not allocate.
- `StealthUnwrapVisibleFrame(cx, principals, stack, selfHosted, skippedAsync, droppedJuggler = nullptr)`: Mozilla's `js::UnwrapSavedFrame`, then, while the frame is Juggler's, the first subsumed frame of its parent; it gives back the first frame that is not Juggler's. The async flag is the one of the step that found it.
- `StealthFirstVisibleFrame(cx, principals, frame, selfHosted, skippedAsync)`: the next frame of the walk, the first frame from the parent of the frame being shown that the reader may see and that is not Juggler's (it takes the arguments of Mozilla's `js::GetFirstSubsumedFrame` call it replaces). It notes, in a thread-local flag, that it dropped a tail of Juggler's frames after the frame shown.
- `StealthIsLastFrame(bool noNextFrame)`: the V8 format marks the last frame by the absence of a next one and ends every other frame with a newline; it answers the loop's `!nextFrame` as true only when there is no next frame and no tail of Juggler's frames was dropped after this one, so the last frame shown keeps its newline when Juggler's frames end the stack.

## Hooks in Mozilla files

All in `js/src/vm/SavedStacks.cpp`:

- Registration: `#include "vm/StealthStackFrames.h"` in a block of ours after Mozilla's includes.
- Wrap of a call, in `js::BuildStackString`, the two places where the walk takes a frame to show: Mozilla's calls with the called name replaced and the arguments as they are. `UnwrapSavedFrame(cx, principals, stack, ...)` of the first frame becomes `StealthUnwrapVisibleFrame(cx, principals, stack, ...)`, and `js::GetFirstSubsumedFrame(cx, principals, parent, ...)` of the next frame becomes `StealthFirstVisibleFrame(cx, principals, parent, ...)`. Each gives back the first frame that is not Juggler's, so no local is passed and Mozilla's loop never meets a frame of Juggler's.
- Wrap of an expression, in the V8 case of the `switch (format)`: Mozilla's `!nextFrame`, the last argument of `FormatV8StackFrame`, is wrapped in `StealthIsLastFrame(!nextFrame)`.

Port note: the two renamed calls must stay where Mozilla's walk takes the first frame and the next frame, with the arguments Mozilla passes; the wrapped `!nextFrame` must stay the last-frame argument of the V8 format; if Mozilla changes how the walk advances, the async flag that the two functions give back must follow.

- Registration of the gtest: `UNIFIED_SOURCES += ["TestStealthStackFrames.cpp"]` in `dom/base/test/gtest/moz.build`, one line of ours after Mozilla's list.

The suite `StealthStackFrames` must be in the default `gtest_filter` of release.yml (`StealthStackFrames.*`).

## Our own files

- `js/src/vm/StealthStackFrames.h` (existing)
- `dom/base/test/gtest/TestStealthStackFrames.cpp` (new)
