/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The branch of Rewrap (js/xpconnect/wrappers/WrapperFactory.cpp) that hands the
// page a caller's object takes no local: StealthNoteCallerObject, an anchor
// where Rewrap has computed its values, decides and records. The web-object
// case steps aside while a decision waits (StealthNotCallerObject, which only
// looks), and the regular case at the end of the chain takes it
// (StealthCallerObjectApplies reads the decision and clears it). These tests
// call the decision, the state, the look and the read with no Realm: the
// decision of one call must not reach the next.

#include "gtest/gtest.h"

namespace mozilla {
bool StealthCallerObjectDecision(bool aOriginHybrid, bool aTargetHybrid,
                                 bool aTargetWantsXrays, bool aTargetIsChrome,
                                 bool aTargetSubsumesOrigin);
void StealthRecordCallerObject(bool aApplies);
bool StealthNotCallerObject(bool aMozillaCondition);
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

TEST(StealthCallerObject, TheWebObjectCaseStepsAsideForAWaitingDecisionWithoutTakingIt)
{
  // No decision waiting: the term is Mozilla's, whatever it is.
  mozilla::StealthRecordCallerObject(false);
  EXPECT_TRUE(mozilla::StealthNotCallerObject(true));
  EXPECT_FALSE(mozilla::StealthNotCallerObject(false));

  // A decision waiting: the web-object case does not apply, whatever Mozilla's term says (negative
  // control: with the look gone from the case, the page would be handed a plain transparent wrapper).
  mozilla::StealthRecordCallerObject(true);
  EXPECT_FALSE(mozilla::StealthNotCallerObject(true));
  EXPECT_FALSE(mozilla::StealthNotCallerObject(false));
  // The look took nothing: the regular case that follows still finds the decision, once.
  EXPECT_TRUE(mozilla::StealthCallerObjectApplies());
  EXPECT_FALSE(mozilla::StealthCallerObjectApplies());
  // Taken: the next look is Mozilla's term again.
  EXPECT_TRUE(mozilla::StealthNotCallerObject(true));
}

TEST(StealthCallerObject, AnObjectThatIsNotTheCallersTakesMozillasBranchUnchanged)
{
  // Each of the five values, taken away alone, makes the decision "not the caller's": the page object is Mozilla's case.
  const bool notTheCallers[][5] = {{false, false, false, false, true}, {true, true, false, false, true},
                                   {true, false, true, false, true},  {true, false, false, true, true},
                                   {true, false, false, false, false}};
  for (const auto& v : notTheCallers) {
    mozilla::StealthRecordCallerObject(mozilla::StealthCallerObjectDecision(v[0], v[1], v[2], v[3], v[4]));
    // The web-object case is Mozilla's term, whatever it says: the original condition comes back as it is.
    EXPECT_TRUE(mozilla::StealthNotCallerObject(true));
    EXPECT_FALSE(mozilla::StealthNotCallerObject(false));
    // Nothing is waiting for the regular case at the end of the chain, so StealthSelectedWrapper goes on to Mozilla's choice
    // of wrapper (its first test is this read, false here), and the look took nothing.
    EXPECT_FALSE(mozilla::StealthCallerObjectApplies());
    EXPECT_FALSE(mozilla::StealthCallerObjectApplies());
  }
  // Negative control: the caller's own decision, with the same look, is the one that steps the case aside.
  mozilla::StealthRecordCallerObject(mozilla::StealthCallerObjectDecision(true, false, false, false, true));
  EXPECT_FALSE(mozilla::StealthNotCallerObject(true));
  EXPECT_TRUE(mozilla::StealthCallerObjectApplies());
}

