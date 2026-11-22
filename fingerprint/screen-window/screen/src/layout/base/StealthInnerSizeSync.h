/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef LAYOUT_BASE_STEALTHINNERSIZESYNC_H_
#define LAYOUT_BASE_STEALTHINNERSIZESYNC_H_

#include "StealthDeclarationGate.h"

namespace mozilla {

// Stealthfox [B258]: nsPresContext::UpdateInnerSizeSpoofedForRFP fills the
// synced inner size of a top-level browsing context when the window outer
// size is protected by resist-fingerprinting. With the stealth engine active
// the field is filled as well, so that the content of a popup or of an
// out-of-process iframe reads the top level's inner size. Every other reader
// of the field is gated on resist-fingerprinting; the reader of a stealth
// popup (nsGlobalWindowOuter, IsInStealthPopup) is gated on the engine.
//
// aRfp is Mozilla's own answer, evaluated first and once at the call site.
// Mozilla's early return fires when this is false, i.e. when neither is on.
inline bool StealthRfpOrEngineActive(bool aRfp) {
  return aRfp || gfx::StealthEngineActive();
}

}  // namespace mozilla

#endif  // LAYOUT_BASE_STEALTHINNERSIZESYNC_H_
