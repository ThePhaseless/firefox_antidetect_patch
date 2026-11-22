/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthLoadInfo.h"

#include "LoadInfo.h"
#include "TRRLoadInfo.h"
#include "mozilla/OriginAttributes.h"
#include "nsError.h"
#include "nsILoadInfo.h"

namespace mozilla::net {

void StealthLoadInfoCopied(LoadInfo* aThis, const LoadInfo& aRhs) {
  // The accessors of nsILoadInfo are not const, though the getter writes
  // nothing; the infallible one is the one without an nsresult to discard.
  uint64_t identifier = const_cast<LoadInfo&>(aRhs).GetJugglerLoadIdentifier();
  (void)aThis->SetJugglerLoadIdentifier(identifier);
}

bool StealthTRRSetOriginAttributes(OriginAttributes& aField,
                                   const OriginAttributes& aValue,
                                   nsresult* aRv) {
  aField = aValue;
  *aRv = NS_OK;
  return true;
}

// nsILoadInfo.jugglerLoadIdentifier of LoadInfo: the member holds the
// identifier of the load (0 when the load never got one).
NS_IMETHODIMP
LoadInfo::GetJugglerLoadIdentifier(uint64_t* aResult) {
  *aResult = mJugglerLoadIdentifier;
  return NS_OK;
}

NS_IMETHODIMP
LoadInfo::SetJugglerLoadIdentifier(uint64_t aID) {
  mJugglerLoadIdentifier = aID;
  return NS_OK;
}

// TRRLoadInfo implements nsILoadInfo by hand and has no load identifier, as
// for the other [infallible] attributes it answers NS_ERROR_NOT_IMPLEMENTED.
NS_IMETHODIMP
TRRLoadInfo::GetJugglerLoadIdentifier(uint64_t* aResult) {
  return NS_ERROR_NOT_IMPLEMENTED;
}

NS_IMETHODIMP
TRRLoadInfo::SetJugglerLoadIdentifier(uint64_t aResult) {
  return NS_ERROR_NOT_IMPLEMENTED;
}

}  // namespace mozilla::net
