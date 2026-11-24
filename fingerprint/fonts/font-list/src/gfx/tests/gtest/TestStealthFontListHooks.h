/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The pure cores of the hooks of fingerprint/fonts/font-list
// (StealthFontListHooks.h). The font list is bundle-only in every build, so the
// only way to see what a hook decides for stock Firefox is the core, where
// aBundleOnly is a value: each test below has its negative control in the
// aBundleOnly = false rows, which are the answers of Mozilla's own code.
//
// None of them needs the bundle on disk. This file is included by the one gtest
// file that runs on each platform (TestStealthFcFontList.cpp on Linux,
// TestStealthBundledCollection.cpp on Windows: gfx/tests/gtest/moz.build lists
// those two and not this one), so the tests run on both. The ones that read the
// manifest are in TestStealthFcFontList.cpp (the Linux gtest run reads it).

#ifndef GFX_TESTSTEALTHFONTLISTHOOKS_H
#define GFX_TESTSTEALTHFONTLISTHOOKS_H

#include "gtest/gtest.h"

#include "StealthFontListHooks.h"
#include "nsString.h"
#include "nsTArray.h"

TEST(StealthFontListHooks, PublishCharacterMap)
{
  // Mozilla's term (an installed face, !IsUserFont()) publishes in every case.
  EXPECT_TRUE(StealthPublishCharacterMapCore(true, false, false, false));
  EXPECT_TRUE(StealthPublishCharacterMapCore(true, true, false, false));
  // A bundled face is built from file data: only the bundle-only list
  // publishes its map.
  EXPECT_TRUE(StealthPublishCharacterMapCore(false, true, true, false));
  // Negative control: the list of stock Firefox does not publish it.
  EXPECT_FALSE(StealthPublishCharacterMapCore(false, false, true, false));
  // A src:local() borrow never publishes.
  EXPECT_FALSE(StealthPublishCharacterMapCore(false, true, true, true));
  EXPECT_FALSE(StealthPublishCharacterMapCore(false, true, false, true));
  // Neither Mozilla's term nor data: nothing.
  EXPECT_FALSE(StealthPublishCharacterMapCore(false, true, false, false));
}

TEST(StealthFontListHooks, NoFontsFound)
{
  // Bundle-only: the bundled count IS the expected state.
  EXPECT_FALSE(StealthNoFontsFoundCore(true, true));
  // Negative control: stock Firefox bails when the count equals the bundled
  // count.
  EXPECT_TRUE(StealthNoFontsFoundCore(false, true));
  EXPECT_FALSE(StealthNoFontsFoundCore(false, false));
  EXPECT_FALSE(StealthNoFontsFoundCore(true, false));
}

TEST(StealthFontListHooks, SkipsHostCollection)
{
  int system = 0;
  int bundled = 0;
  EXPECT_TRUE(StealthSkipsHostCollectionCore(true, &system, &system));
  // The bundled collection is still enumerated.
  EXPECT_FALSE(StealthSkipsHostCollectionCore(true, &bundled, &system));
  // Negative control: stock Firefox enumerates the system collection.
  EXPECT_FALSE(StealthSkipsHostCollectionCore(false, &system, &system));
}

TEST(StealthFontListHooks, SkipsHostSubstitutes)
{
  // Stock Firefox (aBundleOnly = false) always uses the host substitute tables.
  EXPECT_FALSE(StealthSkipsHostSubstitutesCore(false));
}

TEST(StealthFontListHooks, FaceIndex)
{
  // Mozilla's literal 0 stays 0 for every font that is not a .ttc face of the
  // bundle.
  EXPECT_EQ(StealthFaceIndex(0, 0), 0u);
  EXPECT_EQ(StealthFaceIndex(1, 0), 1u);
  EXPECT_EQ(StealthFaceIndex(7, 0), 7u);
  // An entry without a bundle index returns Mozilla's value.
  EXPECT_EQ(StealthFaceIndex(0, 5), 5u);
}

TEST(StealthFontListHooks, UsePrefFontList)
{
  EXPECT_TRUE(StealthUsePrefFontListCore(false, true));
  EXPECT_TRUE(StealthUsePrefFontListCore(true, false));
  // Negative control: stock Firefox follows Mozilla's own value.
  EXPECT_FALSE(StealthUsePrefFontListCore(false, false));
}

TEST(StealthFontListHooks, UseCmaps)
{
  EXPECT_TRUE(StealthUseCmapsCore(false, true));
  EXPECT_TRUE(StealthUseCmapsCore(true, false));
  // Negative control: stock Firefox follows Mozilla's own value.
  EXPECT_FALSE(StealthUseCmapsCore(false, false));
}

TEST(StealthFontListHooks, MayDeferCmapLoading)
{
  // Bundle-only never defers, whatever the pref says.
  EXPECT_FALSE(StealthMayDeferCmapLoadingCore(true, true));
  EXPECT_FALSE(StealthMayDeferCmapLoadingCore(true, false));
  // Negative control: stock Firefox defers when the pref is on.
  EXPECT_TRUE(StealthMayDeferCmapLoadingCore(false, true));
  EXPECT_FALSE(StealthMayDeferCmapLoadingCore(false, false));
}

TEST(StealthFontListHooks, ReplaceCommonFallbackKeepsThePlatformListWithoutBundleOnly)
{
  // Stock Firefox (aBundleOnly = false) keeps the platform's names.
  nsTArray<const char*> list;
  list.AppendElement("Platform");
  StealthReplaceCommonFallbackFontsCore(
      false, 'a', mozilla::intl::Script::LATIN,
      static_cast<FontPresentation>(0), list);
  ASSERT_EQ(list.Length(), 1u);
  EXPECT_STREQ(list[0], "Platform");
}

#endif  // GFX_TESTSTEALTHFONTLISTHOOKS_H
