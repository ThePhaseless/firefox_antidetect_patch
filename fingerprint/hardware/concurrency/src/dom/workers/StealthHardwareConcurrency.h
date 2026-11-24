/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthHardwareConcurrency_h
#define mozilla_dom_StealthHardwareConcurrency_h

// The core count a worker reads from navigator.hardwareConcurrency, as the core
// declares it (pref zoom.stealth.hw_concurrency). The main thread answers the
// same pref through fingerprint/hardware/profile, so a page, its workers and
// its iframes agree.
//
// Header-only on purpose: its one includer is WorkerNavigator.cpp, so no source
// file is registered in dom/workers/moz.build. Do not include it from another
// translation unit.

#include <cstdint>

#include "mozilla/StaticPrefs_zoom.h"

namespace mozilla::dom {

// WorkerNavigator::HardwareConcurrency: the declared core count when the pref
// is above 0, answered before RuntimeService (the host's core count) is
// consulted. Not gated by the engine: a build launched without invisible_core
// has the pref at -1 and keeps the host's count. The name differs from the
// main-thread function of fingerprint/hardware/profile on purpose: the two are
// separate inline functions of separate directories.
inline bool StealthWorkerHardwareConcurrency(uint64_t* aOut) {
  int32_t hwc = StaticPrefs::zoom_stealth_hw_concurrency();
  if (hwc > 0) {
    *aOut = uint64_t(hwc);
    return true;
  }
  return false;
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthHardwareConcurrency_h
