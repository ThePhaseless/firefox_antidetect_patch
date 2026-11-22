/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthJugglerCoalesce_h
#define mozilla_dom_StealthJugglerCoalesce_h

// Header-only on purpose: it is included by CoalescedMouseData.cpp alone, so it
// needs no line in dom/ipc/moz.build.

#include "mozilla/MouseEvents.h"

namespace mozilla {

/**
 * Stealthfox [B217]: the coalesced event acks the LAST id folded into it,
 * which is the one a caller waiting on "has my move landed" holds.
 * CoalescedMouseData::Coalesce calls it in the branch that has a coalesced
 * event (the first event of a run makes the coalesced event as a copy of
 * itself, id included).
 */
inline void StealthCoalesceJugglerEventId(WidgetMouseEvent& aCoalesced,
                                          const WidgetMouseEvent& aLatest) {
  aCoalesced.mJugglerEventId = aLatest.mJugglerEventId;
}

}  // namespace mozilla

#endif  // mozilla_dom_StealthJugglerCoalesce_h
