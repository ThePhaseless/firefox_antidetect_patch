/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The page-facing readers of an OffscreenCanvas and of the
// transferControlToOffscreen placeholder (feature
// fingerprint/canvas/noise-projection).
//
// Mozilla's GetSurfaceSnapshot of both classes keeps the body it had, under
// the name GetSurfaceSnapshotAsDrawn (the hook is on its signature), and the
// name GetSurfaceSnapshot is defined here: the reader of a page. A reader
// Mozilla adds later that calls GetSurfaceSnapshot is a page reader and is
// projected without being taught to.
//
// Part 1, OffscreenCanvas::GetSurfaceSnapshot: the OffscreenCanvas as a page
// reads it. Every caller today is a page drawing with the canvas or reading it
// (ImageBitmap, WebGL texture upload, VideoFrame, WebGPU
// copyExternalImageToTexture, drawImage on a 2D context), the OffscreenCanvas
// twin of HTMLCanvasElement::GetSurfaceSnapshot. This is a fact about the
// callers of today, not something the code enforces: no caller asks for the
// as-drawn variant here (nsLayoutUtils::SurfaceFromOffscreenCanvas has no
// equivalent of the kStealthSfeAsDrawn check that the HTMLCanvasElement path
// has), so the day one does, the fix belongs in nsLayoutUtils.
//
// The snapshot is the context's, unchanged, for every context type the noise
// does not apply to (see StealthProjectsContextType in StealthCanvasUtils.h);
// for WebGL and WebGPU it is StealthProjectSnapshot of it, with the alpha type
// the context reported and the principal of the canvas's global.
//
// aOutAlphaType may be null. When it is not, it always receives the alpha type
// the context reported (Premult if the context reported none, as when it has
// no surface to give).
//
// Part 2, the contract of the two readers of OffscreenCanvasDisplayHelper:
//
// GetSurfaceSnapshot()          the placeholder's pixels as a page reads them
//                               (with the canvas noise). It is what a page
//                               reaches: toDataURL/toBlob, drawImage,
//                               createImageBitmap.
// GetSurfaceSnapshotAsDrawn()   the placeholder's pixels as drawn: for the
//                               browser's own readers, which show the canvas
//                               and never hand its bytes to a page (the screen
//                               through GetAsImage, -moz-element, the drag
//                               image, the taskbar preview).
//
// What a page reads of the placeholder is the worker's front buffer, through
// the canvas noise only for a WebGL/WebGPU context, the same rule the worker's
// own readers follow, so the two sides of a transferControlToOffscreen read one
// image. GetSurfaceSnapshotAsDrawn (-> TransformSurface) hands back
// premultiplied or opaque pixels, hence aPremultiplied is true below.
// GetAsImage (the screen's copy, nsHTMLCanvasFrame) reads the as-drawn surface,
// like every canvas on screen.

#include "CanvasUtils.h"
#include "OffscreenCanvasDisplayHelper.h"

#include "gfxTypes.h"
#include "mozilla/Assertions.h"
#include "mozilla/Mutex.h"
#include "mozilla/RefPtr.h"
#include "mozilla/dom/HTMLCanvasElement.h"
#include "mozilla/dom/OffscreenCanvas.h"
#include "mozilla/dom/StealthCanvasUtils.h"
#include "mozilla/gfx/2D.h"
#include "nsCOMPtr.h"
#include "nsICanvasRenderingContextInternal.h"
#include "nsIGlobalObject.h"
#include "nsIPrincipal.h"

namespace mozilla::dom {

already_AddRefed<gfx::SourceSurface> OffscreenCanvas::GetSurfaceSnapshot(
    gfxAlphaType* aOutAlphaType) {
  if (!GetContext()) {
    return nullptr;
  }

  // The context is asked into a local because aOutAlphaType may be null and
  // the alpha type is needed below either way; the caller's pointer gets it
  // back.
  gfxAlphaType alphaType = gfxAlphaType::Premult;
  RefPtr<gfx::SourceSurface> drawn =
      GetSurfaceSnapshotAsDrawn(aOutAlphaType ? &alphaType : nullptr);
  if (aOutAlphaType) {
    *aOutAlphaType = alphaType;
  }

  // The context type is read after the snapshot, as always.
  if (!CanvasUtils::StealthProjectsContextType(GetContextType())) {
    return drawn.forget();
  }

  nsIGlobalObject* const global = GetParentObject();
  return CanvasUtils::StealthProjectSnapshot(
      drawn, alphaType != gfxAlphaType::NonPremult,
      global ? global->PrincipalOrNull() : nullptr);
}

already_AddRefed<gfx::SourceSurface>
OffscreenCanvasDisplayHelper::GetSurfaceSnapshot() {
  RefPtr<gfx::SourceSurface> drawn = GetSurfaceSnapshotAsDrawn();
  nsCOMPtr<nsIPrincipal> principal;
  {
    MutexAutoLock lock(mMutex);
    if (!CanvasUtils::StealthProjectsContextType(mType)) {
      return drawn.forget();
    }
    if (mCanvasElement) {
      principal = mCanvasElement->NodePrincipal();
    }
  }
  return CanvasUtils::StealthProjectSnapshot(drawn, true, principal);
}

}  // namespace mozilla::dom
