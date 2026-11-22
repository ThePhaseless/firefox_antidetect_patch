/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// HTMLCanvasElement::GetSurfaceSnapshot (feature
// fingerprint/canvas/noise-projection): the canvas as a PAGE reads it, with the
// canvas noise (gfx/2d/StealthCanvasProjection.h) applied to a WebGL or WebGPU
// canvas. A 2D or bitmaprenderer canvas, and a canvas whose noise is off, come
// back exactly as drawn (GetSurfaceSnapshotAsDrawn).
//
// Every way a page turns this canvas into bytes or into the source of another
// drawing comes through it (or through GetSurfaceSnapshotAsync, declared after
// it in HTMLCanvasElement.h, which a context may answer without calling it), so
// a reader added in a future Firefox reads the same image as the others without
// being taught to: Mozilla's GetSurfaceSnapshot keeps its body under the name
// GetSurfaceSnapshotAsDrawn (the hook is on its signature) and the name
// GetSurfaceSnapshot is defined here.
//
// HTMLCanvasElement::GetSurfaceSnapshotAsDrawn (declared in HTMLCanvasElement.h)
// is the same snapshot as DRAWN, for the browser's own readers that show the
// canvas and never hand its bytes to a page: -moz-element, the drag image, the
// taskbar preview, nsDOMWindowUtils. Its call of the display helper stays the
// as-drawn one, or those readers would see the placeholder projected.
// (Printing draws the canvas into a static clone that no page can read, so it
// is left on the page road: a difference nothing can observe is not one to add
// code for.)

#include "CanvasUtils.h"
#include "mozilla/Assertions.h"
#include "mozilla/RefPtr.h"
#include "mozilla/dom/HTMLCanvasElement.h"
#include "mozilla/dom/StealthCanvasUtils.h"
#include "mozilla/gfx/2D.h"
#include "mozilla/gfx/DrawTargetRecording.h"
#include "mozilla/gfx/StealthCanvasProjection.h"

namespace mozilla::dom {

already_AddRefed<gfx::SourceSurface> HTMLCanvasElement::GetSurfaceSnapshot(
    gfxAlphaType* aOutAlphaType, gfx::DrawTarget* aTarget) {
  gfxAlphaType alphaType = gfxAlphaType::Premult;
  RefPtr<gfx::SourceSurface> drawn = GetSurfaceSnapshotAsDrawn(
      aOutAlphaType ? &alphaType : nullptr, aTarget);
  if (aOutAlphaType) {
    *aOutAlphaType = alphaType;
  }
  if (!drawn) {
    return nullptr;
  }
  // A 2D or bitmaprenderer canvas is a source as it was drawn, as on retail:
  // the canvas noise is a WebGL/WebGPU readback only.
  if (!CanvasUtils::StealthProjectsContextType(GetCurrentContextType())) {
    return drawn.forget();
  }
  const bool premultiplied = alphaType != gfxAlphaType::NonPremult;
  // A canvas drawn onto a canvas that records for the GPU process stays on the
  // GPU: the projection is recorded and runs there, where the pixels are
  // (RecordedStealthProjectSurface). Reading it back here to project it would
  // cost a readback per drawImage that the real browser does not pay.
  // The test is on the underlying type, as in StealthProjectedSurface: since
  // 157 a canvas recording's snapshot answers CANVAS_RECORDING to GetType(),
  // and asking GetType() sent every such drawImage to the readback below.
  if (aTarget && aTarget->IsRecording() &&
      drawn->GetUnderlyingType() == gfx::SurfaceType::RECORDING) {
    const gfx::StealthCanvasNoise noise =
        CanvasUtils::StealthNoise(NodePrincipal());
    if (!noise) {
      return drawn.forget();
    }
    return static_cast<gfx::DrawTargetRecording*>(aTarget)
        ->StealthProjectedSurface(drawn, premultiplied, noise);
  }
  return CanvasUtils::StealthProjectSnapshot(drawn, premultiplied,
                                             NodePrincipal());
}

}  // namespace mozilla::dom
