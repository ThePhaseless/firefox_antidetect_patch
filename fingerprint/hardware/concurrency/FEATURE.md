# fingerprint/hardware/concurrency

Category: spoof
Prefs: zoom.stealth.hw_concurrency
Test: wrapper `tests/test_hardware_concurrency_is_declared_e2e.py::test_main_worker_and_iframe_report_the_declared_core_count` (new, written first and green on firefox-68); existing and untouched: `tests/test_fingerprint_consistency.py::test_worker_hardwareConcurrency_matches_main` and `::test_iframe_hardwareConcurrency_matches_window`, `tests/test_fingerprint_surface.py` (`navigator.hardwareConcurrency` pin)

## What it does

`navigator.hardwareConcurrency` read inside a worker answers the core count the core declares in `zoom.stealth.hw_concurrency`, as the page's `Navigator` does (that hook is in `dom/base/Navigator.cpp`, folder `fingerprint/hardware/profile`): the page, its workers and its iframes agree, and none of them reads the host's count.

`WorkerNavigator::HardwareConcurrency` answers the pref, converted to `uint64_t`, when it is above 0, with no engine gate: a build launched without invisible_core has the pref at -1 and keeps the host's count. The host's count (`RuntimeService`) is consulted only when nothing is declared.

The logic is in `dom/workers/StealthHardwareConcurrency.h` (header-only on purpose: its one includer is `WorkerNavigator.cpp`, so no line is added to `dom/workers/moz.build`): `StealthWorkerHardwareConcurrency(uint64_t*)`, which answers false when the pref is not above 0 (Firefox keeps its own path) and otherwise fills its out parameter. The name differs from the main-thread `StealthHardwareConcurrency` of `dom/base/StealthHardwareProfile.h` on purpose: two inline functions of the same name and signature in two directories would be one definition rule risk for no gain. The header includes `mozilla/StaticPrefs_zoom.h`, which `WorkerNavigator.cpp` no longer includes itself.

## Hooks in Mozilla files

All in `dom/workers/WorkerNavigator.cpp`:

- Registration: `#include "StealthHardwareConcurrency.h"` in a block of ours after Mozilla's includes (the old `StaticPrefs_zoom.h` include, out of alphabetical order at the end of Mozilla's block, is gone).
- Guard, first statement of `WorkerNavigator::HardwareConcurrency`: `if (uint64_t stealth; StealthWorkerHardwareConcurrency(&stealth)) return stealth;`

Comment that stood above the old block, moved out of the Mozilla file verbatim:

> Stealth: return spoofed core count if pref is set
