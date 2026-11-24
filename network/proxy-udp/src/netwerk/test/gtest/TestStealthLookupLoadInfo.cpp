/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The load info of the document of a PeerConnection travels to the proxy lookup made for it without a parameter of
// Mozilla's signatures (StealthDocumentChannel.h): the caller sets it, the first statement of ProxyConfigLookup::Create
// takes it, the socket process sends it in a message of its own right before the constructor of PProxyConfigLookup and the
// parent takes it again at that constructor. These tests are that course, a step each, with the controls: without its
// message a constructor has no load info, and a lookup never reads the load info of another.

#include "gtest/gtest.h"
#include "mozilla/BasePrincipal.h"
#include "mozilla/Maybe.h"
#include "mozilla/OriginAttributes.h"
#include "mozilla/RefPtr.h"
#include "mozilla/Services.h"
#include "mozilla/SpinEventLoopUntil.h"
#include "mozilla/ipc/BackgroundUtils.h"
#include "mozilla/net/NeckoChannelParams.h"
#include "mozilla/net/ProxyConfigLookup.h"
#include "mozilla/net/StealthDocumentChannel.h"
#include "nsCOMPtr.h"
#include "nsContentUtils.h"
#include "nsIChannel.h"
#include "nsIContentPolicy.h"
#include "nsILoadInfo.h"
#include "nsIObserver.h"
#include "nsIObserverService.h"
#include "nsIPrincipal.h"
#include "nsIProxyInfo.h"
#include "nsIStreamListener.h"
#include "nsIURI.h"
#include "nsNetUtil.h"
#include "nsString.h"
#include "nsTArray.h"

