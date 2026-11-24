/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The id of a Juggler mouse event ([B217]) travels with the event: through the
// IPC message between the processes, and through the copy of the event.

#include "chrome/common/ipc_message.h"
#include "gtest/gtest.h"
#include "ipc/nsGUIEventIPC.h"
#include "mozilla/MouseEvents.h"
#include "mozilla/UniquePtr.h"

using namespace mozilla;

static bool StealthMouseEventRoundTrip(const WidgetMouseEvent& aIn, WidgetMouseEvent* aOut) {
  UniquePtr<IPC::Message> msg(new IPC::Message(MSG_ROUTING_NONE, 0));
  {
    IPC::MessageWriter writer(*msg);
    IPC::ParamTraits<WidgetMouseEvent>::Write(&writer, aIn);
  }
  IPC::MessageReader reader(*msg);
  return IPC::ParamTraits<WidgetMouseEvent>::Read(&reader, aOut);
}

TEST(StealthMouseEventIPC, TheIdSurvivesTheMessage)
{
  WidgetMouseEvent in(true, eMouseMove, nullptr);
  in.mJugglerEventId = 7;
  in.mButton = MouseButton::eSecondary;
  in.mButtons = MouseButtonsFlag::eSecondaryFlag;

  WidgetMouseEvent out(true, eMouseMove, nullptr);
  ASSERT_TRUE(StealthMouseEventRoundTrip(in, &out));
  EXPECT_EQ(out.mJugglerEventId, 7u);
  EXPECT_EQ(out.mClass, eMouseEventClass);
  EXPECT_EQ(out.mMessage, eMouseMove);
  EXPECT_EQ(out.mButton, MouseButton::eSecondary);
  EXPECT_EQ(out.mButtons, MouseButtonsFlag::eSecondaryFlag);
}

TEST(StealthMouseEventIPC, AnEventWithoutAnIdReadsZero)
{
  // Negative control: the id is not invented on the way.
  WidgetMouseEvent in(true, eMouseDown, nullptr);
  WidgetMouseEvent out(true, eMouseDown, nullptr);
  out.mJugglerEventId = 99;
  ASSERT_TRUE(StealthMouseEventRoundTrip(in, &out));
  EXPECT_EQ(out.mJugglerEventId, 0u);
}

TEST(StealthMouseEventIPC, AMessageWithoutTheEventIsRefused)
{
  UniquePtr<IPC::Message> msg(new IPC::Message(MSG_ROUTING_NONE, 0));
  WidgetMouseEvent out(true, eMouseMove, nullptr);
  IPC::MessageReader reader(*msg);
  EXPECT_FALSE(IPC::ParamTraits<WidgetMouseEvent>::Read(&reader, &out));
}

TEST(StealthMouseEventIPC, TheIdIsReadOnlyWhenTheFieldBeforeItWasRead)
{
  // The read is the last link of the && chain: after a failed read of the
  // field before it, nothing is consumed (negative control), and after a
  // successful one it is the next value of the stream that becomes the id.
  UniquePtr<IPC::Message> msg(new IPC::Message(MSG_ROUTING_NONE, 0));
  {
    IPC::MessageWriter writer(*msg);
    IPC::WriteParam(&writer, uint32_t(5));
  }
  WidgetMouseEvent out(true, eMouseMove, nullptr);
  IPC::MessageReader reader(*msg);
  EXPECT_FALSE(IPC::StealthReadJugglerEventId(&reader, &out, false));
  EXPECT_EQ(out.mJugglerEventId, 0u);
  EXPECT_TRUE(IPC::StealthReadJugglerEventId(&reader, &out, true));
  EXPECT_EQ(out.mJugglerEventId, 5u);
}

TEST(StealthMouseEventCopy, DuplicateKeepsTheId)
{
  WidgetMouseEvent origin(true, eMouseUp, nullptr);
  origin.mJugglerEventId = 9;
  UniquePtr<WidgetEvent> copy(origin.Duplicate());
  ASSERT_TRUE(copy);
  ASSERT_TRUE(copy->AsMouseEvent());
  EXPECT_EQ(copy->AsMouseEvent()->mJugglerEventId, 9u);
}

TEST(StealthMouseEventCopy, AssignMouseEventDataKeepsTheId)
{
  WidgetMouseEvent origin(true, eMouseDown, nullptr);
  origin.mJugglerEventId = 9;
  WidgetMouseEvent target(true, eMouseDown, nullptr);
  target.AssignMouseEventData(origin, true);
  EXPECT_EQ(target.mJugglerEventId, 9u);
}

TEST(StealthMouseEventCopy, AFreshEventHasNoId)
{
  // Negative control: the id is 0 until jugglerSendMouseEvent sets it, and a
  // copy of such an event has 0.
  WidgetMouseEvent origin(true, eMouseDown, nullptr);
  EXPECT_EQ(origin.mJugglerEventId, 0u);
  UniquePtr<WidgetEvent> copy(origin.Duplicate());
  ASSERT_TRUE(copy);
  EXPECT_EQ(copy->AsMouseEvent()->mJugglerEventId, 0u);
}
