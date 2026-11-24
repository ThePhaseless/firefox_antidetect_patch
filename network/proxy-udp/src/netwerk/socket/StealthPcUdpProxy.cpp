/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthPcUdpProxy.h"

#include "mozilla/net/ProxyConfigLookup.h"
#include "mozilla/net/StealthDocumentChannel.h"
#include "mozilla/net/WebrtcProxyConfig.h"
#include "mozilla/Maybe.h"
#include "mozilla/net/NeckoChannelParams.h"
#include "nsIProtocolProxyService.h"
#include "nsIProxyInfo.h"
#include "nsIURI.h"
#include "nsNetUtil.h"
#include "nsProxyInfo.h"
#include "nsThreadUtils.h"
#include "nsUDPSocket.h"
#include "nsXULAppAPI.h"

namespace mozilla::net {

// These pointers are declared in nsProtocolProxyService.cpp; the type of an nsProxyInfo is compared by pointer (as nsProxyInfo.cpp does).
extern const char kProxyType_SOCKS[];
extern const char kProxyType_SOCKS5[];

// static
already_AddRefed<PcUdpProxy> PcUdpProxy::Known(Kind aKind, const Socks5Info& aInfo) {
  RefPtr<PcUdpProxy> proxy = new PcUdpProxy();
  proxy->mKind = aKind;
  proxy->mInfo = aInfo;
  return proxy.forget();
}

// static
already_AddRefed<PcUdpProxy> PcUdpProxy::Lookup(const LoadInfoArgs& aLoadInfo) {
  RefPtr<PcUdpProxy> proxy = new PcUdpProxy();
  // The lookup is made on the main thread; the arguments are copied into the runnable.
  (void)NS_DispatchToMainThread(NS_NewRunnableFunction(
      "PcUdpProxy::Lookup", [proxy, args = aLoadInfo]() { proxy->DoLookup(args); }));
  return proxy.forget();
}

void PcUdpProxy::DoLookup(const LoadInfoArgs& aLoadInfo) {
  MOZ_ASSERT(NS_IsMainThread());
  // The question is "which proxy does this browser context use for the internet?", not "for the address of this page": the
  // UDP of a PeerConnection goes to STUN and TURN servers on the internet whatever the page is. A page on the loopback, a
  // file:, a data: or a sandboxed srcdoc has no proxy of its own address (Necko answers "none" for them, or runs no filter),
  // and that answer must not become "this PeerConnection has no proxy" while the context has one. So the lookup asks about a
  // public https address, with the load info of the document: the proxy filters then see the context of the page.
  nsCOMPtr<nsIURI> uri;
  nsresult rv = NS_NewURI(getter_AddRefs(uri), "https://stun.invalid/"_ns);
  if (NS_FAILED(rv)) {
    Resolved(Kind::Blocked, Socks5Info());
    return;
  }
  RefPtr<PcUdpProxy> self = this;
  // The load info of the document is the one of this lookup alone: Create takes it (StealthDocumentChannel.h).
  StealthSetLookupLoadInfo(Some(aLoadInfo));
  rv = ProxyConfigLookup::Create(
      [self](nsIProxyInfo* aProxyInfo, nsresult aStatus) {
        Socks5Info info;
        const Kind kind = KindFor(aStatus, aProxyInfo, &info);
        self->Resolved(kind, info);
      },
      uri, nsIProtocolProxyService::RESOLVE_PREFER_SOCKS_PROXY, false, nullptr);
  if (NS_FAILED(rv)) {
    // The lookup could not be made: the proxy is not known, so nothing goes out (see above).
    Resolved(Kind::Blocked, Socks5Info());
  }
}

// static
PcUdpProxy::Kind PcUdpProxy::KindFor(nsresult aStatus, nsIProxyInfo* aProxyInfo, Socks5Info* aInfo) {
  Socks5Info scratch;
  Socks5Info& info = aInfo ? *aInfo : scratch;
  info = Socks5Info();
  // A failed lookup is a proxy that is not known: nothing goes out. A lookup that answers with no proxy info is a
  // PeerConnection with no proxy.
  Kind kind = NS_SUCCEEDED(aStatus) ? Kind::Direct : Kind::Blocked;
  if (NS_SUCCEEDED(aStatus) && aProxyInfo) {
    nsAutoCString type;
    aProxyInfo->GetType(type);
    uint32_t flags = 0;
    aProxyInfo->GetFlags(&flags);
    if (type.EqualsLiteral("socks") && (flags & nsIProxyInfo::CARRIES_COHERENT_UDP)) {
      // SOCKS5 whose UDP the session measured coherent: the road of the PeerConnection's UDP.
      kind = Kind::Socks5;
      aProxyInfo->GetHost(info.mHost);
      aProxyInfo->GetPort(&info.mPort);
      aProxyInfo->GetUsername(info.mUser);
      aProxyInfo->GetPassword(info.mPass);
    } else if (!type.EqualsLiteral("direct")) {
      kind = Kind::Blocked;
    }
  }
  return kind;
}

void PcUdpProxy::Resolved(Kind aKind, const Socks5Info& aInfo) {
  nsTArray<std::function<void()>> waiting;
  {
    MutexAutoLock lock(mMutex);
    if (mKind != Kind::Resolving) {
      return;
    }
    mKind = aKind;
    mInfo = aInfo;
    waiting = std::move(mWaiting);
  }
  for (auto& callback : waiting) {
    callback();
  }
}

PcUdpProxy::Kind PcUdpProxy::GetKind(Socks5Info* aInfo) {
  MutexAutoLock lock(mMutex);
  if (aInfo && mKind == Kind::Socks5) {
    *aInfo = mInfo;
  }
  return mKind;
}

void PcUdpProxy::WhenKnown(std::function<void()>&& aCallback) {
  {
    MutexAutoLock lock(mMutex);
    if (mKind == Kind::Resolving) {
      mWaiting.AppendElement(std::move(aCallback));
      return;
    }
  }
  aCallback();
}

void StealthPcUdpProxyLookup(RefPtr<PcUdpProxy>& aProxy, const WebrtcProxyConfig& aConfig) {
  if (XRE_IsSocketProcess() || XRE_IsParentProcess()) {
    aProxy = PcUdpProxy::Lookup(aConfig.loadInfoArgs());
  }
}

// A SOCKS5 proxy: "socks" is SOCKS5 in Firefox's PAC and proxy-service strings, "socks5" is the same said out loud. Whether it carries
// UDP is another question (the flag CARRIES_COHERENT_UDP); this is only the type.
bool nsProxyInfo::IsSOCKS5() { return mType == kProxyType_SOCKS || mType == kProxyType_SOCKS5; }

// The SOCKS5 proxy the datagrams of this socket go by (UDP ASSOCIATE), as the connection that owns it learned it: the SOCKS5 UDP layer
// is put on the socket when it is opened (nsSOCKSUDPIOLayer.h, StealthSocksUdpLayerOn). Call before InitWithAddress. A proxy that is
// not SOCKS5 is ignored by the layer. No proxy: the socket is a plain one.
NS_IMETHODIMP nsUDPSocket::SetSocksProxy(nsIProxyInfo* aProxyInfo) {
  NS_ENSURE_TRUE(mFD == nullptr, NS_ERROR_ALREADY_INITIALIZED);
  mSocksProxy = aProxyInfo;
  return NS_OK;
}

}  // namespace mozilla::net
