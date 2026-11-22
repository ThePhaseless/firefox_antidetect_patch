# fingerprint/hardware/profile

Category: spoof
Prefs: zoom.stealth.hw_concurrency, zoom.stealth.max_touch_points
Test: wrapper `tests/test_fingerprint_surface.py::test_pin_hardware_concurrency_lands_in_navigator`, `tests/test_fingerprint_consistency.py` (worker and iframe `hardwareConcurrency` equal the window's); new wrapper e2e `tests/test_fingerprint_surface.py::test_pin_max_touch_points_lands_in_navigator` (to be written, green on firefox-68 first); core `invisible_core/tests/test_prefs.py` (the `max_touch_points` pref)

## What it does

`navigator.hardwareConcurrency` and `navigator.maxTouchPoints` answer the values the core declares.

- `hardwareConcurrency`: the pref `zoom.stealth.hw_concurrency` when it is above 0, with no engine gate (a build launched without invisible_core has the pref at -1 and keeps the host's count). `WorkerNavigator::HardwareConcurrency` has the same hook under `fingerprint/hardware/concurrency`.
- `maxTouchPoints`: the pref `zoom.stealth.max_touch_points` when the engine is on and the caller is not System, after `StealthAssertDeclarationsComplete()`. It used to be a literal 0 (right for the desktop GPU personas we ship, wrong in shape: a constant buried in C++ is not pinnable, not inspectable and not overridable through `extra_prefs`, so a touchscreen persona such as a Surface or a 2-in-1 would have needed a rebuild). It is now `HardwareProfile.max_touch_points`, at the same level as every other surface. The pref defaults to -1, so a build launched without invisible_core keeps the previous behaviour. 0 is a valid declared value, hence the out parameter of the hook function.

The logic is in `dom/base/StealthHardwareProfile.h` (header-only on purpose, like the other dom/base hooks of the series: its one includer is `Navigator.cpp`, so no line is added to `dom/base/moz.build`): `StealthHardwareConcurrency(uint64_t*)` and `StealthMaxTouchPoints(CallerType, uint32_t*)`. The header includes `StealthDeclarationGate.h` and `StaticPrefs_zoom.h`, which `Navigator.cpp` no longer includes itself.

## Hooks in Mozilla files

All in `dom/base/Navigator.cpp`:

- Registration: `#include "StealthHardwareProfile.h"` in a block of ours after Mozilla's includes.
- Guard, first statement of `Navigator::HardwareConcurrency`: `if (uint64_t stealthCores; StealthHardwareConcurrency(&stealthCores)) return stealthCores;`
- Anchor, in `Navigator::MaxTouchPoints` right after the Responsive Design Mode branch (`if (bc && bc->Top()->InRDMPane()) { return ...GetMaxTouchPointsOverride(); }`): `if (uint32_t stealthTouch; StealthMaxTouchPoints(aCallerType, &stealthTouch)) return stealthTouch;`. It is an anchor only by position: at the top of the function a page in an RDM pane of an engine-on browser would read the declared value instead of the devtools override, a different result in that one case.

Port note: the MaxTouchPoints anchor needs Mozilla's RDM branch to stay before the resist-fingerprinting check; if the RDM branch moves, the hook follows it.
