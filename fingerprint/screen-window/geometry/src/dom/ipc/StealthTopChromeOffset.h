/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthTopChromeOffset_h
#define mozilla_dom_StealthTopChromeOffset_h

// Defined here, not in a source file of its own: dom/ipc/moz.build registers
// none for it, so the hook in BrowserParent.cpp adds no line to a shared build
// file. Included by BrowserParent.cpp only. Parent process, main thread.

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "mozilla/Maybe.h"
#include "mozilla/dom/BrowserParent.h"
#include "mozilla/dom/CanonicalBrowsingContext.h"

namespace mozilla::dom {

// Publishes the top-level browser's chrome offset (the position of its content
// area inside the native window) to every process of the BrowsingContext tree,
// in the synced field StealthTopChromeOffset of the top BrowsingContext.
//
// Why: an out-of-process iframe's BrowserChild is told a chrome offset of 0
// (BrowserParent::UpdateDimensions; its widget transform carries the offset
// instead), so its process cannot tell where the top-level content area
// starts. StealthContentOriginShift needs that point to keep the iframe's
// distance from the top-level content area when it declares the window.
//
// Only the top-level BrowserParent (no BrowserBridgeParent) writes it. A synced
// field Set is not a no-op for an equal value (it always sends the
// transaction), so the value is compared first: the caller runs this only when
// the dimensions changed, and this keeps a repeat from sending anything.
inline void StealthPublishTopChromeOffset(
    BrowserParent* aParent, const LayoutDeviceIntPoint& aChromeOffset) {
  if (!gfx::StealthEngineActive() || aParent->GetBrowserBridgeParent()) {
    return;
  }
  CanonicalBrowsingContext* bc = aParent->GetBrowsingContext();
  if (!bc) {
    return;
  }
  CanonicalBrowsingContext* top = bc->Top();
  if (top->GetStealthTopChromeOffset() == Some(aChromeOffset)) {
    return;
  }
  (void)top->SetStealthTopChromeOffset(Some(aChromeOffset));
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthTopChromeOffset_h
