# fingerprint/screen-window/screen

Category: spoof
Prefs: zoom.stealth.screen.color_depth, zoom.stealth.screen.height, zoom.stealth.screen.taskbar_px, zoom.stealth.screen.width
Test: wrapper:tests/test_fingerprint_surface.py::test_pin_screen_width_lands_in_screen_object, wrapper:tests/test_fingerprint_surface.py::test_fpjs_screen_color_depth_realistic, wrapper:tests/test_fingerprint_surface.py::test_a_declared_screen_that_no_runner_has_is_what_the_page_reads, wrapper:tests/test_fingerprint_surface.py::test_the_inner_size_of_the_top_is_synced_with_the_engine_active_and_not_without

## What it does

`screen.pixelDepth`, `screen.width`/`height` and `screen.availWidth`/`availHeight` are the values the core declares (`zoom.stealth.screen.*`), not the host's; the available height is the declared height minus `zoom.stealth.screen.taskbar_px`. The synced inner size of a top-level browsing context (`BrowsingContext::InnerSizeSpoofedForRFP`) is also filled when the stealth engine is active, not only under resist-fingerprinting: the content of a stealth popup or of an out-of-process iframe reads the top level's inner size from it (B258). Every other reader of the field is gated on resist-fingerprinting; the reader of a stealth popup (`nsGlobalWindowOuter`, `IsInStealthPopup`) is gated on the engine.

The declared values come from `gfx::StealthDeclaredPixelDepth`, `gfx::StealthDeclaredScreenRect` and `gfx::StealthDeclaredAvailRect` (own files of another folder: `gfx/thebes/StealthDeclarationGate.h/.cpp`; they return nothing when the engine is off, so a bare binary is stock Firefox). The inner-size condition is in `layout/base/StealthInnerSizeSync.h`: `StealthRfpOrEngineActive(bool aRfp)` returns `aRfp || gfx::StealthEngineActive()`; Mozilla's early return fires when it is false, which is the old `!RFP && !Engine`.

## Hooks in Mozilla files

`dom/base/nsScreen.cpp`:
- include of `StealthDeclarationGate.h` in a block of ours after Mozilla's includes (registration).
- first statement of `nsScreen::PixelDepth`, `nsScreen::GetRect`, `nsScreen::GetAvailRect`: guard `if (auto declared = gfx::StealthDeclared...()) return ...;`. The declaration of the local in the condition is part of the one line (no `&&`, no ternary); the answer is ours, so Mozilla's code below stays untouched.

`layout/base/nsPresContext.cpp`:
- include of `StealthInnerSizeSync.h` in a block of ours after Mozilla's includes (registration).
- `nsPresContext::UpdateInnerSizeSpoofedForRFP`: the first operand of the early return, Mozilla's `ShouldResistFingerprinting(RFPTarget::WindowOuterSize)` call, is the argument of `StealthRfpOrEngineActive(...)` (wrap-expression; Mozilla's line is rewritten, a conflict at a version change is the signal).
