/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The navigation line of the engine, as Juggler needs it:
//  - TestStealthLinkClickAfter: a planned navigation (a link click, a form
//    submission) is announced once before it and once after, whichever of Run
//    and Cancel ends it first (the pure state, and the two wrapped returns).
//  - TestStealthLoadInfo: a LoadInfo carries the identifier of its load, and
//    every copy of it (Clone, CloneWithNewSecFlags, CloneForNewRequest: a
//    redirect, a separate request) carries it too.
//  - TestStealthDocShellDefaults: a freshly made docshell has the two
//    attributes Juggler sets (file input interception, CSP bypass) off.

#include <string.h>

#include "StealthNavigation.h"
#include "gtest/gtest.h"
#include "mozilla/LoadInfo.h"
#include "mozilla/RefPtr.h"
#include "mozilla/Services.h"
#include "mozilla/dom/BrowsingContext.h"
#include "nsCOMPtr.h"
#include "nsContentUtils.h"
#include "nsDocShell.h"
#include "nsIChannel.h"
#include "nsIContentPolicy.h"
#include "nsILoadInfo.h"
#include "nsIObserver.h"
#include "nsIObserverService.h"
#include "nsIURI.h"
#include "nsNetUtil.h"
#include "nsString.h"

using namespace mozilla;
using namespace mozilla::dom;
using namespace mozilla::net;

namespace {

// Counts the notifications of one topic while it is started.
class TopicCounter final : public nsIObserver {
 public:
  NS_DECL_ISUPPORTS

  explicit TopicCounter(const char* aTopic) : mTopic(aTopic) {}

  void Start() {
    nsCOMPtr<nsIObserverService> observers =
        mozilla::services::GetObserverService();
    ASSERT_TRUE(observers);
    ASSERT_EQ(observers->AddObserver(this, mTopic, false), NS_OK);
  }

  void Stop() {
    nsCOMPtr<nsIObserverService> observers =
        mozilla::services::GetObserverService();
    if (observers) {
      observers->RemoveObserver(this, mTopic);
    }
  }

  int Count() const { return mCount; }

  NS_IMETHOD Observe(nsISupports*, const char* aTopic,
                     const char16_t*) override {
    if (!strcmp(aTopic, mTopic)) {
      ++mCount;
    }
    return NS_OK;
  }

 private:
  ~TopicCounter() = default;

  const char* const mTopic;
  int mCount = 0;
};
NS_IMPL_ISUPPORTS(TopicCounter, nsIObserver)

}  // namespace

// Done sends the "after" once, whichever of Run and Cancel gets there first.
TEST(TestStealthLinkClickAfter, DoneSendsTheAfterOnce)
{
  RefPtr<TopicCounter> after = new TopicCounter("juggler-link-click-sync");
  after->Start();
  StealthLinkClickAfter state;
  state.Done(nullptr);
  state.Done(nullptr);
  EXPECT_EQ(after->Count(), 1);
  after->Stop();
}

// While Run is inside OnLinkClickSync it says "after" itself once the
// navigation has started, so a Cancel then (a form that stops its own
// docshell's network) stays silent; the one "after" comes from Run.
TEST(TestStealthLinkClickAfter, CancelledIsSilentWhileRunning)
{
  RefPtr<TopicCounter> after = new TopicCounter("juggler-link-click-sync");
  after->Start();
  StealthLinkClickAfter state;
  state.StealthSetRunning(true);
  state.StealthCancelled(nullptr);
  EXPECT_EQ(after->Count(), 0);
  state.StealthSetRunning(false);
  state.Done(nullptr);
  EXPECT_EQ(after->Count(), 1);
  after->Stop();
}

// A plan cancelled before it ever ran (another submission replaces it) still
// gets its "after", once, so a client waiting on the pair is not left waiting.
TEST(TestStealthLinkClickAfter, CancelledSendsWhenNotRunning)
{
  RefPtr<TopicCounter> after = new TopicCounter("juggler-link-click-sync");
  after->Start();
  StealthLinkClickAfter state;
  state.StealthCancelled(nullptr);
  EXPECT_EQ(after->Count(), 1);
  state.Done(nullptr);
  EXPECT_EQ(after->Count(), 1);
  after->Stop();
}

