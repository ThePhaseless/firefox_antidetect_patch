/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthDocumentChannel.h"

#include "mozilla/Components.h"
#include "mozilla/dom/RemoteType.h"
#include "mozilla/ipc/BackgroundUtils.h"
#include "mozilla/net/SocketProcessParent.h"
#include "nsContentUtils.h"
#include "nsIChannel.h"
#include "nsIContentPolicy.h"
#include "nsIIOService.h"
#include "nsILoadInfo.h"
#include "nsThreadUtils.h"

namespace mozilla::net {

nsresult StealthNewChannelOfLoadInfo(nsIURI* aURI, uint32_t aProxyResolveFlags,
                                     const LoadInfoArgs& aLoadInfoArgs,
                                     nsIChannel** aResult) {
  MOZ_ASSERT(NS_IsMainThread());
  nsresult rv;
  nsCOMPtr<nsIIOService> ioService = components::IO::Service(&rv);
  NS_ENSURE_SUCCESS(rv, rv);

  nsCOMPtr<nsILoadInfo> loadInfo;
  // As WebrtcTCPSocket::OpenWithHttpProxy: the remote type of the process that
  // sent the arguments is not used for a security decision here.
  rv = ipc::LoadInfoArgsToLoadInfo(aLoadInfoArgs, dom::RemoteType::NotRemote(),
                                   getter_AddRefs(loadInfo));
  NS_ENSURE_SUCCESS(rv, rv);

  // -SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL: the channel is used to CONNECT to an HTTP proxy, so it must be allowed
  // to load from any origin.
  rv = ioService->NewChannelFromURIWithProxyFlags(
      aURI, aURI, aProxyResolveFlags, loadInfo->LoadingNode(),
      loadInfo->GetLoadingPrincipal(), loadInfo->TriggeringPrincipal(),
      nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
      nsIContentPolicy::TYPE_PROXIED_WEBRTC_MEDIA, aResult);
  NS_ENSURE_SUCCESS(rv, rv);
  return NS_OK;
}

namespace {

// Main thread only (the header says why). Never freed: it holds nothing between two lookups.
struct LookupLoadInfoState {
  Maybe<LoadInfoArgs> mPending;
  Maybe<LoadInfoArgs> mActive;
  const void* mParkedOwner = nullptr;
  Maybe<LoadInfoArgs> mParked;
};

LookupLoadInfoState* LookupState() {
  if (!NS_IsMainThread()) {
    return nullptr;
  }
  static LookupLoadInfoState* sState = new LookupLoadInfoState();
  return sState;
}

}  // namespace

void StealthSetLookupLoadInfo(const Maybe<LoadInfoArgs>& aLoadInfo) {
  if (LookupLoadInfoState* state = LookupState()) {
    state->mPending = aLoadInfo;
  }
}

void StealthEnterLookupLoadInfo() {
  if (LookupLoadInfoState* state = LookupState()) {
    state->mActive = std::move(state->mPending);
    state->mPending.reset();
  }
}

Maybe<LoadInfoArgs> StealthActiveLookupLoadInfo() {
  LookupLoadInfoState* state = LookupState();
  return state ? state->mActive : Maybe<LoadInfoArgs>();
}

void StealthParkLookupLoadInfo(const void* aOwner,
                               const Maybe<LoadInfoArgs>& aLoadInfo) {
  if (LookupLoadInfoState* state = LookupState()) {
    state->mParkedOwner = aOwner;
    state->mParked = aLoadInfo;
  }
}

void StealthTakeParkedLookupLoadInfo(const void* aOwner) {
  if (LookupLoadInfoState* state = LookupState()) {
    state->mPending.reset();
    if (state->mParkedOwner == aOwner) {
      state->mPending = std::move(state->mParked);
    }
    state->mParked.reset();
    state->mParkedOwner = nullptr;
  }
}

bool StealthSwapChannelOfLoadInfo(nsIURI* aURI, uint32_t aProxyResolveFlags,
                                  const LoadInfoArgs& aLoadInfo,
                                  nsCOMPtr<nsIChannel>& aChannel,
                                  nsresult* aRv) {
  nsCOMPtr<nsIChannel> channel;
  nsresult rv = StealthNewChannelOfLoadInfo(aURI, aProxyResolveFlags, aLoadInfo,
                                            getter_AddRefs(channel));
  if (NS_FAILED(rv)) {
    *aRv = rv;
    return true;
  }
  aChannel = channel.forget();
  return false;
}

bool StealthSwapLookupChannel(nsIURI* aURI, uint32_t aProxyResolveFlags,
                              nsCOMPtr<nsIChannel>& aChannel, nsresult* aRv) {
  const Maybe<LoadInfoArgs> loadInfo = StealthActiveLookupLoadInfo();
  if (loadInfo.isNothing()) {
    return false;
  }
  return StealthSwapChannelOfLoadInfo(aURI, aProxyResolveFlags, loadInfo.ref(),
                                      aChannel, aRv);
}

mozilla::ipc::IPCResult SocketProcessParent::RecvStealthProxyLookupLoadInfo(
    const Maybe<LoadInfoArgs>& aLoadInfo) {
  StealthParkLookupLoadInfo(this, aLoadInfo);
  return IPC_OK();
}

}  // namespace mozilla::net
