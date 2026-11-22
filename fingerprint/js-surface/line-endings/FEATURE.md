# fingerprint/js-surface/line-endings

Category: spoof
Prefs: none (no pref, no engine gate: every build behaves like Windows)
Test: wrapper `tests/test_native_line_endings_are_windows_e2e.py::test_a_native_blob_ends_its_lines_with_crlf` and `::test_a_selection_across_two_blocks_breaks_with_crlf` (new, written first and green on firefox-68; the stock Firefox of the same candidate is the control on Linux, on Windows both give CRLF and the test adapts to the OS)

## What it does

On the retail Windows Firefox the native line ending is CRLF: `new Blob(['\n'], {endings: 'native'}).size` is 2, and a selection across two blocks stringifies with `\r\n`. On Linux Firefox gives 1 and `\n`. The engine gives the Windows answers on every build ([B294]), toward Windows, with no pref and no engine gate, as before.

- `BlobSet::AppendUTF8String` converts `\n` to `\r\n` for `endings: 'native'` under `#if STEALTH_NATIVE_EOL_IS_CRLF`, where Mozilla's text has `#ifdef XP_WIN`. The macro is 1 in `dom/file/StealthNativeEOL.h`: on a Windows build it is the same code Mozilla compiles there (XP_WIN was defined), on any other build the block is compiled in. Mozilla's own `#endif` is back as in the tag.
- `DetermineLineBreak` (`nsPlainTextSerializer.cpp`), the platform/default branch: `AssignLiteral(STEALTH_NATIVE_ULINEBREAK)`, the macro being the literal `u"\r\n"` in `dom/serializers/StealthPlainTextLineBreak.h`, where Mozilla's text has `NS_ULINEBREAK` (`u"\015\012"` on Windows: the same literal). The other three branches (flags asking for CR, LF or CRLF) are untouched, and Mozilla's `// Platform/default` comment is back.

The callers of `DetermineLineBreak` beyond the selection's `toString()` were never traced (the series inventory says UNVERIFIED): the serializer also backs other plain-text output (copy as plain text). The effect is the one the hook has always had, not a new one.

G13 (a `DEFINES` in `moz.build`) does not apply: it would have to switch ON a Windows-only block, and `XP_WIN` protects more than this block.

## Hooks in Mozilla files

- `dom/file/BlobSet.cpp`: Registration `#include "StealthNativeEOL.h"` in a block of ours after Mozilla's includes; declared value, one Mozilla line rewritten: `#if STEALTH_NATIVE_EOL_IS_CRLF` in place of `#ifdef XP_WIN`.
- `dom/serializers/nsPlainTextSerializer.cpp`: Registration `#include "StealthPlainTextLineBreak.h"` in a block of ours after Mozilla's includes; declared value, one Mozilla line rewritten: `aLineBreak.AssignLiteral(STEALTH_NATIVE_ULINEBREAK);` in place of `aLineBreak.AssignLiteral(NS_ULINEBREAK);`.

Comments that stood in the Mozilla files, moved out verbatim (now in the two headers): "Native line endings are Windows' on every build: the browser this one stands for is a Windows Firefox, and a page reads the platform from new Blob(['\n'], {endings: 'native'}).size, 2 there and 1 on Linux [B294]." and "Platform/default, which is Windows' on every build: a page reads it from getSelection().toString() across two blocks, "\r\n" on a Windows Firefox and "\n" on Linux [B294]."

Port note: both hooks are rewrites of one Mozilla line, so a conflict at a port means Mozilla changed that very line (the `XP_WIN` conversion of `BlobSet`, or the default branch of `DetermineLineBreak`) and it must be looked at.
