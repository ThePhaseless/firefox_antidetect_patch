/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_CubebUtils_StealthSampleRate_h
#define mozilla_CubebUtils_StealthSampleRate_h

// The sample rate a page reads from AudioContext.sampleRate, as the core
// declares it (pref zoom.stealth.audio.sample_rate, set by the launcher).
//
// Header-only on purpose: its one includer is CubebUtils.cpp, so no source file
// is registered in dom/media/moz.build. Do not include it from another
// translation unit.

#include <cstdint>

#include "mozilla/StaticPrefs_zoom.h"

namespace mozilla::CubebUtils {

// PreferredSampleRate: the declared rate when the pref is above 0, answered
// before the fingerprint-resistance rate and before the cubeb device is read.
// Not gated by the engine: a build launched without invisible_core has the pref
// at -1 and keeps the device's rate. The hook sits after Mozilla's forced rate
// (the test-only pref media.cubeb.force_sample_rate), which keeps winning.
inline bool StealthDeclaredSampleRate(uint32_t* aOut) {
  int32_t rate = StaticPrefs::zoom_stealth_audio_sample_rate();
  if (rate > 0) {
    *aOut = uint32_t(rate);
    return true;
  }
  return false;
}

}  // namespace mozilla::CubebUtils

#endif  // mozilla_CubebUtils_StealthSampleRate_h
