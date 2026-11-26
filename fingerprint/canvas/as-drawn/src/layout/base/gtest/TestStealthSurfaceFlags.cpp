/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The flag of ours in nsLayoutUtils::SurfaceFromElement's aSurfaceFlags
// (kStealthSfeAsDrawn): the canvas as drawn, for the browser's own readers.
// Every other caller gets the snapshot a page gets, so the flag must be on no
// bit of Mozilla's SFE_* flags, and StealthWantsAsDrawn must be true for it and
// for nothing else.

#include "StealthSurfaceFlags.h"

#include "gtest/gtest.h"

TEST(StealthSurfaceFlags, TheFlagIsOnNoBitOfMozillasFlags)
{
  const uint32_t mozilla[] = {
      nsLayoutUtils::SFE_WANT_FIRST_FRAME_IF_IMAGE,
      nsLayoutUtils::SFE_NO_COLORSPACE_CONVERSION,
      nsLayoutUtils::SFE_ALLOW_NON_PREMULT,
      nsLayoutUtils::SFE_NO_RASTERIZING_VECTORS,
      nsLayoutUtils::SFE_USE_ELEMENT_SIZE_IF_VECTOR,
      nsLayoutUtils::SFE_EXACT_SIZE_SURFACE,
      nsLayoutUtils::SFE_ORIENTATION_FROM_IMAGE,
      nsLayoutUtils::SFE_ALLOW_UNCROPPED_UNSCALED,
  };
  for (uint32_t flag : mozilla) {
    EXPECT_EQ(flag & kStealthSfeAsDrawn, 0u);
    // Mozilla's flags alone never ask for the canvas as drawn.
    EXPECT_FALSE(StealthWantsAsDrawn(flag));
  }
}

TEST(StealthSurfaceFlags, OnlyOurFlagAsksForTheCanvasAsDrawn)
{
  EXPECT_TRUE(StealthWantsAsDrawn(kStealthSfeAsDrawn));
  EXPECT_TRUE(StealthWantsAsDrawn(kStealthSfeAsDrawn |
                                  nsLayoutUtils::SFE_ALLOW_NON_PREMULT));
  // Negative control: the default flags of a page's reader.
  EXPECT_FALSE(StealthWantsAsDrawn(0));
}
