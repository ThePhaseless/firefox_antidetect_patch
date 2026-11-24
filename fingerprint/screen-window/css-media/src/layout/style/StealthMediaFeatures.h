/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The stealth declarations that nsMediaFeatures.cpp reads: the device size and
 * the pointer capabilities. Logic and comments live here; the Mozilla file only
 * carries STEALTH-HOOK(fingerprint/screen-window/css-media) calls.
 *
 * Each function returns true and writes the declared value when something is
 * declared; false means nothing is declared and Mozilla's code goes on. They
 * are called as `if (T stealth; f(&stealth)) return stealth;`. */

#ifndef LAYOUT_STYLE_STEALTHMEDIAFEATURES_H_
#define LAYOUT_STYLE_STEALTHMEDIAFEATURES_H_

#include <stdint.h>

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "mozilla/LookAndFeel.h"
#include "mozilla/ServoTypes.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "nsSize.h"

namespace mozilla {

/**
 * The device size declared by the launcher (zoom.stealth.screen.width and
 * zoom.stealth.screen.height), in app units: true and *aOut, or false when it
 * is not declared (either value <= 0). Called as the first statement of
 * GetDeviceSize, before Mozilla's resistFingerprinting and RDM branches.
 *
 * Deliberately NOT gated on gfx::StealthEngineActive() and it does not call
 * gfx::StealthAssertDeclarationsComplete(): that is how this block always
 * behaved, and nsScreen::GetRect (dom/base/nsScreen.cpp) reads the same two
 * prefs the same way. Changing either would change what a page sees.
 */
inline bool StealthDeclaredDeviceSize(nsSize* aOut) {
  // Stealth: spoof device size from prefs set by Python at launch
  const int32_t w = StaticPrefs::zoom_stealth_screen_width();
  const int32_t h = StaticPrefs::zoom_stealth_screen_height();
  if (w > 0 && h > 0) {
    *aOut = CSSPixel::ToAppUnits(CSSIntSize(w, h));
    return true;
  }
  return false;
}

/**
 * The pointer capabilities declared for aID, as a PointerCapabilities
 * bitmask: true and *aOut, or false when the engine is off or the pref for
 * this ID is < 0 (not declared): the caller then falls through to the compiled
 * default. Pointer capabilities are DECLARED, one value for the primary
 * pointer and one for the union of all of them.
 *
 * Called in GetPointerCapabilities right after Mozilla's
 * `TouchEventsOverride == Enabled` return (Juggler sets that override from
 * has_touch, so a declaration in front of it would beat the override) and
 * before the resistFingerprinting branch and the LookAndFeel::GetInt host read.
 *
 * This used to be a compiled `Fine | Hover` for both, with the comment
 * "always report desktop pointer, consistent with maxTouchPoints=0". The
 * intent was right and it stopped a real leak -
 * `WinUtils::GetAllPointerCapabilities` adds Coarse whenever
 * `SystemHasTouch()`, so a developer machine with a digitizer would have said
 * `any-pointer: coarse` under a persona claiming a desktop. But it was a
 * second source of truth for something the core already describes
 * (`hardware.max_touch_points`), and it could not be pinned: a persona for a
 * touch laptop was not expressible at all.
 *
 * The core derives both from the touch-point count, so `any-pointer`,
 * `dom.w3c_touch_events.enabled` and `navigator.maxTouchPoints` cannot
 * disagree - and they did. Measured 2026-08-09, our build reported the Touch
 * interfaces present (the host has touch) with maxTouchPoints 0 and
 * `any-pointer: coarse` false: a machine that supports touch events, has no
 * touch points, and has no coarse pointer. No such machine exists.
 *
 * The prefs are read ONLY when the engine is active, and the declaration set
 * is asserted complete only when a value was actually declared.
 */
inline bool StealthDeclaredPointerCapabilities(LookAndFeel::IntID aID,
                                               PointerCapabilities* aOut) {
  if (!gfx::StealthEngineActive()) {
    return false;
  }
  const int32_t declared =
      aID == LookAndFeel::IntID::PrimaryPointerCapabilities
          ? StaticPrefs::zoom_stealth_pointer_primary()
          : StaticPrefs::zoom_stealth_pointer_all();
  if (declared >= 0) {
    gfx::StealthAssertDeclarationsComplete();
    *aOut = static_cast<PointerCapabilities>(declared);
    return true;
  }
  return false;
}

}  // namespace mozilla

#endif  // LAYOUT_STYLE_STEALTHMEDIAFEATURES_H_
