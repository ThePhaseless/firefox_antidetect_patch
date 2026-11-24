/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Behind a proxy the DNS-over-HTTPS request leaves by the proxy of the browser
// context whose lookup caused it: the context (userContextId) of the lookup
// travels from the TRR request to the proxy lookup, and the proxy filter of the
// session sees it on the stand-in channel.

#include "StealthTRRRequest.h"
#include "TRRLoadInfo.h"
#include "gtest/gtest.h"
#include "mozilla/BasePrincipal.h"
#include "mozilla/Maybe.h"
#include "mozilla/OriginAttributes.h"
#include "mozilla/Preferences.h"
#include "mozilla/RefPtr.h"
#include "mozilla/SpinEventLoopUntil.h"
#include "mozilla/net/ProxyConfigLookup.h"
#include "mozilla/net/StealthTRRContext.h"
#include "nsCOMPtr.h"
#include "nsComponentManagerUtils.h"
#include "nsContentUtils.h"
#include "nsIChannel.h"
#include "nsIContentPolicy.h"
#include "nsILoadInfo.h"
#include "nsIProtocolProxyFilter.h"
#include "nsIProtocolProxyService.h"
#include "nsIParentalControlsService.h"
#include "nsIPrincipal.h"
#include "nsIProxyInfo.h"
#include "nsISocketTransport.h"
#include "nsISocketTransportService.h"
#include "nsNetUtil.h"
#include "nsServiceManagerUtils.h"
#include "nsString.h"
#include "nsTArray.h"

namespace mozilla::net {

namespace {

// The proxy filter of the session in one line: it records the context of the
// channel it is asked about and answers with the default proxy info.
class RecordingFilter final : public nsIProtocolProxyChannelFilter {
 public:
  NS_DECL_ISUPPORTS
  NS_IMETHOD ApplyFilter(nsIChannel* aChannel, nsIProxyInfo* aProxyInfo,
                         nsIProxyProtocolFilterResult* aCallback) override {
    nsCOMPtr<nsILoadInfo> loadInfo = aChannel->LoadInfo();
    mUserContextId = loadInfo->GetOriginAttributes().mUserContextId;
    mAsked = true;
    return aCallback->OnProxyFilterResult(aProxyInfo);
  }
  bool mAsked = false;
  uint32_t mUserContextId = 99999;

