/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_net_StealthDocumentChannel_h
#define mozilla_net_StealthDocumentChannel_h

#include "mozilla/Maybe.h"
#include "mozilla/net/NeckoChannelParams.h"
#include "nsCOMPtr.h"
#include "nsError.h"

class nsIChannel;
class nsIURI;

namespace mozilla::net {

/**
 * The channel a proxy lookup is made for when it is made on behalf of a document (the ICE sockets of a PeerConnection):
 * built from the document's load info, as WebrtcTCPSocket builds the channel of its HTTP proxy, so that the proxy
 * filters (Juggler's, per browser context) see the origin attributes of the document and answer with the proxy its
 * context uses, bypass list included. Parent process, main thread. One function for WebrtcTCPSocket (the lookup of its
 * proxy) and for the lookup of the UDP.
 */
nsresult StealthNewChannelOfLoadInfo(nsIURI* aURI, uint32_t aProxyResolveFlags,
                                     const LoadInfoArgs& aLoadInfoArgs,
                                     nsIChannel** aResult);

/**
 * The load info of a proxy lookup (ProxyConfigLookup::Create), without a parameter of Mozilla's signatures.
 *
 * Main thread only: Create is called there, and so are the messages of PSocketProcess and the callers below.
 *
 *  - A caller sets the load info of the lookup it is about to make (StealthSetLookupLoadInfo) on the statement before
 *    the call of Create. It is "pending".
 *  - The first statement of Create (StealthEnterLookupLoadInfo) takes it: pending becomes "active" and pending is empty
 *    again. A Create that no caller set a load info for makes the active one empty. The active load info is read by
 *    nothing but the two places of that one call (the channel built in the parent process, StealthSwapLookupChannel; the
 *    message sent to the parent when the lookup is made in the socket process, StealthSendLookupLoadInfo), and it is
 *    replaced by the next Create: a load info never reaches a lookup it was not set for.
 *  - Socket process: ProxyConfigLookupChild::Create sends it (a message of PSocketProcess, always, empty when empty)
 *    right before the constructor of PProxyConfigLookup. The messages of one protocol arrive in the order they were
 *    sent. The parent keeps what it received in the slot of the socket process actor (StealthParkLookupLoadInfo, called
 *    by SocketProcessParent::RecvStealthProxyLookupLoadInfo), and the constructor of the lookup takes it
 *    (StealthTakeParkedLookupLoadInfo, first statement of RecvPProxyConfigLookupConstructor): the slot is emptied by
 *    that take and is overwritten by the next message, so the load info of one lookup is not the next one's, and a
 *    lookup made in the parent process in between (it has no actor) never reads it.
 */
void StealthSetLookupLoadInfo(const Maybe<LoadInfoArgs>& aLoadInfo);
void StealthEnterLookupLoadInfo();
Maybe<LoadInfoArgs> StealthActiveLookupLoadInfo();
void StealthParkLookupLoadInfo(const void* aOwner,
                               const Maybe<LoadInfoArgs>& aLoadInfo);
void StealthTakeParkedLookupLoadInfo(const void* aOwner);

/**
 * The swap both lookups make (the lookup of ProxyConfigLookup and the one of WebrtcTCPSocket): aChannel, the channel upstream
 * made with the system principal for the proxy lookup, becomes the channel of aLoadInfo (StealthNewChannelOfLoadInfo) and
 * upstream's is dropped. The dropped channel is a stand-in that was never given to anything: nothing opens it (no AsyncOpen,
 * no Open) before or while it is dropped, it is released. True: the new channel could not be made, *aRv is the error, and
 * aChannel is left as it was.
 */
bool StealthSwapChannelOfLoadInfo(nsIURI* aURI, uint32_t aProxyResolveFlags,
                                  const LoadInfoArgs& aLoadInfo,
                                  nsCOMPtr<nsIChannel>& aChannel,
                                  nsresult* aRv);

/**
 * ProxyConfigLookup::DoProxyResolve, right after upstream made the stand-in channel with the system principal: when the
 * lookup has a load info, aChannel becomes the channel of that load info (StealthNewChannelOfLoadInfo) and upstream's is
 * dropped; a lookup with none keeps upstream's. True: the channel could not be made, *aRv is the error and the caller
 * returns it.
 */
bool StealthSwapLookupChannel(nsIURI* aURI, uint32_t aProxyResolveFlags,
                              nsCOMPtr<nsIChannel>& aChannel, nsresult* aRv);

/**
 * ProxyConfigLookupChild::Create (socket process): the load info of the lookup, in a message of its own, sent on every
 * path that sends the constructor of PProxyConfigLookup and right before it. aActor is the SocketProcessChild.
 */
template <typename ActorT>
void StealthSendLookupLoadInfo(ActorT* aActor) {
  (void)aActor->SendStealthProxyLookupLoadInfo(StealthActiveLookupLoadInfo());
}

}  // namespace mozilla::net

#endif  // mozilla_net_StealthDocumentChannel_h
