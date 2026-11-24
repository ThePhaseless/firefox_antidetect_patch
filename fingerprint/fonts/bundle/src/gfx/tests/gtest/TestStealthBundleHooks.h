/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The tests of the hooks of fingerprint/fonts/bundle that need no bundle on
// disk and no window: the borrowed FontData, the presentation overload of the
// Windows fallback names, and the table lookup of the two-argument form of
// gfxFontUtils on a collection.
//
// This file is included by the one gtest file that runs on each platform
// (TestStealthFcFontList.cpp on Linux, TestStealthBundledCollection.cpp on
// Windows: gfx/tests/gtest/moz.build lists those two and not this one), so the
// tests run on both.

#ifndef GFX_TESTSTEALTHBUNDLEHOOKS_H
#define GFX_TESTSTEALTHBUNDLEHOOKS_H

#include "gtest/gtest.h"

#include <cstdlib>
#include <cstring>
#include <utility>

#include "FontData.h"
#include "StealthBundleFontList.h"
#include "gfxFontUtils.h"
#include "gfxPlatform.h"
#include "mozilla/RefPtr.h"
#include "nsTArray.h"

// FontData.h: a FontData lent by the bundle cache does not free its bytes, an
// owning one frees what it was given.
TEST(StealthBundleHooks, BorrowedFontDataIsNotFreed)
{
  uint8_t stack[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  {
    RefPtr<FontData> borrowed =
        new FontData(stack, sizeof(stack), FontData::Borrowed::Yes);
    EXPECT_EQ(nullptr, StealthFontDataOwned(borrowed.get(), stack));
    // Released at the end of this scope: a free() of a stack array would abort
    // here.
  }
  // Negative control: an owning FontData hands its pointer to free().
  uint8_t* heap = static_cast<uint8_t*>(malloc(8));
  ASSERT_NE(nullptr, heap);
  RefPtr<FontData> owning = new FontData(const_cast<const uint8_t*>(heap), 8);
  EXPECT_EQ(heap, StealthFontDataOwned(owning.get(), heap));
}

// gfxPlatformGtk::GetCommonFallbackFonts: the presentation overload is the bool
// overload on PrefersColor(aPresentation).
TEST(StealthBundleHooks, FallbackNamesTakeThePresentation)
{
  nsTArray<const char*> text;
  nsTArray<const char*> textViaBool;
  StealthAppendWindowsFallbackNames(FontPresentation::Any, text);
  StealthAppendWindowsFallbackNames(PrefersColor(FontPresentation::Any),
                                    textViaBool);
  ASSERT_EQ(text.Length(), textViaBool.Length());
  for (size_t i = 0; i < text.Length(); ++i) {
    EXPECT_STREQ(text[i], textViaBool[i]);
  }
  nsTArray<const char*> color;
  nsTArray<const char*> colorViaBool;
  StealthAppendWindowsFallbackNames(FontPresentation::EmojiDefault, color);
  StealthAppendWindowsFallbackNames(PrefersColor(FontPresentation::EmojiDefault),
                                    colorViaBool);
  ASSERT_EQ(color.Length(), colorViaBool.Length());
  for (size_t i = 0; i < color.Length(); ++i) {
    EXPECT_STREQ(color[i], colorViaBool[i]);
  }
  // Negative control: the two presentations give different lists (the emoji
  // face leads only the colour one).
  EXPECT_EQ(text.Length() + 1, color.Length());
  EXPECT_STREQ(color[0], "Segoe UI Emoji");
}

namespace stealth_bundle_hooks_test {

inline void PutBE16(uint8_t* aDst, uint16_t aValue) {
  aDst[0] = uint8_t(aValue >> 8);
  aDst[1] = uint8_t(aValue);
}

inline void PutBE32(uint8_t* aDst, uint32_t aValue) {
  PutBE16(aDst, uint16_t(aValue >> 16));
  PutBE16(aDst + 2, uint16_t(aValue));
}

// One sfnt header (12 bytes) with one 'name' table directory entry (16 bytes)
// at aOffset; the table itself lives at aTableOffset (4 bytes).
inline void WriteFace(uint8_t* aBuf, uint32_t aOffset, uint32_t aTableOffset) {
  uint8_t* p = aBuf + aOffset;
  PutBE32(p, 0x00010000);
  PutBE16(p + 4, 1);   // numTables
  PutBE16(p + 6, 16);  // searchRange
  PutBE16(p + 8, 0);   // entrySelector
  PutBE16(p + 10, 0);  // rangeShift
  PutBE32(p + 12, TRUETYPE_TAG('n', 'a', 'm', 'e'));
  PutBE32(p + 16, 0);  // checkSum
  PutBE32(p + 20, aTableOffset);
  PutBE32(p + 24, 4);  // length
}

constexpr uint32_t kFace0 = 20;
constexpr uint32_t kFace1 = 48;
constexpr uint32_t kTable0 = 76;
constexpr uint32_t kTable1 = 80;

// 'ttcf', version 1.0, two faces; table offsets are relative to the file start.
inline void BuildCollection(uint8_t (&aBuf)[84]) {
  memset(aBuf, 0, sizeof(aBuf));
  memcpy(aBuf, "ttcf", 4);
  PutBE16(aBuf + 4, 1);
  PutBE16(aBuf + 6, 0);
  PutBE32(aBuf + 8, 2);  // numFonts
  PutBE32(aBuf + 12, kFace0);
  PutBE32(aBuf + 16, kFace1);
  WriteFace(aBuf, kFace0, kTable0);
  WriteFace(aBuf, kFace1, kTable1);
  memcpy(aBuf + kTable0, "AAAA", 4);
  memcpy(aBuf + kTable1, "BBBB", 4);
}

}  // namespace stealth_bundle_hooks_test

// gfxFontUtils.cpp: Mozilla's two-argument lookup, hooked to read face 0 of a
// collection, as the three-argument form with index 0 did; the face N lookup
// is the three-argument form.
TEST(StealthBundleHooks, TwoArgumentLookupReadsFaceZeroOfACollection)
{
  using namespace stealth_bundle_hooks_test;
  uint8_t buf[84];
  BuildCollection(buf);
  const uint32_t tag = TRUETYPE_TAG('n', 'a', 'm', 'e');
  const mozilla::TableDirEntry* entry = gfxFontUtils::FindTableDirEntry(buf, tag);
  ASSERT_NE(entry, nullptr);
  EXPECT_EQ(uint32_t(entry->offset), kTable0);
  hb_blob_t* blob = gfxFontUtils::GetTableFromFontData(buf, tag);
  ASSERT_NE(blob, nullptr);
  unsigned int len = 0;
  EXPECT_EQ(0, memcmp(hb_blob_get_data(blob, &len), "AAAA", 4));
  hb_blob_destroy(blob);
  // Face 1 comes through the three-argument form (the negative control: the
  // two-argument form never returns the second face's table).
  const mozilla::TableDirEntry* second =
      gfxFontUtils::FindTableDirEntry(buf, tag, 1);
  ASSERT_NE(second, nullptr);
  EXPECT_EQ(uint32_t(second->offset), kTable1);
}

TEST(StealthBundleHooks, CollectionWithNoFaceFindsNothing)
{
  using namespace stealth_bundle_hooks_test;
  uint8_t buf[84];
  BuildCollection(buf);
  PutBE32(buf + 8, 0);  // numFonts = 0
  const uint32_t tag = TRUETYPE_TAG('n', 'a', 'm', 'e');
  EXPECT_EQ(gfxFontUtils::FindTableDirEntry(buf, tag), nullptr);
  EXPECT_EQ(gfxFontUtils::GetTableFromFontData(buf, tag), nullptr);
  EXPECT_EQ(gfxFontUtils::FindTableDirEntry(buf, tag, 0), nullptr);
}

#endif  // GFX_TESTSTEALTHBUNDLEHOOKS_H
