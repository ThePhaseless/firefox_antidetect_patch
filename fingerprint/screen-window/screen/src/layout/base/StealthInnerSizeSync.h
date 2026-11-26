/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef LAYOUT_BASE_STEALTHINNERSIZESYNC_H_
#define LAYOUT_BASE_STEALTHINNERSIZESYNC_H_

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "mozilla/LookAndFeel.h"
#include "mozilla/dom/BrowsingContext.h"
#include "mozilla/dom/Document.h"
#include "nsDeviceContext.h"
#include "nsIWidget.h"
#include "nsPresContext.h"

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

// The window's device pixels per CSS pixel, as the root widget gives it: the
// number nsGlobalWindowOuter::CSSToDevScaleForBaseWindow gives outerWidth and
// screenX, built the same way. That one is nsIBaseWindow::
// UnscaledDevicePixelsPerCSSPixel() (the widget's default scale, rounded
// through app units per device pixel, with the OS zoom) times the
// BrowsingContext's full zoom; the base window's widget scale is the default
// scale of the window's root widget (nsDocShell::GetWidgetCSSToDeviceScale,
// AppWindow::GetWidgetCSSToDeviceScale). nsPresContext::CSSToDevPixelScale()
// is not used: it rounds the zoomed app units once more, which can differ by a
// device pixel from this product at a zoom other than 1.
inline CSSToLayoutDeviceScale StealthWindowScale(
    nsIWidget* aRootWidget, const dom::BrowsingContext* aBrowsingContext) {
  int32_t apd = nsDeviceContext::ComputeAppUnitsPerDevPixelForWidgetScale(
      aRootWidget->GetDefaultScale());
  apd = nsDeviceContext::ApplyFullZoomToAPD(
      apd, LookAndFeel::SystemZoomSettings().mFullZoom);
  CSSToLayoutDeviceScale scale(double(AppUnitsPerCSSPixel()) / double(apd));
  scale.scale *= aBrowsingContext->FullZoom();
  return scale;
}

// Called with the top-level inner size nsPresContext::
// UpdateInnerSizeSpoofedForRFP is about to set, answers it unchanged, and
// updates before it the main window's state on the same top BrowsingContext
// (gfx::StealthWindowState, one synced field): the ONE place the state changes.
// UpdateInnerSizeSpoofedForRFP runs in the process that owns the top document,
// once per change of its visible area, and sets both fields from there, so
// every other process receives them from it. Nothing for a popup (declared
// from its own frame), in fullscreen (the inner size is the screen's, and the
// window state is what it was before), or without a declaration.
inline CSSIntSize StealthInnerSizeWithWindowState(nsPresContext* aPresContext,
                                                  const CSSIntSize& aInner) {
  if (!gfx::StealthEngineActive()) {
    return aInner;
  }
  dom::Document* doc = aPresContext->Document();
  dom::BrowsingContext* bc = doc ? doc->GetBrowsingContext() : nullptr;
  nsIWidget* rootWidget = aPresContext->GetRootWidget();
  const Maybe<gfx::StealthWindowFrame> frame = gfx::StealthDeclaredWindowFrame();
  const Maybe<LayoutDeviceIntRect> maximized =
      gfx::StealthDeclaredMaximizedWindow();
  if (!bc || !rootWidget || !frame || !maximized || bc->GetIsPopupRequested() ||
      rootWidget->SizeMode() == nsSizeMode_Fullscreen) {
    return aInner;
  }
  const uint64_t current = bc->GetStealthWindowState();
  const uint64_t next = gfx::StealthPackWindowState(gfx::StealthNextWindowState(
      gfx::StealthUnpackWindowState(current), bc->GetInnerSizeSpoofedForRFP(),
      aInner, *maximized, *frame, StealthWindowScale(rootWidget, bc).scale));
  if (next != current) {
    (void)bc->SetStealthWindowState(next);
  }
  return aInner;
}

}  // namespace mozilla

#endif  // LAYOUT_BASE_STEALTHINNERSIZESYNC_H_