namespace mozilla::net {

namespace {

// The load info args of a document of the browser context aUserContextId.
Maybe<LoadInfoArgs> ArgsOfTheDocument(uint32_t aUserContextId) {
  nsCOMPtr<nsIURI> uri;
  EXPECT_EQ(NS_NewURI(getter_AddRefs(uri), "https://example.net/"_ns), NS_OK);
  OriginAttributes attrs;
  attrs.mUserContextId = aUserContextId;
  RefPtr<BasePrincipal> principal =
      BasePrincipal::CreateContentPrincipal(uri, attrs);
  nsCOMPtr<nsIChannel> channel;
  EXPECT_EQ(NS_NewChannel(getter_AddRefs(channel), uri, principal.get(),
                          nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                          nsIContentPolicy::TYPE_OTHER),
            NS_OK);
  LoadInfoArgs args;
  nsCOMPtr<nsILoadInfo> loadInfo = channel->LoadInfo();
  EXPECT_EQ(ipc::LoadInfoToLoadInfoArgs(loadInfo, &args), NS_OK);
  return Some(args);
}

Maybe<LoadInfoArgs> ArgsOrNothing(uint32_t aUserContextId) {
  if (aUserContextId == 0) {
    return Nothing();
  }
  return ArgsOfTheDocument(aUserContextId);
}

// The userContextId of the load info of the lookup being made (0: none).
uint32_t ContextOfTheActiveLoadInfo() {
  Maybe<LoadInfoArgs> active = StealthActiveLookupLoadInfo();
  return active.isSome() ? active->originAttributes().mUserContextId : 0;
}

// What the parent does for one constructor of PProxyConfigLookup, on the messages it has received: a message parks the
// load info in the slot of the socket process actor (SocketProcessParent::RecvStealthProxyLookupLoadInfo), the constructor
// takes it (the first statement of RecvPProxyConfigLookupConstructor) and the lookup is made (ProxyConfigLookup::Create,
// whose first statement makes the taken load info the one of the lookup).
struct ParentSideOfTheLookup {
  int mActor = 0;  // only its address is used: the SocketProcessParent
  void OnMessage(const Maybe<LoadInfoArgs>& aLoadInfo) {
    StealthParkLookupLoadInfo(&mActor, aLoadInfo);
  }
  // The context of the load info the lookup of the constructor is made with (0: none).
  uint32_t OnConstructor() {
    StealthTakeParkedLookupLoadInfo(&mActor);
    StealthEnterLookupLoadInfo();
    return ContextOfTheActiveLoadInfo();
  }
};

// The socket process side, as ProxyConfigLookupChild::Create makes it: the first statement of Create, then the message,
// then the constructor. The wire is what the two sides share, in the order of sending.
struct WireEvent {
  bool mIsConstructor;
  Maybe<LoadInfoArgs> mLoadInfo;
};

struct FakeSocketProcessChild {
  nsTArray<WireEvent>* mWire;
  bool SendStealthProxyLookupLoadInfo(const Maybe<LoadInfoArgs>& aLoadInfo) {
    mWire->AppendElement(WireEvent{false, aLoadInfo});
    return true;
  }
  void SendPProxyConfigLookupConstructor() {
    mWire->AppendElement(WireEvent{true, Nothing()});
  }
};

// One lookup made in the socket process; aMessage false is a lookup whose message never reaches the parent (the control).
void LookupInTheSocketProcess(FakeSocketProcessChild* aChild,
                              const Maybe<LoadInfoArgs>& aLoadInfo,
                              bool aMessage) {
  StealthSetLookupLoadInfo(aLoadInfo);  // the caller: the lookup of a PeerConnection's UDP
  StealthEnterLookupLoadInfo();         // the first statement of Create
  if (aMessage) {
    StealthSendLookupLoadInfo(aChild);  // right before the constructor
  }
  aChild->SendPProxyConfigLookupConstructor();
}

// The parent, the events in the order they arrive: the wire of the channel is a queue (ipc/glue/MessageChannel.cpp:
// OnMessageReceivedFromLink inserts each message at the back of mPending and posts a task for it; the tasks run in the
// order they were posted). The result is the context of the load info each constructor made its lookup with.
nsTArray<uint32_t> ContextsOfTheLookupsOfTheParent(
    ParentSideOfTheLookup& aParent, const nsTArray<WireEvent>& aWire) {
  nsTArray<uint32_t> made;
  for (const WireEvent& event : aWire) {
    if (event.mIsConstructor) {
      made.AppendElement(aParent.OnConstructor());
    } else {
      aParent.OnMessage(event.mLoadInfo);
    }
  }
  return made;
}

}  // namespace

// A load info is the one of the lookup it was set for: the next Create, which nobody set one for, has none. (A pending
// load info that stayed would make the lookup of another document leave by this one's proxy.)
TEST(TestStealthLookupLoadInfo, TheLoadInfoOfALookupIsNotTheNextOnes)
{
  StealthSetLookupLoadInfo(ArgsOfTheDocument(7));
  StealthEnterLookupLoadInfo();
  EXPECT_EQ(ContextOfTheActiveLoadInfo(), 7u);
  EXPECT_TRUE(StealthActiveLookupLoadInfo().isSome());

  StealthEnterLookupLoadInfo();
  EXPECT_TRUE(StealthActiveLookupLoadInfo().isNothing());
  EXPECT_EQ(ContextOfTheActiveLoadInfo(), 0u);
}

// Where Create builds the stand-in channel: right after upstream made it with the system principal, the channel of the
// document when the lookup has its load info, upstream's channel (kept, the very same object) when it has none. The proxy
// filters read the origin attributes of the channel.
TEST(TestStealthLookupLoadInfo, TheStandInChannelIsMadeFromTheLoadInfoOfTheLookup)
{
  nsCOMPtr<nsIURI> uri;
  ASSERT_EQ(NS_NewURI(getter_AddRefs(uri), "https://stun.invalid/"_ns), NS_OK);
  nsCOMPtr<nsIChannel> channel;
  ASSERT_EQ(NS_NewChannel(getter_AddRefs(channel), uri,
                          nsContentUtils::GetSystemPrincipal(),
                          nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                          nsIContentPolicy::TYPE_OTHER),
            NS_OK);

  // The control: no load info, upstream's channel stays.
  StealthSetLookupLoadInfo(Nothing());
  StealthEnterLookupLoadInfo();
  nsCOMPtr<nsIChannel> upstream = channel;
  nsresult rv = NS_OK;
  EXPECT_FALSE(StealthSwapLookupChannel(uri, 0, channel, &rv));
  EXPECT_EQ(rv, NS_OK);
  EXPECT_EQ(channel.get(), upstream.get());
  nsCOMPtr<nsILoadInfo> upstreamInfo = channel->LoadInfo();
  EXPECT_EQ(upstreamInfo->GetOriginAttributes().mUserContextId, 0u);
  EXPECT_EQ(upstreamInfo->InternalContentPolicyType(),
            nsIContentPolicy::TYPE_OTHER);

  // The load info of a document of the context 7: the channel of the document, with the flags of the lookup.
  StealthSetLookupLoadInfo(ArgsOfTheDocument(7));
  StealthEnterLookupLoadInfo();
  EXPECT_FALSE(StealthSwapLookupChannel(uri, 0, channel, &rv));
  EXPECT_EQ(rv, NS_OK);
  EXPECT_NE(channel.get(), upstream.get());
  nsCOMPtr<nsILoadInfo> info = channel->LoadInfo();
  EXPECT_EQ(info->GetOriginAttributes().mUserContextId, 7u);
  EXPECT_EQ(info->InternalContentPolicyType(),
            nsIContentPolicy::TYPE_PROXIED_WEBRTC_MEDIA);
}

// Between the message of the socket process and its constructor the parent may make a lookup of its own (the one of a
// PeerConnection when there is no socket process, TRRServiceBase): it never reads the load info parked for the constructor.
// The constructor takes it, once; a constructor of a socket process that was started again (another actor) gets none.
TEST(TestStealthLookupLoadInfo, ALookupBetweenTheMessageAndTheConstructorNeverReadsItsLoadInfo)
{
  ParentSideOfTheLookup actor;
  ParentSideOfTheLookup restarted;

  actor.OnMessage(ArgsOfTheDocument(7));
  // The lookup of the parent in between: no load info.
  StealthEnterLookupLoadInfo();
  EXPECT_EQ(ContextOfTheActiveLoadInfo(), 0u);
  // The constructor: the load info of its message.
  EXPECT_EQ(actor.OnConstructor(), 7u);
  // Taken: a constructor with no message in front of it has none (the control: the same take, nothing parked).
  EXPECT_EQ(actor.OnConstructor(), 0u);
  // Another actor takes nothing of this one's.
  actor.OnMessage(ArgsOfTheDocument(12));
  EXPECT_EQ(restarted.OnConstructor(), 0u);
}

// The messages and the constructors of one channel arrive in the order they were sent, and each constructor has its
// message right in front of it: so each lookup of the parent has the load info its caller in the socket process set, the
// absence of one included (a message is sent for it too), and never the one of the lookup before.
TEST(TestStealthLookupLoadInfo, EachConstructorTakesTheMessageSentRightBeforeIt)
{
  nsTArray<WireEvent> wire;
  FakeSocketProcessChild child{&wire};
  LookupInTheSocketProcess(&child, ArgsOrNothing(7), true);
  LookupInTheSocketProcess(&child, ArgsOrNothing(0), true);
  LookupInTheSocketProcess(&child, ArgsOrNothing(12), true);
  // A message and a constructor each, and nothing between a message and its constructor.
  ASSERT_EQ(wire.Length(), 6u);
  for (size_t i = 0; i < wire.Length(); ++i) {
    EXPECT_EQ(wire[i].mIsConstructor, i % 2 == 1);
  }

  ParentSideOfTheLookup actor;
  nsTArray<uint32_t> made = ContextsOfTheLookupsOfTheParent(actor, wire);
  ASSERT_EQ(made.Length(), 3u);
  EXPECT_EQ(made[0], 7u);
  EXPECT_EQ(made[1], 0u);
  EXPECT_EQ(made[2], 12u);
}

// The control: the same lookups with no message in front of the second constructor. Without our message the load info is
// absent: the lookup has none, not the one of the lookup before.
TEST(TestStealthLookupLoadInfo, WithoutItsMessageAConstructorHasNoLoadInfo)
{
  nsTArray<WireEvent> wire;
  FakeSocketProcessChild child{&wire};
  LookupInTheSocketProcess(&child, ArgsOrNothing(7), true);
  LookupInTheSocketProcess(&child, ArgsOrNothing(12), false);
  LookupInTheSocketProcess(&child, ArgsOrNothing(9), true);
  ASSERT_EQ(wire.Length(), 5u);

  ParentSideOfTheLookup actor;
  nsTArray<uint32_t> made = ContextsOfTheLookupsOfTheParent(actor, wire);
  ASSERT_EQ(made.Length(), 3u);
  EXPECT_EQ(made[0], 7u);
  EXPECT_EQ(made[1], 0u);
  EXPECT_EQ(made[2], 9u);
}


namespace {

// "http-on-opening-request" is notified by the AsyncOpen of an HTTP channel: the channels it names are the ones that were
// opened.
class OpeningObserver final : public nsIObserver {
 public:
  NS_DECL_ISUPPORTS
  NS_IMETHOD Observe(nsISupports* aSubject, const char* aTopic,
                     const char16_t* aData) override {
    if (nsCOMPtr<nsIChannel> channel = do_QueryInterface(aSubject)) {
      mOpened.AppendElement(channel);
    }
    return NS_OK;
  }
  bool Saw(nsIChannel* aChannel) const {
    for (const nsCOMPtr<nsIChannel>& channel : mOpened) {
      if (channel == aChannel) {
        return true;
      }
    }
    return false;
  }
  nsTArray<nsCOMPtr<nsIChannel>> mOpened;

