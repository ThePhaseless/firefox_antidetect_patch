/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_net_StealthHttp3Socks_h
#define mozilla_net_StealthHttp3Socks_h

/*
 * HTTP/3 through a SOCKS5 proxy (network/proxy-udp).
 *
 * Firefox lets HTTP/3 go direct or through an HTTP/3 (MASQUE) proxy only. A SOCKS5 proxy whose UDP the session measured coherent
 * carries the UDP of HTTP/3 as well (UDP ASSOCIATE, nsSOCKSUDPIOLayer.cpp), so the places that decide "HTTP/3 or not" for a connection
 * also say yes for a SOCKS5 proxy, and the places that would then resolve or write on the socket by themselves leave it to the layer.
 *
 * Each function is the truth table of the Mozilla statement it wraps with the SOCKS5 case added: it takes what Mozilla's own
 * expression computed (aMozilla) and the fields that expression reads, and gives the same answer as before with the SOCKS5 term.
 */

#include "nscore.h"

class nsIProxyInfo;
class nsIUDPSocket;

namespace mozilla::net {

class nsHttpConnectionInfo;
class nsProxyInfo;

// AltSvcCache::UpdateAltServiceMapping: an h3 alt-svc is kept through a direct proxy, an HTTP/3 proxy (aMozilla), or a SOCKS5 proxy. No
// proxy info at all is allowed by Mozilla's own expression (aMozilla is true then).
bool StealthProxyAllowsHttp3(nsProxyInfo* aPi, bool aMozilla);

// DnsAndConnectSocket::DnsAndConnectSocket: a connection that uses a proxy is HTTP/3 when it is an HTTP/3 proxy connection (aMozilla),
// or an HTTP/3 connection through a SOCKS5 proxy.
bool StealthHttp3ThroughSocks5(nsHttpConnectionInfo* aConnInfo, bool aMozilla);

// DnsAndConnectSocket::CheckProxyConfig: the name is resolved by the proxy (aMozilla) only for a connection that is not HTTP/3: an HTTP/3
// connection through SOCKS5 connects to an address it resolved itself, and the UDP layer sends it to the relay.
bool StealthSocksResolvesHost(bool aIsHttp3, bool aMozilla);

// Http3Session::Init: neqo writes on the OS handle of the socket and never reaches the SOCKS5 UDP layer, so a SOCKS5 proxy sends the
// session by NSPR I/O (aMozilla is the pref or the tunnel).
bool StealthUseNsprForSocksUdp(nsHttpConnectionInfo* aConnInfo, bool aMozilla);

// HttpBaseChannel::Http3Allowed: the proxy info of the channel (aProxyInfo, the field) is a SOCKS5 proxy, or an HTTP/3 proxy (aMozilla).
bool StealthSocksProxyIsHttp3Capable(nsIProxyInfo* aProxyInfo, bool aMozilla);

// HttpConnectionUDP::InitCommon: a connection that is not inside a tunnel and goes by a SOCKS5 proxy gives its UDP socket that proxy
// (nsIUDPSocket.setSocksProxy: the layer is put on the socket when it is opened). True = the socket refused it: the connection fails.
bool StealthSocksProxyOfUdpSocketFailed(nsHttpConnectionInfo* aConnInfo, nsIUDPSocket* aSocket, bool aIsInTunnel);

}  // namespace mozilla::net

#endif  // mozilla_net_StealthHttp3Socks_h
