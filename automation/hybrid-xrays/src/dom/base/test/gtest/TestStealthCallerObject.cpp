/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The branch of Rewrap (js/xpconnect/wrappers/WrapperFactory.cpp) that hands the
// page a caller's object takes no local: StealthNoteCallerObject, an anchor
// where Rewrap has computed its values, decides and records, and the condition
// of the branch, StealthCallerObjectApplies, reads the decision and clears it.
// These tests call the decision, the state and the read with no Realm: the
// decision of one call must not reach the next.

#include "gtest/gtest.h"

namespace mozilla {
bool StealthCallerObjectDecision(bool aOriginHybrid, bool aTargetHybrid,
                                 bool aTargetWantsXrays, bool aTargetIsChrome,
                                 bool aTargetSubsumesOrigin);
void StealthRecordCallerObject(bool aApplies);
bool StealthCallerObjectApplies();
}  // namespace mozilla

TEST(StealthCallerObject, TheDecisionIsTheCallersWorldReadByThePageItSubsumes)
{
  // Applies: the origin is a caller's world, the target is not, is not chrome,
  // subsumes the origin and does not force Xrays.
  EXPECT_TRUE(mozilla::StealthCallerObjectDecision(true, false, false, false, true));
  // Each of the five values, taken away alone, makes it not apply.
  EXPECT_FALSE(mozilla::StealthCallerObjectDecision(false, false, false, false, true));
  EXPECT_FALSE(mozilla::StealthCallerObjectDecision(true, true, false, false, true));
  EXPECT_FALSE(mozilla::StealthCallerObjectDecision(true, false, true, false, true));
  EXPECT_FALSE(mozilla::StealthCallerObjectDecision(true, false, false, true, true));
  EXPECT_FALSE(mozilla::StealthCallerObjectDecision(true, false, false, false, false));
}

TEST(StealthCallerObject, TheSecondDecisionIsNotTheFirstsWhateverTheOrder)
{
  // Opposite inputs, both orders: the read gives the decision just made.
  mozilla::StealthRecordCallerObject(mozilla::StealthCallerObjectDecision(true, false, false, false, true));
  EXPECT_TRUE(mozilla::StealthCallerObjectApplies());
  mozilla::StealthRecordCallerObject(mozilla::StealthCallerObjectDecision(false, false, false, false, true));
  EXPECT_FALSE(mozilla::StealthCallerObjectApplies());

  mozilla::StealthRecordCallerObject(mozilla::StealthCallerObjectDecision(false, false, false, false, true));
  EXPECT_FALSE(mozilla::StealthCallerObjectApplies());
  mozilla::StealthRecordCallerObject(mozilla::StealthCallerObjectDecision(true, false, false, false, true));
  EXPECT_TRUE(mozilla::StealthCallerObjectApplies());
}

TEST(StealthCallerObject, ADecisionIsReadOnceAndAReadWithNoDecisionIsFalse)
{
  mozilla::StealthRecordCallerObject(true);
  EXPECT_TRUE(mozilla::StealthCallerObjectApplies());
  // Consumed: a branch reached with no anchor before it does not take the
  // decision of an earlier call (negative control for the reset).
  EXPECT_FALSE(mozilla::StealthCallerObjectApplies());
  EXPECT_FALSE(mozilla::StealthCallerObjectApplies());
}
