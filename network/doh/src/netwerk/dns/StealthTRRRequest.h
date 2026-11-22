/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// STEALTH-HOOK(network/doh)
//
// What TRR::SendHTTPRequest does for the DoH request of a lookup made in a
// browser context: the request leaves by the proxy of that context, which the
// proxy filter answers by the userContextId of the load info of the channel.
// The suffix passed is the origin suffix of the lookup (TRR::mOriginSuffix).

#ifndef mozilla_net_StealthTRRRequest_h
#define mozilla_net_StealthTRRRequest_h

#include "nsError.h"
#include "nsStringFwd.h"

class nsIChannel;

namespace mozilla::net {

/**
 * Gives the load info of aChannel (the DoH channel just made) the context of
 * the lookup, as StealthApplyTRRContextToChannel (StealthTRRContext.h): nothing
 * for the default context. True when that failed: the request would leave by the
 * wrong proxy, so the caller returns *aRv at once. *aRv is set in every case.
 */
bool StealthTRRApplyContext(const nsACString& aOriginSuffix,
                            nsIChannel* aChannel, nsresult* aRv);

/**
 * The connection info the TRR service caches belongs to the default context
 * and the proxy of the browser: aPrefValue (network.trr.async_connInfo) stays
 * as it is for a lookup of the default context, and a lookup of another context
 * never takes it. Pure.
 */
bool StealthTRRConnInfoUsable(const nsACString& aOriginSuffix,
                              bool aPrefValue);

}  // namespace mozilla::net

#endif  // mozilla_net_StealthTRRRequest_h
