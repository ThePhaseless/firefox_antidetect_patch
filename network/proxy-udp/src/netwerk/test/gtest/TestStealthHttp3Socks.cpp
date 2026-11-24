/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// STEALTH-HOOK(network/proxy-udp)
//
// HTTP/3 through a SOCKS5 proxy: each function is the truth table of the Mozilla statement it wraps, with the SOCKS5 term added
// (StealthHttp3Socks.h). The control of every case is the same call with a proxy that is not SOCKS5 (HTTP, SOCKS4) or with no proxy at
// all, where the answer is Mozilla's own. The proxy infos come from the proxy service, as the session's filter makes them.

#include "gtest/gtest.h"

#include "StealthHttp3Socks.h"
#include "mozilla/OriginAttributes.h"
#include "nsComponentManagerUtils.h"
#include "nsContentUtils.h"
#include "nsHttpConnectionInfo.h"
#include "nsIProtocolProxyService.h"
#include "nsIUDPSocket.h"
#include "nsNetCID.h"
#include "nsProxyInfo.h"
#include "nsServiceManagerUtils.h"
#include "nsSOCKSUDPIOLayer.h"
#include "nsTArray.h"
#include "prio.h"

namespace mozilla::net {
namespace {

// Holds what a test makes for as long as the test runs, so that the functions are given plain pointers.
struct Kit {
  nsTArray<RefPtr<nsProxyInfo>> mProxies;
  nsTArray<RefPtr<nsHttpConnectionInfo>> mConnections;

  nsProxyInfo* Proxy(const char* aType, uint32_t aFlags = 0) {
    nsCOMPtr<nsIProtocolProxyService> ps = do_GetService(NS_PROTOCOLPROXYSERVICE_CONTRACTID);
    if (!ps) {
      return nullptr;
    }
    nsCOMPtr<nsIProxyInfo> info;
    nsresult rv = ps->NewProxyInfoWithAuth(nsDependentCString(aType), "gw.test"_ns, 1080, ""_ns, ""_ns, ""_ns, ""_ns, aFlags,
                                           UINT32_MAX, nullptr, getter_AddRefs(info));
    if (NS_FAILED(rv) || !info) {
      return nullptr;
    }
    mProxies.AppendElement(static_cast<nsProxyInfo*>(info.get()));
    return mProxies.LastElement();
  }