 private:
  ~RecordingFilter() = default;
};
NS_IMPL_ISUPPORTS(RecordingFilter, nsIProtocolProxyChannelFilter)

// The two members the channel hooks use, as the channel classes have them.
struct FakeChannel {
  int mClosed = 0;
  int mAborted = 0;
  nsresult mAbortStatus = NS_OK;
  void CloseCacheEntry(bool aDoomOnFailure) { ++mClosed; }
  nsresult AsyncAbort(nsresult aStatus) {
    ++mAborted;
    mAbortStatus = aStatus;
    return NS_OK;
  }
};

Maybe<OriginAttributes> ContextOf(uint32_t aUserContextId) {
  OriginAttributes attrs;
  attrs.mUserContextId = aUserContextId;
  return Some(attrs);
}

}  // namespace

// The default context is answered by the browser's proxy, as upstream: nothing
// is carried. Every other attribute of the suffix is left behind.
TEST(TestStealthTRRContext, SuffixOfTheDefaultContextCarriesNothing)
{
  EXPECT_TRUE(StealthTRRContextOfSuffix(""_ns).isNothing());
  EXPECT_TRUE(StealthTRRContextOfSuffix("^privateBrowsingId=1"_ns).isNothing());
  EXPECT_TRUE(StealthTRRContextOfSuffix(
                  "^partitionKey=%28https%2Cexample.com%29"_ns)
                  .isNothing());
  EXPECT_TRUE(StealthTRRContextOfSuffix("^userContextId=0"_ns).isNothing());
}

TEST(TestStealthTRRContext, SuffixOfAContextCarriesTheUserContextIdAlone)
{
  Maybe<OriginAttributes> context = StealthTRRContextOfSuffix(
      "^userContextId=7&partitionKey=%28https%2Cexample.com%29"_ns);
  ASSERT_TRUE(context.isSome());
  EXPECT_EQ(context->mUserContextId, 7u);
  EXPECT_TRUE(context->mPartitionKey.IsEmpty());
}

// The OCSP request of a certificate is made for the page's TLS: it keeps of the
// page's attributes the first party domain and the private browsing id (as
// Mozilla's code in nsNSSCallbacks.cpp copies them) and, from this function, the
// context, which is what the proxy filter answers by. Without it the request
// left in the default context, outside the proxy of the page's context.
TEST(TestStealthTRRContext, TheOcspRequestKeepsTheContextOfThePage)
{
  OriginAttributes page;
  page.mUserContextId = 7;
  page.mFirstPartyDomain.Assign(u"a.test"_ns);
  page.mPrivateBrowsingId = 1;
  // What Mozilla's code copies before the hook.
  OriginAttributes request;
  request.mFirstPartyDomain = page.mFirstPartyDomain;
  request.mPrivateBrowsingId = page.mPrivateBrowsingId;

  StealthKeepRequestContext(page, request);

  EXPECT_EQ(request.mUserContextId, 7u);
  EXPECT_TRUE(request.mFirstPartyDomain.Equals(u"a.test"_ns));
  EXPECT_EQ(request.mPrivateBrowsingId, 1u);
  EXPECT_TRUE(request.mPartitionKey.IsEmpty());
  EXPECT_TRUE(request != OriginAttributes());
}

TEST(TestStealthTRRContext, TheOcspRequestOfTheDefaultContextIsUnchanged)
{
  OriginAttributes page;  // userContextId 0
  OriginAttributes request;
  request.mPrivateBrowsingId = 1;
  StealthKeepRequestContext(page, request);
  EXPECT_EQ(request.mUserContextId, 0u);
  EXPECT_EQ(request.mPrivateBrowsingId, 1u);
}

// The TLS layered over a tunnel is made for the page whose connection it is;
// with no transport it is the default context, as it always was.
TEST(TestStealthTRRContext, ATlsOverATunnelWithoutATransportIsInTheDefaultContext)
{
  EXPECT_TRUE(StealthTransportContext(nullptr) == OriginAttributes());
}

// The Safe Browsing completion of a page load is requested in the context of
// that page: Classify opens a scope with the page's principal, the lookup
// callbacks made inside it read the context, the default context stays 0.
TEST(TestStealthTRRContext, ALookupScopeCarriesTheContextOfThePrincipalAndRestores)
{
  nsCOMPtr<nsIURI> uri;
  ASSERT_EQ(NS_NewURI(getter_AddRefs(uri), "https://a.test/"_ns), NS_OK);
  OriginAttributes attrs;
  attrs.mUserContextId = 7;
  RefPtr<BasePrincipal> page = BasePrincipal::CreateContentPrincipal(uri, attrs);
  ASSERT_TRUE(page);
  RefPtr<BasePrincipal> plain =
      BasePrincipal::CreateContentPrincipal(uri, OriginAttributes());
  ASSERT_TRUE(plain);

  EXPECT_EQ(StealthCurrentLookupContext(), 0u);
  {
    StealthLookupContextScope outer(page.get());
    EXPECT_EQ(StealthCurrentLookupContext(), 7u);
    {
      uint32_t other = 3;
      StealthLookupContextScope inner(other);
      EXPECT_EQ(StealthCurrentLookupContext(), 3u);
    }
    EXPECT_EQ(StealthCurrentLookupContext(), 7u);
  }
  EXPECT_EQ(StealthCurrentLookupContext(), 0u);

  StealthLookupContextScope defaultContext(plain.get());
  EXPECT_EQ(StealthCurrentLookupContext(), 0u);
  StealthLookupContextScope noPrincipal(static_cast<nsIPrincipal*>(nullptr));
  EXPECT_EQ(StealthCurrentLookupContext(), 0u);
}

TEST(TestStealthTRRContext, TheLookupContextGetterGivesTheContextAndRefusesNull)
{
  uint32_t out = 99;
  EXPECT_EQ(StealthLookupContextOut(7, &out), NS_OK);
  EXPECT_EQ(out, 7u);
  EXPECT_EQ(StealthLookupContextOut(7, nullptr), NS_ERROR_INVALID_POINTER);
}

// The load info of a DoH channel off the main thread is a TRRLoadInfo; it used
// to refuse the attributes (NS_ERROR_NOT_IMPLEMENTED), so the context could
// not be put on the channel.
TEST(TestStealthTRRContext, ATRRLoadInfoTakesTheContext)
{
  RefPtr<TRRLoadInfo> loadInfo =
      new TRRLoadInfo(nullptr, nsIContentPolicy::TYPE_OTHER);
  EXPECT_TRUE(StealthTRRContextOfLoadInfo(loadInfo).isNothing());
  ASSERT_EQ(StealthApplyTRRContext(loadInfo, ContextOf(7)), NS_OK);
  Maybe<OriginAttributes> context = StealthTRRContextOfLoadInfo(loadInfo);
  ASSERT_TRUE(context.isSome());
  EXPECT_EQ(context->mUserContextId, 7u);
}

// TRRLoadInfo::SetOriginAttributes stores what it is given (upstream refused
// with NS_ERROR_NOT_IMPLEMENTED) and the load info reads it back.
TEST(TestStealthTRRContext, ATRRLoadInfoStoresWhatItIsGiven)
{
  OriginAttributes given;
  given.mUserContextId = 9;
  RefPtr<TRRLoadInfo> loadInfo =
      new TRRLoadInfo(nullptr, nsIContentPolicy::TYPE_OTHER);
  nsCOMPtr<nsILoadInfo> asLoadInfo = loadInfo.get();
  EXPECT_EQ(asLoadInfo->SetOriginAttributes(given), NS_OK);
  EXPECT_EQ(asLoadInfo->GetOriginAttributes().mUserContextId, 9u);
}

// A redirect of the DoH request is made on a clone of the load info: it stays
// in the same context, so it leaves by the same proxy.
TEST(TestStealthTRRContext, TheCloneOfATRRLoadInfoKeepsTheContext)
{
  RefPtr<TRRLoadInfo> loadInfo =
      new TRRLoadInfo(nullptr, nsIContentPolicy::TYPE_OTHER);
  ASSERT_EQ(StealthApplyTRRContext(loadInfo, ContextOf(7)), NS_OK);
  nsCOMPtr<nsILoadInfo> clone = loadInfo->Clone();
  Maybe<OriginAttributes> context = StealthTRRContextOfLoadInfo(clone);
  ASSERT_TRUE(context.isSome());
  EXPECT_EQ(context->mUserContextId, 7u);
}

TEST(TestStealthTRRContext, NothingLeavesTheLoadInfoAsItIs)
{
  RefPtr<TRRLoadInfo> loadInfo =
      new TRRLoadInfo(nullptr, nsIContentPolicy::TYPE_OTHER);
  ASSERT_EQ(StealthApplyTRRContext(loadInfo, ContextOf(7)), NS_OK);
  ASSERT_EQ(StealthApplyTRRContext(loadInfo, Nothing()), NS_OK);
  EXPECT_TRUE(StealthTRRContextOfLoadInfo(loadInfo).isSome());
}

TEST(TestStealthTRRContext, ARealChannelTakesTheContext)
{
  nsCOMPtr<nsIURI> uri;
  ASSERT_EQ(NS_NewURI(getter_AddRefs(uri), "https://example.com/dns-query"_ns),
            NS_OK);
  nsCOMPtr<nsIChannel> channel;
  ASSERT_EQ(
      NS_NewChannel(getter_AddRefs(channel), uri,
                    nsContentUtils::GetSystemPrincipal(),
                    nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                    nsIContentPolicy::TYPE_OTHER),
      NS_OK);
  ASSERT_EQ(StealthApplyTRRContextToChannel(channel, ContextOf(7)), NS_OK);
  nsCOMPtr<nsILoadInfo> loadInfo = channel->LoadInfo();
  EXPECT_EQ(loadInfo->GetOriginAttributes().mUserContextId, 7u);
}

// A DoH request whose proxy could not be learned fails; it never goes DIRECT.
TEST(TestStealthTRRContext, AFailedProxyLookupEndsTheRequest)
{
  EXPECT_EQ(StealthTRRProxyFailure(NS_ERROR_FAILURE),
            NS_ERROR_PROXY_CONNECTION_REFUSED);
  EXPECT_EQ(StealthTRRProxyFailure(NS_ERROR_NOT_AVAILABLE),
            NS_ERROR_PROXY_CONNECTION_REFUSED);
  EXPECT_EQ(StealthTRRProxyFailure(NS_ERROR_NET_TIMEOUT),
            NS_ERROR_PROXY_CONNECTION_REFUSED);
  EXPECT_EQ(StealthTRRProxyFailure(NS_ERROR_UNEXPECTED),
            NS_ERROR_PROXY_CONNECTION_REFUSED);
}

// A cancellation is not a proxy failure: it keeps its own code.
TEST(TestStealthTRRContext, ACancellationKeepsItsCode)
{
  EXPECT_EQ(StealthTRRProxyFailure(NS_ERROR_ABORT), NS_ERROR_ABORT);
  EXPECT_EQ(StealthTRRProxyFailure(NS_BINDING_ABORTED), NS_BINDING_ABORTED);
}

// The nsHttpChannel of a DoH request (main thread of the parent, no socket
// process) fails closed like TRRServiceChannel: a failed lookup of a TRR service
// channel ends it; a success, a cancellation and any other channel do not.
TEST(TestStealthTRRContext, ATRRServiceChannelWhoseProxyLookupFailedFailsClosed)
{
  EXPECT_TRUE(StealthFailClosedOnProxyFailure(NS_ERROR_FAILURE, true, false));
  EXPECT_TRUE(
      StealthFailClosedOnProxyFailure(NS_ERROR_NOT_AVAILABLE, true, false));
}

TEST(TestStealthTRRContext, OtherChannelsAndOtherOutcomesKeepUpstreamBehaviour)
{
  // An ordinary channel fails over as upstream does.
  EXPECT_FALSE(StealthFailClosedOnProxyFailure(NS_ERROR_FAILURE, false, false));
  // A lookup that succeeded.
  EXPECT_FALSE(StealthFailClosedOnProxyFailure(NS_OK, true, false));
  // A cancelled channel goes on as upstream (BeginConnect returns its status).
  EXPECT_FALSE(StealthFailClosedOnProxyFailure(NS_ERROR_FAILURE, true, true));
}

// The hook of nsHttpChannel: a TRR service channel whose lookup failed is
// closed and aborted with the proxy failure; nothing else is touched.
TEST(TestStealthTRRContext, TheHttpChannelHookEndsAFailedTRRServiceChannel)
{
  FakeChannel channel;
  EXPECT_TRUE(StealthTRRFailClosed(&channel, NS_ERROR_FAILURE, true, false));
  EXPECT_EQ(channel.mClosed, 1);
  EXPECT_EQ(channel.mAborted, 1);
  EXPECT_EQ(channel.mAbortStatus, NS_ERROR_PROXY_CONNECTION_REFUSED);
}

TEST(TestStealthTRRContext, TheHttpChannelHookLeavesTheOtherCasesToUpstream)
{
  FakeChannel channel;
  EXPECT_FALSE(StealthTRRFailClosed(&channel, NS_ERROR_FAILURE, false, false));
  EXPECT_FALSE(StealthTRRFailClosed(&channel, NS_OK, true, false));
  EXPECT_FALSE(StealthTRRFailClosed(&channel, NS_ERROR_FAILURE, true, true));
  EXPECT_EQ(channel.mClosed, 0);
  EXPECT_EQ(channel.mAborted, 0);
}

// The hook of TRRServiceChannel: the same rule, no cache entry; the start of
// the request (nothing to cancel yet) passes false for the cancellation.
TEST(TestStealthTRRContext, TheServiceChannelHookEndsAFailedLookup)
{
  FakeChannel channel;
  EXPECT_TRUE(StealthTRRServiceFailClosed(&channel, NS_ERROR_NOT_AVAILABLE,
                                          false));
  EXPECT_EQ(channel.mClosed, 0);
  EXPECT_EQ(channel.mAborted, 1);
  EXPECT_EQ(channel.mAbortStatus, NS_ERROR_PROXY_CONNECTION_REFUSED);
}

TEST(TestStealthTRRContext, TheServiceChannelHookKeepsACancellationAndASuccess)
{
  FakeChannel channel;
  EXPECT_FALSE(StealthTRRServiceFailClosed(&channel, NS_OK, false));
  EXPECT_FALSE(StealthTRRServiceFailClosed(&channel, NS_ERROR_FAILURE, true));
  EXPECT_EQ(channel.mAborted, 0);
  // A cancellation that reaches the rule keeps its own code.
  EXPECT_TRUE(StealthTRRServiceFailClosed(&channel, NS_BINDING_ABORTED, false));
  EXPECT_EQ(channel.mAbortStatus, NS_BINDING_ABORTED);
}

// The proxy lookup of a DoH request asks the proxy filters with a stand-in
// channel. With the context of the lookup it is that context's channel; without
// one it is the default context's, as upstream.
TEST(TestStealthTRRContext, TheFilterSeesTheContextOfTheLookup)
{
  nsCOMPtr<nsIProtocolProxyService> pps =
      do_GetService(NS_PROTOCOLPROXYSERVICE_CONTRACTID);
  ASSERT_TRUE(pps);
  RefPtr<RecordingFilter> filter = new RecordingFilter();
  ASSERT_EQ(pps->RegisterChannelFilter(filter, 0), NS_OK);

  nsCOMPtr<nsIURI> uri;
  ASSERT_EQ(NS_NewURI(getter_AddRefs(uri),
                      "https://mozilla.cloudflare-dns.com/dns-query"_ns),
            NS_OK);

  auto Lookup = [&](const Maybe<OriginAttributes>& aContext) {
    bool done = false;
    filter->mAsked = false;
    EXPECT_EQ(ProxyConfigLookup::Create(
                  [&done](nsIProxyInfo*, nsresult) { done = true; }, uri, 0,
                  /* aIsTRRServiceChannel */ true, nullptr, Nothing(),
                  aContext),
              NS_OK);
    EXPECT_TRUE(SpinEventLoopUntil("TestStealthTRRContext"_ns,
                                   [&] { return done; }));
    EXPECT_TRUE(filter->mAsked);
  };

  Lookup(ContextOf(7));
  EXPECT_EQ(filter->mUserContextId, 7u);
  Lookup(ContextOf(12));
  EXPECT_EQ(filter->mUserContextId, 12u);
  Lookup(Nothing());
  EXPECT_EQ(filter->mUserContextId, 0u);

  EXPECT_EQ(pps->UnregisterChannelFilter(filter), NS_OK);
}

// Parental controls are declared off by the service itself, so every reader
// (nsHttpHandler, downloads, the DoH heuristics) sees the same value and the OS
// is never asked. The Linux implementation is a stub that already says "off",
// so this passes on the old code there; it is a guard for the contract.
TEST(TestStealthTRRContext, ParentalControlsServiceReportsEverythingOff)
{
  nsCOMPtr<nsIParentalControlsService> pcs =
      do_CreateInstance("@mozilla.org/parental-controls-service;1");
  if (!pcs) {
    GTEST_SKIP() << "no parental controls service in this build";
  }
  bool enabled = true;
  EXPECT_EQ(pcs->GetParentalControlsEnabled(&enabled), NS_OK);
  EXPECT_FALSE(enabled);
  // An implementation without the state answers an error and leaves false.
  bool blocked = false;
  if (NS_SUCCEEDED(pcs->GetBlockFileDownloadsEnabled(&blocked))) {
    EXPECT_FALSE(blocked);
  }
  bool logging = false;
  if (NS_SUCCEEDED(pcs->GetLoggingEnabled(&logging))) {
    EXPECT_FALSE(logging);
  }
}

// ---- the hooks as the Mozilla files call them --------------------------------------------------------------------------

namespace {

// The value of network.trr.stealth.contexts for the length of a test, put back as it was.
class ContextsPrefScope {
 public:
  explicit ContextsPrefScope(const nsACString& aValue) {
    mHad = NS_SUCCEEDED(Preferences::GetCString(kPref, mOld));
    Preferences::SetCString(kPref, aValue);
  }
  ~ContextsPrefScope() {
    if (mHad) {
      Preferences::SetCString(kPref, mOld);
    } else {
      Preferences::ClearUser(kPref);
    }
  }

