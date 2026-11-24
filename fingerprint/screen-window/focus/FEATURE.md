# fingerprint/screen-window/focus

Category: spoof
Prefs: zoom.stealth.focus.ignore_os_deactivation
Test: wrapper:tests/test_focus_survives_os_deactivation_e2e.py::test_a_page_keeps_focus_when_another_session_takes_the_display

## What it does

With `zoom.stealth.focus.ignore_os_deactivation` (B149) the window keeps its
activation when the SYSTEM takes it away (another application, another
session's window on the same display) and loses it only to this session's own
windows, whose activation arrives as `WindowActivated` and lowers the window
it replaces there, with the same blur a page sees in any Firefox. Measured: a
second visible session on one display took the focus of the first 4 times in
4, and a window opened on the host's desktop 6 in 6, so a page read
`document.hasFocus()` false while nothing in its own session had moved.
`focusmanager.testmode` stops that too but also emulates every raise, and a
page can tell: `hasFocus()` turns false with no blur event (3 in 3).

## Hooks in Mozilla files

All in `xpfe/appshell/AppWindow.cpp`, one line each; the logic is in
`xpfe/appshell/StealthAppWindowFocus.h` (own file, header only).

- Registration: `#include "StealthAppWindowFocus.h"` in a block of ours after
  Mozilla's includes.
- Guard, first statement of `AppWindow::WindowDeactivated`:
  `if (StealthKeepsActivation()) return;`. True when the pref is set: Mozilla's
  deactivation body is skipped.
- Anchor, in `AppWindow::WindowActivated`, right after
  `RefPtr<nsFocusManager> fm = nsFocusManager::GetFocusManager()` and before
  `fm->WindowRaised(...)`: `StealthLowerActiveWindow(window, fm);`. With the
  pref set, the window that is active now (when it is another one) is lowered
  first and with its own action id: the order and the ids a page's process sees
  are those of an ordinary switch. Left to `WindowRaised`, the lowering travels
  with the raise's id, the page's process has already given up its active
  window when the deactivation arrives, and `document.hasFocus()` turns false
  with no blur event (measured, 4 in 4, when the session opened another page).
  It is an anchor and not a notice at the top of the function because the
  notice would run before Mozilla re-reads `mDocShell->GetWindow()` and the
  focus manager, and the lowering runs blur handlers that can close the window.

## Test

`wrapper:tests/test_focus_survives_os_deactivation_e2e.py::test_a_page_keeps_focus_when_another_session_takes_the_display`
(Linux, Xvfb, two sessions on one display; all three hooks). Without the guard
the first page's `hasFocus()` turns false when the second session takes the
display; without the anchor line it turns false with no blur event. Control:
pref false, `hasFocus()` is false after the second session takes the display.
