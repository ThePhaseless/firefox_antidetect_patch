/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "gtest/gtest.h"

#include "mozilla/scache/StealthStartupCache.h"

// A write holds mTableLock throughout and the main thread's GetBuffer() waits
// on it, so no write may lower its own priority: see
// StealthWritesMayLowerIOPriority for what that cost under load.
TEST(StealthStartupCache, AWriteNeverLowersItsIOPriority)
{
  EXPECT_FALSE(mozilla::scache::StealthWritesMayLowerIOPriority(true));
  EXPECT_FALSE(mozilla::scache::StealthWritesMayLowerIOPriority(false));
}
