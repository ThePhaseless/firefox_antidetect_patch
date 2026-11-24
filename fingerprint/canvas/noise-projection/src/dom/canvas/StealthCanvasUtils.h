/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef DOM_CANVAS_STEALTHCANVASUTILS_H_
#define DOM_CANVAS_STEALTHCANVASUTILS_H_

// The canvas-noise entry points of namespace CanvasUtils (feature
// fingerprint/canvas/noise-projection), declared here so that CanvasUtils.h,
// a widely included header, stays identical to Mozilla's. Exported as
// mozilla/dom/StealthCanvasUtils.h. The definitions are in
// dom/canvas/StealthCanvasNoise.cpp, where their contract is written.

#include "mozilla/AlreadyAddRefed.h"
#include "mozilla/dom/CanvasRenderingContextHelper.h"
#include "mozilla/gfx/StealthCanvasProjection.h"

class nsICanvasRenderingContextInternal;
class nsIPrincipal;

namespace mozilla {

namespace gfx {
class SourceSurface;
}  // namespace gfx

namespace CanvasUtils {

// The canvas noise for a canvas owned by aCanvasPrincipal; Off() for a
// canvas of the browser itself.
gfx::StealthCanvasNoise StealthNoise(nsIPrincipal* aCanvasPrincipal);

// Whether a canvas of this context type goes through the canvas noise at all:
// WebGL and WebGPU only. A 2D canvas, on the page or offscreen, and a
// bitmaprenderer read back exactly as drawn, as on retail; a bitmap taken from
// a WebGL canvas was already projected when it was taken.
inline bool StealthProjectsContextType(dom::CanvasContextType aType) {
  return aType == dom::CanvasContextType::WebGL1 ||
         aType == dom::CanvasContextType::WebGL2 ||
         aType == dom::CanvasContextType::WebGPU;
}

// A snapshot of a WebGL or WebGPU canvas as a page reads it: a new surface
// with the canvas noise applied, or aSnapshot back when the seed is 0.
already_AddRefed<gfx::SourceSurface> StealthProjectSnapshot(
    gfx::SourceSurface* aSnapshot, bool aPremultiplied,
    nsIPrincipal* aCanvasPrincipal);

// The same for the snapshot of a WebGPU canvas context (toDataURL, toBlob):
// premultiplied, owned by the principal of aContext. A null snapshot stays
// null.
already_AddRefed<gfx::SourceSurface> StealthProjectWebGPUSnapshot(
    nsICanvasRenderingContextInternal* aContext,
    already_AddRefed<gfx::SourceSurface> aSnapshot);

// The snapshot a page reads of a canvas context (nsICanvasRenderingContextInternal::StealthGetSurfaceSnapshot, what
// createPattern() takes from a canvas or an OffscreenCanvas): the element's own GetSurfaceSnapshot, where the noise of a
// WebGL or WebGPU canvas is applied, never the context's raw one, which would read a WebGL canvas back for nothing. The
// element of the context is aCanvas (a canvas element's context) or aOffscreen (an OffscreenCanvas's); only a context that
// has neither (never one of those two paths) answers with its own snapshot, aContextOwn.
template <typename CanvasT, typename OffscreenT, typename ContextOwnT>
already_AddRefed<gfx::SourceSurface> StealthPageSnapshotOf(
    CanvasT* aCanvas, OffscreenT* aOffscreen, ContextOwnT&& aContextOwn) {
  if (aCanvas) {
    return aCanvas->GetSurfaceSnapshot();
  }
  if (aOffscreen) {
    return aOffscreen->GetSurfaceSnapshot();
  }
  return aContextOwn();
}

}  // namespace CanvasUtils
}  // namespace mozilla

#endif  // DOM_CANVAS_STEALTHCANVASUTILS_H_