 private:
  ~OpeningObserver() = default;
};
NS_IMPL_ISUPPORTS(OpeningObserver, nsIObserver)

class NullListener final : public nsIStreamListener {
 public:
  NS_DECL_ISUPPORTS
  NS_DECL_NSIREQUESTOBSERVER
  NS_DECL_NSISTREAMLISTENER
 private:
  ~NullListener() = default;
};
NS_IMPL_ISUPPORTS(NullListener, nsIStreamListener, nsIRequestObserver)
NS_IMETHODIMP NullListener::OnStartRequest(nsIRequest*) { return NS_OK; }
NS_IMETHODIMP NullListener::OnStopRequest(nsIRequest*, nsresult) {
  return NS_OK;
}
NS_IMETHODIMP NullListener::OnDataAvailable(nsIRequest*, nsIInputStream*,
                                            uint64_t, uint32_t) {
  return NS_OK;
}

constexpr const char* kOpeningTopic = "http-on-opening-request";

// The swap the two lookups make, as the lookups call it (flags 0: a lookup of a document with no resolve flags).
bool TheSwap(nsIURI* aURI, const LoadInfoArgs& aArgs,
             nsCOMPtr<nsIChannel>& aChannel, nsresult* aRv) {
  return StealthSwapChannelOfLoadInfo(aURI, 0, aArgs, aChannel, aRv);
}

// The control: the same swap, written so that it opens the channel it drops before it drops it.
bool ASwapThatOpensTheDroppedChannel(nsIURI* aURI, const LoadInfoArgs& aArgs,
                                     nsCOMPtr<nsIChannel>& aChannel,
                                     nsresult* aRv) {
  RefPtr<NullListener> listener = new NullListener();
  EXPECT_EQ(aChannel->AsyncOpen(listener), NS_OK);
  return StealthSwapChannelOfLoadInfo(aURI, 0, aArgs, aChannel, aRv);
}

// Makes upstream's channel (the system principal, as ProxyConfigLookup::DoProxyResolve and WebrtcTCPSocket::
// DoProxyConfigLookup make it), swaps it with aSwap for the channel of a document's load info, and answers whether the dropped
// one was opened: an "http-on-opening-request" for it, or a request that is pending.
bool TheDroppedChannelWasOpened(bool (*aSwap)(nsIURI*, const LoadInfoArgs&,
                                              nsCOMPtr<nsIChannel>&,
                                              nsresult*)) {
  nsCOMPtr<nsIObserverService> observers = services::GetObserverService();
  EXPECT_TRUE(observers);
  RefPtr<OpeningObserver> observer = new OpeningObserver();
  EXPECT_EQ(observers->AddObserver(observer, kOpeningTopic, false), NS_OK);

  nsCOMPtr<nsIURI> uri;
  EXPECT_EQ(NS_NewURI(getter_AddRefs(uri), "https://stun.invalid/"_ns), NS_OK);
  nsCOMPtr<nsIChannel> upstream;
  EXPECT_EQ(NS_NewChannel(getter_AddRefs(upstream), uri,
                          nsContentUtils::GetSystemPrincipal(),
                          nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                          nsIContentPolicy::TYPE_OTHER),
            NS_OK);
  Maybe<LoadInfoArgs> args = ArgsOfTheDocument(7);
  EXPECT_TRUE(args.isSome());

  nsCOMPtr<nsIChannel> channel = upstream;
  nsresult rv = NS_OK;
  EXPECT_FALSE(aSwap(uri, args.ref(), channel, &rv));
  EXPECT_NE(channel.get(), upstream.get());

  bool pending = false;
  EXPECT_EQ(upstream->IsPending(&pending), NS_OK);
  const bool opened = observer->Saw(upstream) || pending;
  if (opened) {
    (void)upstream->Cancel(NS_BINDING_ABORTED);
  }
  EXPECT_EQ(observers->RemoveObserver(observer, kOpeningTopic), NS_OK);
  return opened;
}

}  // namespace

// The channel upstream makes for the proxy lookup is dropped when the lookup has a load info (the swap of ProxyConfigLookup and
// of WebrtcTCPSocket is this one function). It is acceptable only because it is a stand-in nobody opens: not before it is
// dropped, not by the swap. The control is the same test on a swap that opens the dropped channel: it is seen opened, so the
// answer of this test is not "never" for any swap.
TEST(TestStealthLookupLoadInfo, TheChannelTheSwapDropsIsNeverOpened)
{
  EXPECT_FALSE(TheDroppedChannelWasOpened(TheSwap));
  EXPECT_TRUE(TheDroppedChannelWasOpened(ASwapThatOpensTheDroppedChannel));
}

// The whole lookup, as ProxyConfigLookup::Create runs it with a load info: no channel is opened, the stand-in or any other.
TEST(TestStealthLookupLoadInfo, ALookupWithALoadInfoOpensNoChannel)
{
  nsCOMPtr<nsIObserverService> observers = services::GetObserverService();
  ASSERT_TRUE(observers);
  RefPtr<OpeningObserver> observer = new OpeningObserver();
  ASSERT_EQ(observers->AddObserver(observer, kOpeningTopic, false), NS_OK);
  nsCOMPtr<nsIURI> uri;
  ASSERT_EQ(NS_NewURI(getter_AddRefs(uri), "https://stun.invalid/"_ns), NS_OK);

  bool done = false;
  StealthSetLookupLoadInfo(ArgsOfTheDocument(7));
  EXPECT_EQ(ProxyConfigLookup::Create(
                [&done](nsIProxyInfo*, nsresult) { done = true; }, uri, 0,
                /* aIsTRRServiceChannel */ false, nullptr),
            NS_OK);
  EXPECT_TRUE(SpinEventLoopUntil("TestStealthLookupLoadInfo"_ns,
                                 [&] { return done; }));
  EXPECT_EQ(observer->mOpened.Length(), 0u);
  EXPECT_EQ(observers->RemoveObserver(observer, kOpeningTopic), NS_OK);
}

}  // namespace mozilla::net
