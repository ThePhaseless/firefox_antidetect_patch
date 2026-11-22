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

TEST(StealthMouseEventCopy, DuplicateKeepsTheId)
{
  WidgetMouseEvent origin(true, eMouseUp, nullptr);
  origin.mJugglerEventId = 9;
  UniquePtr<WidgetEvent> copy(origin.Duplicate());
  ASSERT_TRUE(copy);
  ASSERT_TRUE(copy->AsMouseEvent());
  EXPECT_EQ(copy->AsMouseEvent()->mJugglerEventId, 9u);
}
