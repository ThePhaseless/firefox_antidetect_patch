/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "gtest/gtest.h"

#include "StealthPrefSanitize.h"

// The names Preferences.cpp let through to content processes through its
// override list entry "zoom.stealth.": every name that starts with it.
TEST(StealthPrefSanitize, ThePrefixIsAllowedInContent)
{
  EXPECT_TRUE(StealthPrefAllowedInContent("zoom.stealth.screen.width"));
  EXPECT_TRUE(StealthPrefAllowedInContent("zoom.stealth.x"));
  EXPECT_TRUE(StealthPrefAllowedInContent("zoom.stealth."));
}

// Negative control: names outside the prefix are not ours to allow, so
// Mozilla's own rules keep deciding them.
TEST(StealthPrefSanitize, NamesOutsideThePrefixAreNotAllowed)
{
  EXPECT_FALSE(StealthPrefAllowedInContent("zoom.stealth"));
  EXPECT_FALSE(StealthPrefAllowedInContent("zoom.stealthy"));
  EXPECT_FALSE(StealthPrefAllowedInContent("zoom.other"));
  EXPECT_FALSE(StealthPrefAllowedInContent("zoom."));
  EXPECT_FALSE(StealthPrefAllowedInContent("ui.x"));
  EXPECT_FALSE(StealthPrefAllowedInContent("datareporting.policy.x"));
  EXPECT_FALSE(StealthPrefAllowedInContent(""));
}
