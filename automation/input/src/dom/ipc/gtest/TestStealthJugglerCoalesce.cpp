/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// [B217]: mouse moves that are folded into one carry the id of the LAST one, the
// id that a caller waiting for "my move has landed" holds.

#include "gtest/gtest.h"
#include "mozilla/MouseEvents.h"
#include "mozilla/UniquePtr.h"
#include "mozilla/dom/CoalescedMouseData.h"
#include "mozilla/layers/ScrollableLayerGuid.h"

using namespace mozilla;

TEST(StealthJugglerCoalesce, TheLastIdFoldedInWins)
{
  dom::CoalescedMouseData data;
  layers::ScrollableLayerGuid guid;

  WidgetMouseEvent first(true, eMouseMove, nullptr);
  first.mJugglerEventId = 5;
  WidgetMouseEvent second(true, eMouseMove, nullptr);
  second.mJugglerEventId = 6;

  data.Coalesce(first, guid, 1);
  data.Coalesce(second, guid, 1);

  UniquePtr<WidgetMouseEvent> folded = data.TakeCoalescedEvent();
  ASSERT_TRUE(folded);
  EXPECT_EQ(folded->mJugglerEventId, 6u);
}

TEST(StealthJugglerCoalesce, AnEventAloneKeepsItsId)
{
  // Negative control: the first event of a run is copied whole; only the
  // later ones go through the folding that takes the latest id.
  dom::CoalescedMouseData data;
  layers::ScrollableLayerGuid guid;

  WidgetMouseEvent first(true, eMouseMove, nullptr);
  first.mJugglerEventId = 5;
  data.Coalesce(first, guid, 1);

  UniquePtr<WidgetMouseEvent> folded = data.TakeCoalescedEvent();
  ASSERT_TRUE(folded);
  EXPECT_EQ(folded->mJugglerEventId, 5u);
}

TEST(StealthJugglerCoalesce, ALaterNativeMoveClearsTheId)
{
  // The folded event takes the id of the latest one, 0 included: a native move
  // after a Juggler move must not leave the Juggler id on the folded event.
  dom::CoalescedMouseData data;
  layers::ScrollableLayerGuid guid;

  WidgetMouseEvent first(true, eMouseMove, nullptr);
  first.mJugglerEventId = 5;
  WidgetMouseEvent second(true, eMouseMove, nullptr);

  data.Coalesce(first, guid, 1);
  data.Coalesce(second, guid, 1);

  UniquePtr<WidgetMouseEvent> folded = data.TakeCoalescedEvent();
  ASSERT_TRUE(folded);
  EXPECT_EQ(folded->mJugglerEventId, 0u);
}
