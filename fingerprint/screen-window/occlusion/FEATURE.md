# fingerprint/screen-window/occlusion

Category: spoof
Prefs: zoom.stealth.widget.occlusion_tracking.enabled (declared in modules/libpref/init/StaticPrefList.yaml)
Test: wrapper:tests/test_window_occlusion_e2e.py::test_a_covered_window_stays_visible_unless_occlusion_tracking_is_enabled (Linux under Xvfb: a second window covers the first; pref false keeps `document.visibilityState` "visible"; control: pref true makes it "hidden"), wrapper:tests/test_fullscreen_without_wm_e2e.py::test_fullscreen_without_a_window_manager_is_the_declared_screen (the hook of fingerprint/screen-window/geometry that lives in this folder's file; the rectangle rule itself is gtest:StealthFullscreen.* in widget/tests/gtest/TestStealthFullscreen.cpp, geometry's)

## What it does

GTK/Linux only. With `zoom.stealth.widget.occlusion_tracking.enabled` false, as the core declares it, a window that is fully covered stays visible: the page does not see `hidden`, as on Windows where the same declaration turns occlusion tracking off. Measured on Xvfb: a second session's window made the first one's page `hidden` 4 times in 4 without it (B149).

`nsWindow::OnVisibilityNotifyEvent` still calls `NotifyOcclusionState` (with UNKNOWN when the pref is false): only the condition of Mozilla's ternary is wrapped.

The file also carries one hook of fingerprint/screen-window/geometry (the marker names `geometry`; the file's owner is this folder, G7): fullscreen on an X display with no window manager is decided by the widget itself, from the declared screen (`nsWindow::StealthMakeFullScreenWithoutWM`, widget/gtk/StealthFullscreenGtk.cpp), instead of Mozilla's refusal.

## Hooks in Mozilla files

Each is one line with the marker on the line.

- `widget/gtk/nsWindow.cpp`:
  - the include of `StealthOcclusion.h`, in a block of ours after Mozilla's includes (the `StaticPrefs_zoom.h` include left Mozilla's list: our header includes it);
  - wrap-expression in `nsWindow::OnVisibilityNotifyEvent`: the first line of Mozilla's ternary, `auto state = aState == GDK_VISIBILITY_FULLY_OBSCURED`, becomes `auto state = StealthOcclusionTracked(aState == GDK_VISIBILITY_FULLY_OBSCURED)`; the two following Mozilla lines (`? OcclusionState::OCCLUDED : OcclusionState::UNKNOWN;`) are untouched. Same boolean as the old `&&` and the pref read, with the same short circuit (the pref is read only when the window is obscured), and `NotifyOcclusionState(state)` is still called, which a guard that returned early would skip. The pref value still goes through our function (G12);
  - anchor of `geometry` in `nsWindow::MakeFullScreen`: `if (StealthMakeFullScreenWithoutWM(aFullScreen)) return NS_OK;`, the first statement inside Mozilla's own block `if (GdkIsX11Display() && !IsFullscreenSupported(mShell)) {`; Mozilla's `return NS_ERROR_NOT_AVAILABLE;` stays below it. The condition is Mozilla's (nothing of it is copied); our function runs when both tests hold, in the same order as before, and returns the same NS_OK; when it answers false Mozilla's return runs. (Before, the hook line repeated the two tests and Mozilla's block evaluated them again on the false path; `IsFullscreenSupported` is a read of the window manager hint list with no page-visible effect.) Why an anchor: a guard at the head would have to copy Mozilla's `no window manager` computation, and a wrap of `MakeFullScreen` would read the refusal from the return code, which the kiosk unfullscreen path also returns. For the port to 160: in 160 `IsFullscreenSupported()` becomes a member with a `if (!IsFullscreenSupported())` block that also covers a Wayland PiP window; the hook text is identical, and `StealthMakeFullScreenWithoutWM` must then take `GdkIsX11Display()` as its first test so that it stays X11-only (that line belongs to geometry's `StealthFullscreenGtk.cpp`).

## Our own files

- `widget/gtk/StealthOcclusion.h` (header-only): `StealthOcclusionTracked(bool aObscured)`: `aObscured && StaticPrefs::zoom_stealth_widget_occlusion_tracking_enabled()`.
- `widget/gtk/StealthFullscreenGtk.cpp` and the declaration in `widget/gtk/nsWindow.h` are geometry's.
