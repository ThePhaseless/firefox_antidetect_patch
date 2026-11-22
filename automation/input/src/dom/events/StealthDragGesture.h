/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthDragGesture_h
#define mozilla_StealthDragGesture_h

// Header-only on purpose: it is included by EventStateManager.cpp alone, so it
// needs no line in dom/events/moz.build.

#include "mozilla/BasicEvents.h"
#include "mozilla/MouseEvents.h"

namespace mozilla {

/**
 * Stealthfox [B288]: a drag gesture continues only with moves from where its
 * press came from. In a visible session the system's real pointer sits over
 * the window, and its native moves reach this process during a press that
 * Juggler sent: one from far away crossed the threshold and started a NATIVE
 * drag out of a click on a link. That drag then ended on its own, the
 * driver's release went to a drag session that no longer existed, and the
 * click failed (measured on X11 with XTest moves during the press; seen on
 * Windows as "session is null" in dispatchDragEvent). The id is set on every
 * event from jugglerSendMouseEvent, carried across processes and coalescing,
 * and is 0 for native input. The move is still dispatched; it only does not
 * count for this gesture, and tracking goes on.
 */

// EventStateManager::BeginTrackingDragGesture, after the other gesture fields:
// whether the press that starts the gesture came from Juggler
// (nsIDOMWindowUtils.jugglerSendMouseEvent). aFromJuggler is the member
// EventStateManager::mGestureDownFromJuggler.
inline void StealthDragGestureBegin(bool& aFromJuggler,
                                    const WidgetMouseEvent& aPress) {
  aFromJuggler = aPress.mJugglerEventId != 0;
}

// EventStateManager::GenerateDragGesture, once a gesture is tracked: true for
// a mouse event whose Juggler origin differs from the one of the press. The
// caller returns without updating the gesture.
inline bool StealthSkipDragGesture(bool aFromJuggler,
                                   const WidgetInputEvent& aEvent) {
  if (const WidgetMouseEvent* mouseEvent = aEvent.AsMouseEvent()) {
    return (mouseEvent->mJugglerEventId != 0) != aFromJuggler;
  }
  return false;
}

}  // namespace mozilla

#endif  // mozilla_StealthDragGesture_h
