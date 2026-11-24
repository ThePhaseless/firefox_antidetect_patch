/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef StealthWebrtcTcpSocket_h_
#define StealthWebrtcTcpSocket_h_

/*
 * The TCP socket of a PeerConnection (TURN over TCP, WebrtcTCPSocket) behind the proxy of the PeerConnection's context.
 *
 * Two things upstream's socket does not know, each a function called from one line of WebrtcTCPSocket.cpp. They read the private
 * state of the socket through the one friend of the class, StealthWebrtcTcpSocketAccess.
 */

#include "WebrtcTCPSocket.h"
#include "mozilla/net/StealthDocumentChannel.h"
#include "nsIProtocolProxyService.h"
#include "transport/nr_stealth_network.h"

namespace mozilla::net {

struct StealthWebrtcTcpSocketAccess {
  // OnProxyAvailable, at the end, where upstream opens the socket plain for every outcome the dispatch above it did not take (a failed
  // lookup, a proxy of a type it does not know): a socket whose context has a proxy never goes out plain because of that. True = the
  // socket is closed, and nothing opens it. The rule is StealthTcpDirectRefused (nr_stealth_network.h).
  static bool TcpSocketRefusesDirect(WebrtcTCPSocket* aSocket, nsresult aResult, nsIProxyInfo* aProxyInfo) {
    if (!mozilla::StealthTcpDirectRefused(aSocket->mProxyConfig.isSome(), NS_FAILED(aResult), aProxyInfo)) {
      return false;
    }
    aSocket->CloseWithReason(NS_ERROR_FAILURE);
    return true;
  }

  // OpenWithoutHttpProxy, after Mozilla parsed the local address into aAddr: the transport of the socket is given the context of its
  // name lookup, and aAddr becomes the wildcard of its family on port 0 (StealthTcpSocketBorn). Before the bind, which refuses
  // attributes once the socket exists. The address parsed already: the second parse cannot fail.
  static void TcpSocketBorn(WebrtcTCPSocket* aSocket, union PRNetAddr* aAddr) {
    (void)mozilla::StealthTcpSocketBorn(aSocket->mTransport, aSocket->mProxyConfig.ptrOr(nullptr),
                                        aSocket->mLocalAddress.get(), aSocket->mLocalPort, aAddr);
  }
};

inline bool StealthTcpSocketRefusesDirect(WebrtcTCPSocket* aSocket, nsresult aResult, nsIProxyInfo* aProxyInfo) {
  return StealthWebrtcTcpSocketAccess::TcpSocketRefusesDirect(aSocket, aResult, aProxyInfo);
}

inline void StealthTcpSocketBorn(WebrtcTCPSocket* aSocket, union PRNetAddr* aAddr) {
  StealthWebrtcTcpSocketAccess::TcpSocketBorn(aSocket, aAddr);
}

}  // namespace mozilla::net

#endif  // StealthWebrtcTcpSocket_h_