 private:
  static constexpr const char* kPref = "network.trr.stealth.contexts";
  nsAutoCString mOld;
  bool mHad = false;
};

// What the templates read from a channel of the two classes besides what FakeChannel does: its cancellation, whether it is a
// DoH request, and its load info.
struct FakeHttpChannel : FakeChannel {
  bool mCanceled = false;
  bool mIsTRR = false;
  RefPtr<TRRLoadInfo> mLoadInfo =
      new TRRLoadInfo(nullptr, nsIContentPolicy::TYPE_OTHER);
  nsresult GetCanceled(bool* aCanceled) {
    *aCanceled = mCanceled;
    return NS_OK;
  }
  nsresult GetIsTRRServiceChannel(bool* aIsTRR) {
    *aIsTRR = mIsTRR;
    return NS_OK;
  }
  already_AddRefed<nsILoadInfo> LoadInfo() {
    nsCOMPtr<nsILoadInfo> loadInfo = mLoadInfo.get();
    return loadInfo.forget();
  }
};

already_AddRefed<nsIChannel> NewDoHChannel() {
  nsCOMPtr<nsIURI> uri;
  if (NS_FAILED(NS_NewURI(getter_AddRefs(uri), "https://example.com/dns-query"_ns))) {
    return nullptr;
  }
  nsCOMPtr<nsIChannel> channel;
  if (NS_FAILED(NS_NewChannel(getter_AddRefs(channel), uri,
                              nsContentUtils::GetSystemPrincipal(),
                              nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                              nsIContentPolicy::TYPE_OTHER))) {
    return nullptr;
  }
  return channel.forget();
}

}  // namespace

// TRRServiceChannel::MaybeResolveProxyAndBeginConnect: the lookup that failed ends the request and gives the caller NS_OK,
// which it returns as it does for a lookup that went well; a lookup that went well is left as it is.
TEST(TestStealthTRRContext, AFailedLookupOfAServiceChannelEndsItAndGivesOkToItsCaller)
{
  FakeChannel channel;
  EXPECT_EQ(StealthTRRServiceProxyLookup(&channel, NS_ERROR_FAILURE), NS_OK);
  EXPECT_EQ(channel.mAborted, 1);
  EXPECT_EQ(channel.mAbortStatus, NS_ERROR_PROXY_CONNECTION_REFUSED);
}

TEST(TestStealthTRRContext, ALookupOfAServiceChannelThatWentWellIsLeftAlone)
{
  FakeChannel channel;
  EXPECT_EQ(StealthTRRServiceProxyLookup(&channel, NS_OK), NS_OK);
  EXPECT_EQ(channel.mAborted, 0);
}

// TRRServiceChannel::OnProxyAvailable: the answer, not only the status: an answer with no proxy info is refused, and a
// cancellation is read from the channel.
TEST(TestStealthTRRContext, AnAnswerOfAServiceChannelWithNoProxyInfoEndsIt)
{
  FakeHttpChannel channel;
  EXPECT_TRUE(StealthTRRServiceOnProxyAnswer(&channel, NS_OK, nullptr));
  EXPECT_EQ(channel.mAborted, 1);
  EXPECT_EQ(channel.mAbortStatus, NS_ERROR_PROXY_CONNECTION_REFUSED);
}

TEST(TestStealthTRRContext, ACancelledServiceChannelGoesOnAsUpstream)
{
  FakeHttpChannel channel;
  channel.mCanceled = true;
  EXPECT_FALSE(StealthTRRServiceOnProxyAnswer(&channel, NS_ERROR_FAILURE, nullptr));
  EXPECT_EQ(channel.mAborted, 0);
}

// nsHttpChannel::MaybeResolveProxyAndBeginConnect: a DoH request whose lookup failed is closed and ended; a channel of a
// context with a proxy too; any other channel keeps upstream's failover; a cancelled one goes on.
TEST(TestStealthTRRContext, AFailedLookupOfADoHHttpChannelClosesItsCacheEntryAndEndsIt)
{
  FakeHttpChannel channel;
  channel.mIsTRR = true;
  EXPECT_EQ(StealthChannelProxyLookup(&channel, NS_ERROR_FAILURE), NS_OK);
  EXPECT_EQ(channel.mClosed, 1);
  EXPECT_EQ(channel.mAborted, 1);
  EXPECT_EQ(channel.mAbortStatus, NS_ERROR_PROXY_CONNECTION_REFUSED);
}

TEST(TestStealthTRRContext, AFailedLookupOfAnOrdinaryChannelKeepsUpstreamUnlessItsContextHasAProxy)
{
  ContextsPrefScope list("7"_ns);
  FakeHttpChannel plain;  // the default context, not in the list
  EXPECT_EQ(StealthChannelProxyLookup(&plain, NS_ERROR_FAILURE), NS_ERROR_FAILURE);
  EXPECT_EQ(plain.mAborted, 0);

  FakeHttpChannel proxied;
  ASSERT_EQ(StealthApplyTRRContext(proxied.mLoadInfo, ContextOf(7)), NS_OK);
  EXPECT_EQ(StealthChannelProxyLookup(&proxied, NS_ERROR_FAILURE), NS_OK);
  EXPECT_EQ(proxied.mClosed, 1);
  EXPECT_EQ(proxied.mAborted, 1);
}

TEST(TestStealthTRRContext, ALookupThatWentWellOrWasCancelledIsLeftToUpstream)
{
  FakeHttpChannel channel;
  channel.mIsTRR = true;
  EXPECT_EQ(StealthChannelProxyLookup(&channel, NS_OK), NS_OK);
  EXPECT_EQ(channel.mAborted, 0);
  channel.mCanceled = true;
  EXPECT_EQ(StealthChannelProxyLookup(&channel, NS_ERROR_FAILURE), NS_ERROR_FAILURE);
  EXPECT_EQ(channel.mAborted, 0);
}

// nsHttpChannel::OnProxyAvailable: the same for the answer; the DIRECT answer of a page channel is legitimate (a bypass
// list matched its host), the one of a DoH request is not.
TEST(TestStealthTRRContext, ADirectAnswerEndsADoHHttpChannelAndNotAPageChannel)
{
  ContextsPrefScope list(""_ns);
  FakeHttpChannel doh;
  doh.mIsTRR = true;
  EXPECT_TRUE(StealthChannelOnProxyAnswer(&doh, NS_OK, nullptr));
  EXPECT_EQ(doh.mClosed, 1);
  EXPECT_EQ(doh.mAborted, 1);

  FakeHttpChannel page;
  EXPECT_FALSE(StealthChannelOnProxyAnswer(&page, NS_OK, nullptr));
  EXPECT_FALSE(StealthChannelOnProxyAnswer(&page, NS_ERROR_FAILURE, nullptr));
  EXPECT_EQ(page.mAborted, 0);
}

TEST(TestStealthTRRContext, AFailedAnswerEndsAPageChannelOfAContextWithAProxy)
{
  ContextsPrefScope list("7"_ns);
  FakeHttpChannel page;
  ASSERT_EQ(StealthApplyTRRContext(page.mLoadInfo, ContextOf(7)), NS_OK);
  EXPECT_TRUE(StealthChannelOnProxyAnswer(&page, NS_ERROR_FAILURE, nullptr));
  EXPECT_EQ(page.mClosed, 1);
  EXPECT_EQ(page.mAborted, 1);
}

// TRR::SendHTTPRequest: the channel of the request takes the context of its lookup (the origin suffix of its record); the
// default context leaves it as it is; a channel that cannot take the context ends the request.
TEST(TestStealthTRRContext, TheRequestOfAContextGivesItsChannelTheContext)
{
  nsCOMPtr<nsIChannel> channel = NewDoHChannel();
  ASSERT_TRUE(channel);
  nsresult rv = NS_ERROR_FAILURE;
  EXPECT_FALSE(StealthTRRApplyContext("^userContextId=7"_ns, channel, &rv));
  EXPECT_EQ(rv, NS_OK);
  nsCOMPtr<nsILoadInfo> loadInfo = channel->LoadInfo();
  EXPECT_EQ(loadInfo->GetOriginAttributes().mUserContextId, 7u);
}

TEST(TestStealthTRRContext, TheRequestOfTheDefaultContextLeavesItsChannelAsItIs)
{
  nsCOMPtr<nsIChannel> channel = NewDoHChannel();
  ASSERT_TRUE(channel);
  nsresult rv = NS_ERROR_FAILURE;
  EXPECT_FALSE(StealthTRRApplyContext(""_ns, channel, &rv));
  EXPECT_EQ(rv, NS_OK);
  nsCOMPtr<nsILoadInfo> loadInfo = channel->LoadInfo();
  EXPECT_EQ(loadInfo->GetOriginAttributes().mUserContextId, 0u);
}

TEST(TestStealthTRRContext, AChannelThatCannotTakeTheContextEndsTheRequest)
{
  nsresult rv = NS_OK;
  EXPECT_TRUE(StealthTRRApplyContext("^userContextId=7"_ns, nullptr, &rv));
  EXPECT_EQ(rv, NS_ERROR_UNEXPECTED);
  rv = NS_ERROR_FAILURE;
  EXPECT_FALSE(StealthTRRApplyContext(""_ns, nullptr, &rv));
  EXPECT_EQ(rv, NS_OK);
}

// TRR::SendHTTPRequest: the cached connection info is of the default context and the browser's proxy, so it serves a lookup
// of the default context only, and only behind the pref.
TEST(TestStealthTRRContext, TheCachedConnectionInfoServesOnlyTheDefaultContextBehindThePref)
{
  EXPECT_TRUE(StealthTRRConnInfoUsable(""_ns, true));
  EXPECT_FALSE(StealthTRRConnInfoUsable("^userContextId=7"_ns, true));
  EXPECT_FALSE(StealthTRRConnInfoUsable(""_ns, false));
  EXPECT_FALSE(StealthTRRConnInfoUsable("^userContextId=7"_ns, false));
}

// TRRServiceChannel::BeginConnect: the connection info of a DoH channel carries the context of its load info, so the tunnel
// is not shared between contexts; the default context gets the attributes Mozilla's code passes.
TEST(TestStealthTRRContext, TheConnectionInfoOfAChannelCarriesTheContextOfItsLoadInfo)
{
  nsCOMPtr<nsIChannel> channel = NewDoHChannel();
  ASSERT_TRUE(channel);
  EXPECT_TRUE(StealthTRRConnectionAttributes(channel, OriginAttributes()) == OriginAttributes());
  ASSERT_EQ(StealthApplyTRRContextToChannel(channel, ContextOf(7)), NS_OK);
  EXPECT_EQ(StealthTRRConnectionAttributes(channel, OriginAttributes()).mUserContextId, 7u);

  // The default context keeps what Mozilla passes.
  OriginAttributes upstream;
  upstream.mPrivateBrowsingId = 1;
  nsCOMPtr<nsIChannel> plain = NewDoHChannel();
  ASSERT_TRUE(plain);
  EXPECT_TRUE(StealthTRRConnectionAttributes(plain, upstream) == upstream);
}

// TLSTransportLayer::Init: the TLS over a tunnel takes the context of the transport it runs over; with no transport, or one
// with no context, the attributes Mozilla's code passes.
TEST(TestStealthTRRContext, ATlsOverATunnelTakesTheContextOfItsTransport)
{
  nsCOMPtr<nsISocketTransportService> service =
      do_GetService("@mozilla.org/network/socket-transport-service;1");
  ASSERT_TRUE(service);
  nsCOMPtr<nsISocketTransport> transport;
  ASSERT_EQ(service->CreateTransport(nsTArray<nsCString>(), "a.test"_ns, 443,
                                     nullptr, nullptr,
                                     getter_AddRefs(transport)),
            NS_OK);
  EXPECT_TRUE(StealthTransportContext(transport, OriginAttributes()) == OriginAttributes());
  OriginAttributes attrs;
  attrs.mUserContextId = 7;
  ASSERT_EQ(transport->SetOriginAttributes(attrs), NS_OK);
  EXPECT_EQ(StealthTransportContext(transport, OriginAttributes()).mUserContextId, 7u);

  OriginAttributes upstream;
  upstream.mPrivateBrowsingId = 1;
  EXPECT_TRUE(StealthTransportContext(nullptr, upstream) == upstream);
}

// TRRServiceChannel::ResolveProxy passes itself: the context a channel gives its proxy lookup is the one of its load info,
// Nothing for the default context.
TEST(TestStealthTRRContext, TheContextOfAChannelIsTheContextOfItsLoadInfo)
{
  nsCOMPtr<nsIChannel> channel = NewDoHChannel();
  ASSERT_TRUE(channel);
  EXPECT_TRUE(StealthTRRContextOf(channel).isNothing());
  ASSERT_EQ(StealthApplyTRRContextToChannel(channel, ContextOf(7)), NS_OK);
  Maybe<OriginAttributes> context = StealthTRRContextOf(channel);
  ASSERT_TRUE(context.isSome());
  EXPECT_EQ(context->mUserContextId, 7u);
}

}  // namespace mozilla::net
