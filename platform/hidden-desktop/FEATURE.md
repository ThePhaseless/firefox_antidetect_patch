# platform/hidden-desktop

Category: other
Prefs: none read directly
Test: dom/media/webrtc/tests/gtest/TestStealthWindowInputDesktop.cpp (StealthWindowInputDesktop.OnlyAWindowOfThisProcessOnAnotherDesktopIsOff; Windows only)

## What it does

Windows only, libwebrtc only. A window created on a Win32 desktop object other
than the input desktop passes the visibility check of
CroppingWindowCapturerWin::ShouldUseScreenCapturer
(IsWindowVisibleOnCurrentDesktop): it is visible, not iconic, not cloaked, and
the shell's virtual desktop manager has no opinion about it. Yet the screen
shows the input desktop only, so a crop of the screen can never contain it.
Worse, the screen capturers move the capture thread onto the input desktop,
after which the window capturer cannot read the window either: the capture
ends with no frame at all. PrintWindow with PW_RENDERFULLCONTENT reads such a
window in full from a thread on its own desktop (measured 2026-09-20), so the
window capturer is the only path that can deliver. The hook excludes the
window from the screen capturer, so it goes to the window capturer.

StealthIsWindowOnInputDesktop (StealthWindowInputDesktop.h) compares, by name
and case-insensitively, the desktop of the window's own thread with the input
desktop. Only a thread of this process can be asked which desktop it was
created on: a window of another process, a window without a thread, a thread
whose desktop cannot be read and an input desktop that cannot be opened or
named are all reported as on the input desktop. The handle GetThreadDesktop
returns is not closed (it is not ours). StealthIsOffInputDesktop is its
negation, the one the hook calls.

## Hooks in Mozilla files

- `third_party/libwebrtc/modules/desktop_capture/cropping_window_capturer_win.cc`: our include in a block of ours after Mozilla's (registration); in `CroppingWindowCapturerWin::ShouldUseScreenCapturer`, an anchor guard `if (StealthIsOffInputDesktop(selected)) return false;` right after the `IsWindowVisibleOnCurrentDesktop` check (it needs the local `selected` and the order of the Windows calls of today).
- `dom/media/webrtc/moz.build`: `TEST_DIRS += ["tests/gtest"]` (registration of the gtest below).
- `window_capture_utils.{h,cc}` of libwebrtc are as in the tag: the member `WindowCaptureHelperWin::IsWindowOnInputDesktop` that only forwarded to our function is gone.

## Our own files

- `third_party/libwebrtc/modules/desktop_capture/win/StealthWindowInputDesktop.h`
- `dom/media/webrtc/tests/gtest/moz.build`
- `dom/media/webrtc/tests/gtest/TestStealthWindowInputDesktop.cpp`
