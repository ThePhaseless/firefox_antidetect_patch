/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// [B217]: the renderer acks a Juggler mouse event once, after handling it, with
// "<type> <id>" on juggler-mouse-event-hit-renderer. The object of
// layout/base/StealthJugglerAck.h is the first local of PresShell::HandleEvent,
// so its destructor runs when the function returns.

#include "StealthJugglerAck.h"

#include "gtest/gtest.h"
#include "mozilla/MouseEvents.h"
#include "mozilla/RefPtr.h"
#include "mozilla/Services.h"
#include "nsCOMPtr.h"
#include "nsIObserver.h"
#include "nsIObserverService.h"
#include "nsString.h"
#include "nsTArray.h"

using namespace mozilla;

namespace {

constexpr const char* kStealthAckTopic = "juggler-mouse-event-hit-renderer";

class StealthAckObserver final : public nsIObserver {
 public:
  NS_DECL_ISUPPORTS

  NS_IMETHOD Observe(nsISupports*, const char* aTopic,
                     const char16_t* aData) override {
    if (!strcmp(aTopic, kStealthAckTopic)) {
      mNotifications.AppendElement(NS_ConvertUTF16toUTF8(aData));
    }
    return NS_OK;
  }

  nsTArray<nsCString> mNotifications;

 private:
  ~StealthAckObserver() = default;
};

NS_IMPL_ISUPPORTS(StealthAckObserver, nsIObserver)

class StealthScopedAckObserver {
 public:
  StealthScopedAckObserver() : mObserver(new StealthAckObserver()) {
    nsCOMPtr<nsIObserverService> os = services::GetObserverService();
    if (os) {
      os->AddObserver(mObserver, kStealthAckTopic, false);
    }
  }
  ~StealthScopedAckObserver() {
    nsCOMPtr<nsIObserverService> os = services::GetObserverService();
    if (os) {
      os->RemoveObserver(mObserver, kStealthAckTopic);
    }
  }
  StealthAckObserver* operator->() { return mObserver; }

 private:
  RefPtr<StealthAckObserver> mObserver;
};

}  // namespace

TEST(StealthJugglerMouseAck, AnEventWithAnIdIsAckedOnceWhenTheScopeEnds)
{
  StealthScopedAckObserver observer;
  WidgetMouseEvent event(true, eMouseDown, nullptr);
  event.mJugglerEventId = 7;
  {
    StealthJugglerMouseAck ack(&event);
    EXPECT_EQ(observer->mNotifications.Length(), 0u);
  }
  ASSERT_EQ(observer->mNotifications.Length(), 1u);
  EXPECT_TRUE(observer->mNotifications[0].EqualsLiteral("mousedown 7"));
  // The id is cleared, so a nested handler of the same event stays quiet.
  EXPECT_EQ(event.mJugglerEventId, 0u);
}

TEST(StealthJugglerMouseAck, TheTypeFollowsTheMessage)
{
  StealthScopedAckObserver observer;
  const EventMessage messages[] = {eMouseMove, eMouseUp, eContextMenu};
  for (EventMessage message : messages) {
    WidgetMouseEvent event(false, message, nullptr);
    event.mJugglerEventId = 1;
    { StealthJugglerMouseAck ack(&event); }
  }
  ASSERT_EQ(observer->mNotifications.Length(), 3u);
  EXPECT_TRUE(observer->mNotifications[0].EqualsLiteral("mousemove 1"));
  EXPECT_TRUE(observer->mNotifications[1].EqualsLiteral("mouseup 1"));
  EXPECT_TRUE(observer->mNotifications[2].EqualsLiteral("contextmenu 1"));
}

TEST(StealthJugglerMouseAck, AnEventWithoutAnIdIsNotAcked)
{
  // Negative control: a native event has no id and nobody is told.
  StealthScopedAckObserver observer;
  WidgetMouseEvent event(true, eMouseDown, nullptr);
  { StealthJugglerMouseAck ack(&event); }
  EXPECT_EQ(observer->mNotifications.Length(), 0u);
}

TEST(StealthJugglerMouseAck, AnIdThatAnotherHandlerTookIsNotAckedAgain)
{
  StealthScopedAckObserver observer;
  WidgetMouseEvent event(true, eMouseMove, nullptr);
  event.mJugglerEventId = 3;
  {
    StealthJugglerMouseAck ack(&event);
    event.mJugglerEventId = 0;
  }
  EXPECT_EQ(observer->mNotifications.Length(), 0u);
}

TEST(StealthJugglerMouseAck, AMessageWithoutAnAckTypeIsNotAcked)
{
  StealthScopedAckObserver observer;
  WidgetMouseEvent event(true, eMouseEnterIntoWidget, nullptr);
  event.mJugglerEventId = 4;
  { StealthJugglerMouseAck ack(&event); }
  EXPECT_EQ(observer->mNotifications.Length(), 0u);
}
