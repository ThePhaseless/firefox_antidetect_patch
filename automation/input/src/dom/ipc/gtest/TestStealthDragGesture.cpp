/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The decision of [B288] (dom/events/StealthDragGesture.h): a drag gesture that
// a Juggler press started continues only with Juggler moves, and a gesture
// that a native press started continues only with native moves. The id of an
// event is not 0 exactly when jugglerSendMouseEvent sent it.

#include "StealthDragGesture.h"

#include "gtest/gtest.h"
#include "mozilla/MouseEvents.h"
#include "mozilla/TouchEvents.h"

using namespace mozilla;

static WidgetMouseEvent StealthMouseEventWithId(EventMessage aMessage, uint32_t aId) {
  WidgetMouseEvent event(true, aMessage, nullptr);
  event.mJugglerEventId = aId;
  return event;
}

TEST(StealthDragGesture, ThePressOfJugglerDecidesWhichMovesContinueTheGesture)
{
  bool fromJuggler = false;
  StealthDragGestureBegin(fromJuggler, StealthMouseEventWithId(eMouseDown, 3));
  EXPECT_TRUE(fromJuggler);

  // A native move during a Juggler press does not count for the gesture.
  EXPECT_TRUE(
      StealthSkipDragGesture(fromJuggler, StealthMouseEventWithId(eMouseMove, 0)));
  // A move that Juggler sent does.
  EXPECT_FALSE(
      StealthSkipDragGesture(fromJuggler, StealthMouseEventWithId(eMouseMove, 4)));
}

TEST(StealthDragGesture, TheNativePressKeepsTheNativeMoves)
{
  bool fromJuggler = true;
  StealthDragGestureBegin(fromJuggler, StealthMouseEventWithId(eMouseDown, 0));
  EXPECT_FALSE(fromJuggler);

  EXPECT_FALSE(
      StealthSkipDragGesture(fromJuggler, StealthMouseEventWithId(eMouseMove, 0)));
  EXPECT_TRUE(
      StealthSkipDragGesture(fromJuggler, StealthMouseEventWithId(eMouseMove, 9)));
}

TEST(StealthDragGesture, AnEventThatIsNotAMouseEventIsNeverSkipped)
{
  WidgetTouchEvent touch(true, eTouchMove, nullptr);
  EXPECT_FALSE(StealthSkipDragGesture(true, touch));
  EXPECT_FALSE(StealthSkipDragGesture(false, touch));
}

TEST(StealthDragGesture, WithoutBeginAJugglerMoveIsSkipped)
{
  // Negative control: the flag of a gesture that never went through
  // StealthDragGestureBegin is the default of the member (false), so a move
  // that Juggler sent does not continue it.
  bool fromJuggler = false;
  EXPECT_TRUE(
      StealthSkipDragGesture(fromJuggler, StealthMouseEventWithId(eMouseMove, 5)));
}
