/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_net_StealthPcUdpProxy_h
#define mozilla_net_StealthPcUdpProxy_h

#include <functional>

#include "mozilla/Mutex.h"
#include "mozilla/RefPtr.h"
#include "nsString.h"
#include "nsTArray.h"

class nsIProxyInfo;

namespace mozilla::net {

class LoadInfoArgs;
class WebrtcProxyConfig;

// The proxy of a SOCKS5 answer, as the nsIProxyInfo of the lookup says it.
struct PcUdpSocks5Info {
  nsCString mHost;
  int32_t mPort = 0;
  nsCString mUser;
  nsCString mPass;
};

/**
 * The proxy the UDP of one PeerConnection leaves by: what Firefox itself answers when asked which proxy the document of
 * the PeerConnection uses (nsIProtocolProxyService with the proxy filters, so per browser context, bypass list and
 * credentials included), asked once when the PeerConnection is configured. Any thread.
 *
 *   Resolving  the lookup is not done yet
 *   Direct     no proxy: UDP goes out as it does on a machine with none
 *   Socks5     the proxy that carries UDP by UDP ASSOCIATE (nsSOCKSUDPIOLayer)
 *   Blocked    a proxy that carries no UDP (HTTP, HTTPS, SOCKS4): UDP goes nowhere, as behind a router that drops it
 */
class PcUdpProxy final {
 public:
  NS_INLINE_DECL_THREADSAFE_REFCOUNTING(PcUdpProxy)

  enum class Kind : uint8_t { Resolving, Direct, Socks5, Blocked };

  using Socks5Info = PcUdpSocks5Info;

  // Any thread: start the lookup for the document of aLoadInfo (it is made on the main thread).
  static already_AddRefed<PcUdpProxy> Lookup(const LoadInfoArgs& aLoadInfo);

  // An answer that is already known (the proxy of a test, a PeerConnection that has none).
  static already_AddRefed<PcUdpProxy> Known(Kind aKind, const PcUdpSocks5Info& aInfo = PcUdpSocks5Info());

  Kind GetKind(Socks5Info* aInfo = nullptr);

  // What the answer of the lookup means, as a pure function of it (the callback of Lookup calls it): a lookup that failed is a proxy that
  // is not known, so nothing goes out (Blocked); an answer with no proxy info is no proxy (Direct); a SOCKS5 proxy whose UDP the session
  // measured coherent is Socks5 (aInfo, if given, is filled with it); any other proxy carries no UDP (Blocked). Any thread.
  static Kind KindFor(nsresult aStatus, nsIProxyInfo* aProxyInfo, Socks5Info* aInfo = nullptr);

  // Any thread: aCallback runs, once, as soon as the kind is not Resolving (at once if it already is not), on the thread
  // that learned it or on the caller's.
  void WhenKnown(std::function<void()>&& aCallback);

 private:
  PcUdpProxy() = default;
  ~PcUdpProxy() = default;

  void Resolved(Kind aKind, const Socks5Info& aInfo);
  void DoLookup(const LoadInfoArgs& aLoadInfo);

  Mutex mMutex{"PcUdpProxy"};
  Kind mKind = Kind::Resolving;
  Socks5Info mInfo;
  nsTArray<std::function<void()>> mWaiting;
};

/**
 * NrSocketProxyConfig::NrSocketProxyConfig: the proxy the UDP of this PeerConnection leaves by (what Firefox answers for its
 * document), asked when the config is made, before the ICE gather asks for the first socket. The sockets of the gather are made in
 * the socket process (or in the parent), so only there is a lookup started; in a content process no UDP socket of the PeerConnection
 * is made (NrSocketBase::CreateSocket refuses it), and aProxy stays null. Read back by NrSocketProxyConfig::UdpProxy.
 */
void StealthPcUdpProxyLookup(RefPtr<PcUdpProxy>& aProxy, const WebrtcProxyConfig& aConfig);

/**
 * The same, as the expression of NrSocketProxyConfig's constructor that makes its Private: aPrivate is the new Private (mUdpProxy is its
 * member), the lookup is started on it and it is handed back, for mPrivate to own.
 */
template <typename PrivateT>
PrivateT* StealthPcUdpProxyOf(const WebrtcProxyConfig& aConfig, PrivateT* aPrivate) {
  StealthPcUdpProxyLookup(aPrivate->mUdpProxy, aConfig);
  return aPrivate;
}

}  // namespace mozilla::net

#endif  // mozilla_net_StealthPcUdpProxy_h
