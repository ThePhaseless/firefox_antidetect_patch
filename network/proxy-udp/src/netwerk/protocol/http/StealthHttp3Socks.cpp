/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthHttp3Socks.h"

#include "Http3ConnectUDPStream.h"
#include "nsHttpConnectionInfo.h"
#include "nsIProxyInfo.h"
#include "nsIUDPSocket.h"
#include "nsProxyInfo.h"

namespace mozilla::net {

bool StealthProxyAllowsHttp3(nsProxyInfo* aPi, bool aMozilla) {
  return aMozilla || (aPi && aPi->IsSOCKS5());
}

bool StealthHttp3ThroughSocks5(nsHttpConnectionInfo* aConnInfo, bool aMozilla) {
  return aMozilla || (aConnInfo->IsHttp3() && aConnInfo->ProxyInfo() && aConnInfo->ProxyInfo()->IsSOCKS5());
}

bool StealthSocksResolvesHost(bool aIsHttp3, bool aMozilla) { return aMozilla && !aIsHttp3; }

bool StealthUseNsprForSocksUdp(nsHttpConnectionInfo* aConnInfo, bool aMozilla) {
  return aMozilla || (aConnInfo->ProxyInfo() && aConnInfo->ProxyInfo()->IsSOCKS5());
}

bool StealthSocksProxyIsHttp3Capable(nsIProxyInfo* aProxyInfo, bool aMozilla) {
  return aMozilla || (aProxyInfo && static_cast<nsProxyInfo*>(aProxyInfo)->IsSOCKS5());
}

bool StealthSocksProxyOfUdpSocketFailed(nsHttpConnectionInfo* aConnInfo, nsIUDPSocket* aSocket, bool aIsInTunnel) {
  if (!aIsInTunnel && aConnInfo && aConnInfo->ProxyInfo() && aConnInfo->ProxyInfo()->IsSOCKS5()) {
    return NS_FAILED(aSocket->SetSocksProxy(aConnInfo->ProxyInfo()));
  }
  return false;
}

// nsIUDPSocket.setSocksProxy is for the sockets that leave by a SOCKS5 proxy; this stream goes by its own HTTP proxy (CONNECT-UDP).
NS_IMETHODIMP Http3ConnectUDPStream::SetSocksProxy(nsIProxyInfo* aProxyInfo) { return NS_ERROR_NOT_IMPLEMENTED; }

}  // namespace mozilla::net
