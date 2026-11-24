# automation/window-size

Category: juggler
Prefs: none read directly
Test: juggler/tests/explicit_size_flag_is_free.test.mjs (node, in the candidate's node step: the C++ and the JS side use the same bit, no CHROME_* flag of nsIWebBrowserChrome uses it); the wrapper's popup tests (tests/test_popup_pages.py)

## What it does

A popup that a page opens with window.open(url, '', 'width=500,height=400') must
report the size the page asked for. Juggler can only tell that popup from one that
gave no size if the chrome flags carry a bit for it. `JugglerPopupChromeFlags`
(toolkit/components/windowwatcher/JugglerWindowSize.cpp) returns the popup flags
of Mozilla and adds that bit when the features give a size. It has two forms: one
that starts from CHROME_MINIMAL_POPUP, and one that takes the popup flags the
caller already holds (the caller passes Mozilla's own operand, so a change of
Mozilla's popup flags is followed).

## Hooks in Mozilla files

- `toolkit/components/windowwatcher/moz.build` (registration, after the closing `]`): `UNIFIED_SOURCES += ["JugglerWindowSize.cpp"]`. Without it the link fails (`JugglerPopupChromeFlags` undefined), which is the red case.
- The call in `nsWindowWatcher::CalculateChromeFlagsForContent` (popup branch) and the include of `JugglerWindowSize.h` are in `toolkit/components/windowwatcher/nsWindowWatcher.cpp`, a file that fingerprint/screen-window/popup-position owns (one owner per Mozilla file); the call is `mozilla::JugglerPopupChromeFlags(aFeatures, nsIWebBrowserChrome::CHROME_MINIMAL_POPUP)`.
- The next line of the same moz.build, `StealthWindowPlacement.cpp`, belongs to fingerprint/screen-window/popup-position.

## The explicit-size flag

Juggler: the window.open features that opened this popup give a size
(width, height, innerWidth or innerHeight). Juggler then leaves the
window at that size instead of applying the context's default viewport.

The flag is ours: `kJugglerWindowExplicitSize` in JugglerWindowSize.h, read as
`JUGGLER_WINDOW_EXPLICIT_SIZE` in juggler/TargetRegistry.js, bit 1 of the chrome
flags, which nsIWebBrowserChrome leaves free. Until 2026-10-29 it was declared
in nsIWebBrowserChrome.idl as 1 << 25, one of the bits the Mozilla comment
"Two bits are free here." counted; Firefox 159 gives that bit to
CHROME_MEDIA_PIP. juggler/tests/explicit_size_flag_is_free.test.mjs checks that
both sides agree and that no CHROME_* flag uses the bit.
