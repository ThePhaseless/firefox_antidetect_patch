/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The table lookup of the two-argument form of gfxFontUtils on a collection:
// it reads face 0, as the three-argument form with index 0 does. It needs no
// bundle on disk and no window, so it runs on every platform.

#include "gtest/gtest.h"

#include <cstring>

#include "gfxFontUtils.h"

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
