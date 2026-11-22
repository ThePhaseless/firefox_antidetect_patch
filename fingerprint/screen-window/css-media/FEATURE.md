# fingerprint/screen-window/css-media

Category: spoof
Prefs: zoom.stealth.pointer.all, zoom.stealth.pointer.primary, zoom.stealth.screen.height, zoom.stealth.screen.width
Test: wrapper:tests/test_css_media_declared_values_e2e.py::test_device_size_media_queries_are_the_declared_screen, wrapper:tests/test_css_media_declared_values_e2e.py::test_pointer_media_queries_are_declared_and_a_touch_override_still_wins

## What it does

The media features that a page reads with `matchMedia` and CSS (`device-width`, `device-height`, `device-aspect-ratio`, `pointer`, `any-pointer`, `hover`, `any-hover`) answer from values declared by the launcher instead of the monitor and the input devices of the host. Device size: `zoom.stealth.screen.width` and `.height` (CSS pixels, both > 0), the same two prefs `nsScreen::GetRect` reads, deliberately not gated on `StealthEngineActive()`. Pointer capabilities: `zoom.stealth.pointer.primary` and `.all` (a `PointerCapabilities` bitmask, < 0 means not declared), read only when the engine is active; the core derives them from the touch-point count so `any-pointer`, the Touch interfaces and `navigator.maxTouchPoints` cannot disagree. The host value (`LookAndFeel::GetInt`, which on Windows adds Coarse whenever the machine has a digitizer) is never read once a value is declared. The comments that explain why are in `layout/style/StealthMediaFeatures.h`.

## Hooks in Mozilla files

All in `layout/style/nsMediaFeatures.cpp`; own code in `layout/style/StealthMediaFeatures.h` (header only). Both functions are out-parameter functions: they return true and write the declared value, false when nothing is declared.

- registration: `#include "StealthMediaFeatures.h"` in our block after Mozilla's includes, before `using namespace mozilla;`.
- guard, `GetDeviceSize` (static): `if (nsSize stealth; StealthDeclaredDeviceSize(&stealth)) return stealth;` as the first statement, before the resistFingerprinting and RDM branches.
- anchor, `GetPointerCapabilities` (static): `if (PointerCapabilities stealth; StealthDeclaredPointerCapabilities(aID, &stealth)) return stealth;` right after Mozilla's `if (dom::BrowsingContext* bc = aDocument->GetBrowsingContext()) { if (bc->TouchEventsOverride() == dom::TouchEventsOverride::Enabled) { return PointerCapabilities::Coarse; } }` block. It is an anchor, not a guard in the head, because it must run after that return (the override is reachable: Juggler sets it from `has_touch`, and a declaration in front of it would beat it) and before the resistFingerprinting branch and the `LookAndFeel::GetInt` read of the host.
