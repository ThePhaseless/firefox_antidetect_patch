/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthHardwareProfile_h
#define mozilla_dom_StealthHardwareProfile_h

// The hardware profile a page reads from navigator: hardwareConcurrency and
// maxTouchPoints, as the core declares them (prefs zoom.stealth.hw_concurrency
// and zoom.stealth.max_touch_points).
//
// Header-only on purpose, like the other dom/base hooks of the series: the one
// includer is Navigator.cpp, so no source file is registered in
// dom/base/moz.build. Do not include it from another translation unit.
//
// Each function answers false when the declaration does not apply: the caller
// then keeps Firefox's own path. Otherwise it fills its out parameter and
// answers true. The out parameter is a parameter because 0 is a valid declared
// value of maxTouchPoints.

#include <cstdint>

#include "StealthDeclarationGate.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "mozilla/dom/BindingDeclarations.h"

namespace mozilla::dom {

// Navigator::HardwareConcurrency: the declared core count when the pref is
// above 0. Not gated by the engine: a build launched without invisible_core
// has the pref at -1 and keeps the host's count.
// (WorkerNavigator::HardwareConcurrency has the same hook under
// fingerprint/hardware/concurrency.)
inline bool StealthHardwareConcurrency(uint64_t* aOut) {
  int32_t hwc = StaticPrefs::zoom_stealth_hw_concurrency();
  if (hwc > 0) {
    *aOut = uint64_t(hwc);
    return true;
  }
  return false;
}

// Navigator::MaxTouchPoints: the declared touch point count, for a page (never
// the System caller) when the engine is on. It was a literal 0, right for the
// desktop GPU personas we ship but not pinnable, inspectable or overridable
// through extra_prefs, so a touchscreen persona (a Surface, a 2-in-1) would
// have needed a rebuild. The pref defaults to -1, so a build launched without
// invisible_core keeps the previous behaviour. The hook sits after the
// Responsive Design Mode branch of Mozilla's function: in a Responsive Design
// pane the devtools override still wins.
inline bool StealthMaxTouchPoints(CallerType aCallerType, uint32_t* aOut) {
  if (aCallerType == CallerType::System || !gfx::StealthEngineActive()) {
    return false;
  }
  gfx::StealthAssertDeclarationsComplete();
  *aOut = uint32_t(StaticPrefs::zoom_stealth_max_touch_points());
  return true;
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthHardwareProfile_h
