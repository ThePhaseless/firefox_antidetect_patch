/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthNavigationEvents_h
#define mozilla_dom_StealthNavigationEvents_h

#include <inttypes.h>

#include "mozilla/Assertions.h"
#include "mozilla/Services.h"
#include "mozilla/dom/CanonicalBrowsingContext.h"
#include "mozilla/dom/ContentParent.h"
#include "nsCOMPtr.h"
#include "nsDocShellLoadState.h"
#include "nsIObserverService.h"
#include "nsISupportsImpl.h"
#include "nsPrintfCString.h"
#include "nsString.h"

namespace mozilla::dom {

// Tells the automation layer (observer topic
// "juggler-navigation-started-browser") that a top-level load is about to
// start. The subject is the browsing context, the data is the load identifier
// of aLoadState as a decimal string. Call it right before the Mozilla
// CanonicalBrowsingContext::LoadURI(aLoadState, true) in the two entry points
// that start a load from a URI (LoadURI with LoadURIOptions and
// FixupAndLoadURIString). Main thread only.
//
// Header-only on purpose, so that docshell/base/moz.build needs no extra line:
// it is included from CanonicalBrowsingContext.cpp, and from
// netwerk/ipc/DocumentLoadListener.cpp by its path (it is not exported).
inline void StealthNotifyNavigationStarted(CanonicalBrowsingContext* aContext,
                                           nsDocShellLoadState* aLoadState) {
  MOZ_ASSERT(aContext);
  MOZ_ASSERT(aLoadState);
  nsCOMPtr<nsIObserverService> observerService =
      mozilla::services::GetObserverService();
  if (observerService) {
    observerService->NotifyObservers(
        ToSupports(aContext), "juggler-navigation-started-browser",
        NS_ConvertASCIItoUTF16(
            nsPrintfCString("%" PRIu64, aLoadState->GetLoadIdentifier()))
            .get());
  }
}

// Tells the automation layer (observer topic "juggler-navigation-moved") that
// the parent process decided that a document load leaves the docShell that
// started it: DocumentLoadListener::TriggerProcessSwitch, right before it
// disconnects the listeners of the old process. From that instant the stand-in
// of the request that docShell still holds counts for nothing (the Cancel it
// sends is ignored, the load goes on), so a stop of it by the old page is not
// the end of the navigation. The subject is the browsing context the load
// leaves (aContext, whose current process is aContentParent), the data is
// "<load identifier> <child id>" with the child id of aContentParent (the one
// the content process reads as Services.appinfo.uniqueProcessID; not the system
// pid, which a sandbox may show differently to the two sides), 0 when there is
// none: a docShell of the parent process is 0 on both sides. Nothing is told
// for a load that goes to a new tab (the old docShell cancels it for real) nor
// for an object load: the conditions are here, the call site is one line. Main
// thread only.
inline void StealthNotifyNavigationMoved(CanonicalBrowsingContext* aContext,
                                         ContentParent* aContentParent,
                                         uint64_t aLoadIdentifier,
                                         bool aIsDocumentLoad,
                                         bool aIsNewTab) {
  MOZ_ASSERT(aContext);
  if (!aIsDocumentLoad || aIsNewTab) {
    return;
  }
  nsCOMPtr<nsIObserverService> observerService =
      mozilla::services::GetObserverService();
  if (observerService) {
    uint64_t childId = aContentParent ? uint64_t(aContentParent->ChildID()) : 0;
    observerService->NotifyObservers(
        ToSupports(aContext), "juggler-navigation-moved",
        NS_ConvertASCIItoUTF16(
            nsPrintfCString("%" PRIu64 " %" PRIu64, aLoadIdentifier, childId))
            .get());
  }
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthNavigationEvents_h