  nsHttpConnectionInfo* Conn(nsProxyInfo* aProxy, bool aHttp3) {
    mConnections.AppendElement(
        new nsHttpConnectionInfo("origin.test"_ns, 443, ""_ns, ""_ns, aProxy, OriginAttributes(), true, aHttp3));
    return mConnections.LastElement();
  }
};

TEST(StealthNsProxyInfoKinds, IsSOCKS5IsTrueForSocksAndSocks5Only)
{
  Kit k;
  EXPECT_TRUE(k.Proxy("socks")->IsSOCKS5());
  nsProxyInfo* socks5 = k.Proxy("socks5");  // the same proxy said out loud; the service may not know the word
  if (socks5) {
    EXPECT_TRUE(socks5->IsSOCKS5());
  }
  // The controls: the other kinds of proxy.
  EXPECT_FALSE(k.Proxy("socks4")->IsSOCKS5());
  EXPECT_FALSE(k.Proxy("http")->IsSOCKS5());
  EXPECT_FALSE(k.Proxy("https")->IsSOCKS5());
}

TEST(StealthHttp3Socks, ProxyAllowsHttp3)
{
  Kit k;
  EXPECT_TRUE(StealthProxyAllowsHttp3(k.Proxy("socks"), false));
  // Mozilla's own answer (direct, an HTTP/3 proxy, no proxy info) is never turned off.
  EXPECT_TRUE(StealthProxyAllowsHttp3(k.Proxy("http"), true));
  EXPECT_TRUE(StealthProxyAllowsHttp3(nullptr, true));
  // The controls: any other proxy with Mozilla's answer false.
  EXPECT_FALSE(StealthProxyAllowsHttp3(k.Proxy("socks4"), false));
  EXPECT_FALSE(StealthProxyAllowsHttp3(k.Proxy("http"), false));
  EXPECT_FALSE(StealthProxyAllowsHttp3(nullptr, false));
}

TEST(StealthHttp3Socks, Http3ThroughSocks5)
{
  Kit k;
  EXPECT_TRUE(StealthHttp3ThroughSocks5(k.Conn(k.Proxy("socks"), true), false));
  // HTTP/3 only: an HTTP/2 connection through the same proxy is not HTTP/3.
  EXPECT_FALSE(StealthHttp3ThroughSocks5(k.Conn(k.Proxy("socks"), false), false));
  EXPECT_FALSE(StealthHttp3ThroughSocks5(k.Conn(k.Proxy("http"), true), false));
  EXPECT_FALSE(StealthHttp3ThroughSocks5(k.Conn(k.Proxy("socks4"), true), false));
  // Mozilla's answer (an HTTP/3 proxy connection) stays.
  EXPECT_TRUE(StealthHttp3ThroughSocks5(k.Conn(k.Proxy("http"), false), true));
}

TEST(StealthHttp3Socks, SocksResolvesHost)
{
  Kit k;
  EXPECT_TRUE(StealthSocksResolvesHost(false, true));
  // An HTTP/3 connection through SOCKS5 resolves the name itself: the proxy does not.
  EXPECT_FALSE(StealthSocksResolvesHost(true, true));
  EXPECT_FALSE(StealthSocksResolvesHost(false, false));
  EXPECT_FALSE(StealthSocksResolvesHost(true, false));
}

TEST(StealthHttp3Socks, UseNsprForSocksUdp)
{
  Kit k;
  EXPECT_TRUE(StealthUseNsprForSocksUdp(k.Conn(k.Proxy("socks"), true), false));
  EXPECT_TRUE(StealthUseNsprForSocksUdp(k.Conn(nullptr, true), true)) << "the pref or the tunnel";
  EXPECT_FALSE(StealthUseNsprForSocksUdp(k.Conn(k.Proxy("http"), true), false));
  EXPECT_FALSE(StealthUseNsprForSocksUdp(k.Conn(nullptr, true), false));
}

TEST(StealthHttp3Socks, SocksProxyIsHttp3Capable)
{
  Kit k;
  nsProxyInfo* socks = k.Proxy("socks");
  nsProxyInfo* http = k.Proxy("http");
  EXPECT_TRUE(StealthSocksProxyIsHttp3Capable(socks, false));
  EXPECT_TRUE(StealthSocksProxyIsHttp3Capable(http, true)) << "an HTTP/3 proxy (Mozilla's answer)";
  EXPECT_FALSE(StealthSocksProxyIsHttp3Capable(http, false));
  EXPECT_FALSE(StealthSocksProxyIsHttp3Capable(nullptr, false));
}

// The socket takes the proxy only before it is opened: SetSocksProxy of an opened socket fails, and the function says so.
TEST(StealthHttp3Socks, SocksProxyOfUdpSocketFailed)
{
  Kit k;
  nsCOMPtr<nsIUDPSocket> opened = do_CreateInstance("@mozilla.org/network/udp-socket;1");
  ASSERT_TRUE(opened);
  ASSERT_TRUE(NS_SUCCEEDED(opened->Init(0, true, nsContentUtils::GetSystemPrincipal(), true, 1)));
  nsHttpConnectionInfo* socks = k.Conn(k.Proxy("socks"), true);
  nsHttpConnectionInfo* http = k.Conn(k.Proxy("http"), true);
  EXPECT_TRUE(StealthSocksProxyOfUdpSocketFailed(socks, opened, false)) << "an opened socket refuses its proxy";
  // The controls: inside a tunnel, through a proxy that is not SOCKS5, with no proxy, nothing is asked of the socket.
  EXPECT_FALSE(StealthSocksProxyOfUdpSocketFailed(socks, opened, true));
  EXPECT_FALSE(StealthSocksProxyOfUdpSocketFailed(http, opened, false));
  EXPECT_FALSE(StealthSocksProxyOfUdpSocketFailed(k.Conn(nullptr, true), opened, false));
  // And a socket not opened yet takes it.
  nsCOMPtr<nsIUDPSocket> fresh = do_CreateInstance("@mozilla.org/network/udp-socket;1");
  ASSERT_TRUE(fresh);
  EXPECT_FALSE(StealthSocksProxyOfUdpSocketFailed(socks, fresh, false));
  opened->Close();
  fresh->Close();
}

// The layer of an HTTP/3 socket (nsUDPSocket::InitWithAddress): a socket with no proxy is left plain; one whose layer cannot be pushed is
// reported failed (the caller closes it); one with the layer gives no OS handle. A bound socket is the one that is born.
TEST(StealthSocksUdpLayer, ASocketWithNoProxyIsLeftPlainAndALayerThatCannotBePushedFailsTheSocket)
{
  Kit k;
  PRFileDesc* plain = PR_NewUDPSocket();
  ASSERT_TRUE(plain);
  EXPECT_FALSE(StealthSocksUdpLayerFailed(plain, nullptr)) << "no proxy: nothing is done";
  EXPECT_FALSE(StealthSocksUdpHasNoHandle(plain)) << "a plain socket has an OS handle";
  StealthSocksUdpBorn(plain);  // a socket with no layer: nothing happens
  PR_Close(plain);

  PRFileDesc* refused = PR_NewUDPSocket();
  ASSERT_TRUE(refused);
  nsSOCKSUDPIOLayerFailNextPushForTests(true);
  EXPECT_TRUE(StealthSocksUdpLayerFailed(refused, k.Proxy("socks"))) << "a layer that cannot be pushed fails the socket";
  nsSOCKSUDPIOLayerFailNextPushForTests(false);
  EXPECT_FALSE(StealthSocksUdpHasNoHandle(refused)) << "the refused socket got no layer";
  PR_Close(refused);

  PRFileDesc* layered = PR_NewUDPSocket();
  ASSERT_TRUE(layered);
  EXPECT_FALSE(StealthSocksUdpLayerFailed(layered, k.Proxy("socks")));
  EXPECT_TRUE(StealthSocksUdpHasNoHandle(layered)) << "what writes on the OS handle would go direct";
  PR_Close(layered);
}

}  // namespace
}  // namespace mozilla::net
