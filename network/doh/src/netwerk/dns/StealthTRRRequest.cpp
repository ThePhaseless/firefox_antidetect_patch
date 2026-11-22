/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthTRRRequest.h"

#include "mozilla/net/StealthTRRContext.h"
#include "nsDebug.h"
#include "nsIChannel.h"
#include "nsString.h"

namespace mozilla::net {

bool StealthTRRApplyContext(const nsACString& aOriginSuffix,
                            nsIChannel* aChannel, nsresult* aRv) {
  *aRv = StealthApplyTRRContextToChannel(
      aChannel, StealthTRRContextOfSuffix(aOriginSuffix));
  NS_ENSURE_SUCCESS(*aRv, true);
  return false;
}

bool StealthTRRConnInfoUsable(const nsACString& aOriginSuffix,
                              bool aPrefValue) {
  return aPrefValue && StealthTRRContextOfSuffix(aOriginSuffix).isNothing();
}

}  // namespace mozilla::net