namespace {

already_AddRefed<nsILoadInfo> NewLoadInfo(nsCOMPtr<nsIChannel>& aChannel) {
  nsCOMPtr<nsIURI> uri;
  EXPECT_EQ(NS_NewURI(getter_AddRefs(uri), "https://example.com/"_ns), NS_OK);
  EXPECT_EQ(
      NS_NewChannel(getter_AddRefs(aChannel), uri,
                    nsContentUtils::GetSystemPrincipal(),
                    nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                    nsIContentPolicy::TYPE_OTHER),
      NS_OK);
  nsCOMPtr<nsILoadInfo> loadInfo = aChannel->LoadInfo();
  return loadInfo.forget();
}

}  // namespace

// A LoadInfo that never got an identifier reports 0; with one, it reports it,
// and every copy of it reports the same.
TEST(TestStealthLoadInfo, EveryCopyOfALoadInfoKeepsItsLoadIdentifier)
{
  nsCOMPtr<nsIChannel> channel;
  nsCOMPtr<nsILoadInfo> info = NewLoadInfo(channel);
  ASSERT_TRUE(info);
  EXPECT_EQ(info->GetJugglerLoadIdentifier(), 0u);

  ASSERT_EQ(info->SetJugglerLoadIdentifier(7), NS_OK);
  EXPECT_EQ(info->GetJugglerLoadIdentifier(), 7u);

  LoadInfo* loadInfo = static_cast<LoadInfo*>(info.get());
  nsCOMPtr<nsILoadInfo> clone = loadInfo->Clone();
  ASSERT_TRUE(clone);
  EXPECT_EQ(clone->GetJugglerLoadIdentifier(), 7u);

  nsCOMPtr<nsILoadInfo> withFlags = loadInfo->CloneWithNewSecFlags(
      nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL);
  ASSERT_TRUE(withFlags);
  EXPECT_EQ(withFlags->GetJugglerLoadIdentifier(), 7u);

  nsCOMPtr<nsILoadInfo> forNewRequest = loadInfo->CloneForNewRequest();
  ASSERT_TRUE(forNewRequest);
  EXPECT_EQ(forNewRequest->GetJugglerLoadIdentifier(), 7u);

  // The copy is its own object: the original's identifier moving on does not
  // reach it.
  ASSERT_EQ(info->SetJugglerLoadIdentifier(9), NS_OK);
  EXPECT_EQ(clone->GetJugglerLoadIdentifier(), 7u);
}

TEST(TestStealthLoadInfo, ACopyOfALoadInfoWithoutOneReportsZero)
{
  nsCOMPtr<nsIChannel> channel;
  nsCOMPtr<nsILoadInfo> info = NewLoadInfo(channel);
  ASSERT_TRUE(info);
  nsCOMPtr<nsILoadInfo> clone = static_cast<LoadInfo*>(info.get())->Clone();
  ASSERT_TRUE(clone);
  EXPECT_EQ(clone->GetJugglerLoadIdentifier(), 0u);
}

// A docshell as nsDocShell::Create makes it. The docshell is not initialised
// and is left to the cycle collector at shutdown.
TEST(TestStealthDocShellDefaults, AFreshDocShellHasBothAttributesOff)
{
  RefPtr<BrowsingContext> browsingContext =
      BrowsingContext::CreateIndependent(BrowsingContext::Type::Content, true);
  ASSERT_TRUE(browsingContext);
  RefPtr<nsDocShell> docShell = nsDocShell::Create(browsingContext);
  ASSERT_TRUE(docShell);

  bool enabled = true;
  ASSERT_EQ(docShell->GetFileInputInterceptionEnabled(&enabled), NS_OK);
  EXPECT_FALSE(enabled);
  enabled = true;
  ASSERT_EQ(docShell->GetBypassCSPEnabled(&enabled), NS_OK);
  EXPECT_FALSE(enabled);

  // What is set is read back, each on its own.
  ASSERT_EQ(docShell->SetFileInputInterceptionEnabled(true), NS_OK);
  ASSERT_EQ(docShell->GetFileInputInterceptionEnabled(&enabled), NS_OK);
  EXPECT_TRUE(enabled);
  ASSERT_EQ(docShell->GetBypassCSPEnabled(&enabled), NS_OK);
  EXPECT_FALSE(enabled);
  ASSERT_EQ(docShell->SetBypassCSPEnabled(true), NS_OK);
  ASSERT_EQ(docShell->GetBypassCSPEnabled(&enabled), NS_OK);
  EXPECT_TRUE(enabled);
}
