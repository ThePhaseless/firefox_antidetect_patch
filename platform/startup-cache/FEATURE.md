# platform/startup-cache

Category: other
Prefs: none read directly
Test: gtest:StealthStartupCache.AWriteNeverLowersItsIOPriority

## What it does

StartupCache writes no longer take a lowered I/O priority (`nsAutoLowPriorityIO`).
The write holds `mTableLock` from its first entry to its last, and the main
thread takes the same lock in `GetBuffer()` for every module it loads, so a
starved writer is a starved main thread. On Windows the lowered priority is
`THREAD_MODE_BACKGROUND_BEGIN`, which lowers the thread's CPU priority as well
as its I/O, and the write compresses every entry with LZ4 HC. Upstream saw it
at shutdown (bug 2037923) and exempted only that write; the first regular write,
about 30 s after a launch, is the same inversion. Measured on 2026-10-28 with
eleven browsers at once on Windows: the parent's main thread stood in
`GetBuffer()` for 7-27 s with its CPU idle, behind a pool thread in
`WriteToDisk()`, in 10 runs of 11, and nothing it owed the pages or the
automation pipe went out meanwhile. With background mode refused from outside,
the same runs never waited more than 4.5 s and the writes took 0.7-2 s. 151 had
no lowered priority here. (Fix of the 157 priority inversion, commit
044fdc985f.)

## Hooks in Mozilla files

- `startupcache/StartupCache.cpp`: `#include "StealthStartupCache.h"` in a block
  of ours after Mozilla's includes (registration), and in the write lambda of
  `StartupCache::MaybeWriteOffMainThread` the condition
  `if (aUseLowPriorityIO)` is wrapped: `if (StealthWritesMayLowerIOPriority(aUseLowPriorityIO)) {`
  (wrap of expression; the parameter is captured by value, so a guard at the top
  cannot change it). The function is `aWanted && false`: the lambda body and
  Mozilla's `lowPriority.emplace()` stay in the tree and unreachable.
- `startupcache/moz.build`: `EXPORTS.mozilla.scache += ["StealthStartupCache.h"]`
  after the closing `]` of Mozilla's list.
- `startupcache/test/moz.build`: `UNIFIED_SOURCES += ["TestStealthStartupCache.cpp"]`
  after the closing `]` of Mozilla's list.

`startupcache/StartupCache.h` and `startupcache/test/TestStartupCache.cpp` are as
in the tag. Own files: `startupcache/StealthStartupCache.h` (header only,
namespace `mozilla::scache`, the constant and the function) and
`startupcache/test/TestStealthStartupCache.cpp`.

## Test

`gtest:StealthStartupCache.AWriteNeverLowersItsIOPriority`: the function is
false for both values of its argument. The value is a constant, so there is
nothing to flip for a negative control; the wiring in `StartupCache.cpp` is
proven by `HOOKS.json` and the marker rule. The suite `StealthStartupCache.*`
must be in the gtest filter of the candidate (`release.yml`, `release_plan.py`
`DEFAULT_GTEST_FILTER`, `test_release_path.py`): without it no round runs this test (G20, G42).
