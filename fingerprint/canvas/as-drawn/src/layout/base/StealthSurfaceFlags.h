/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef StealthSurfaceFlags_h
#define StealthSurfaceFlags_h

#include <stdint.h>

#include "mozilla/RefPtr.h"
#include "mozilla/dom/HTMLCanvasElement.h"
#include "nsLayoutUtils.h"

// Our flag for nsLayoutUtils::SurfaceFromElement's aSurfaceFlags
// (fingerprint/canvas/as-drawn): the canvas as drawn, without the noise a
// page's readback gets. It is not in Mozilla's SFE_* enum because Mozilla
// appends its new flags there on the next free bit, and a flag of ours there
// would collide with one of Mozilla's in silence at a port (the merge sees two
// different lines). Bit 31 is far from Mozilla's (they end at bit 8 in 157 and
// 159); build/stealth_check_sources.py fails if an SFE_ flag takes it.
// STEALTH-FLAG-SPACE(layout/base/nsLayoutUtils.h, SFE_)
constexpr uint32_t kStealthSfeAsDrawn = 1u << 31;

// Who asks for it: nsImageRenderer::PrepareImage, because -moz-element SHOWS
// the element, like the screen, so a canvas is shown as drawn. It calls
// nsLayoutUtils::StealthSurfaceFromElementAsDrawn.

// Whether a caller of nsLayoutUtils::SurfaceFromElement asked for the canvas as
// drawn. The one place that reads the flag.
constexpr bool StealthWantsAsDrawn(uint32_t aSurfaceFlags) {
  return (aSurfaceFlags & kStealthSfeAsDrawn) != 0;
}

// nsLayoutUtils::SurfaceFromElement(aElement, kStealthSfeAsDrawn) for the
// browser's own readers: the overload is the one the static type of aElement
// picks (Element* or HTMLCanvasElement*).
template <class ElementT>
mozilla::SurfaceFromElementResult nsLayoutUtils::StealthSurfaceFromElementAsDrawn(
    ElementT* aElement) {
  return SurfaceFromElement(aElement, kStealthSfeAsDrawn);
}

// nsLayoutUtils::SurfaceFromElement's snapshot of a canvas: as drawn when the
// caller set kStealthSfeAsDrawn, else what Mozilla takes. Exactly one of the two
// is called, with the same arguments; the snapshot with the noise is never taken
// first.
inline already_AddRefed<mozilla::gfx::SourceSurface>
mozilla::dom::HTMLCanvasElement::StealthGetSurfaceSnapshot(
    uint32_t aSurfaceFlags, gfxAlphaType* aOutAlphaType,
    gfx::DrawTarget* aTarget) {
  return StealthWantsAsDrawn(aSurfaceFlags)
             ? GetSurfaceSnapshotAsDrawn(aOutAlphaType, aTarget)
             : GetSurfaceSnapshot(aOutAlphaType, aTarget);
}

#endif  // StealthSurfaceFlags_h
