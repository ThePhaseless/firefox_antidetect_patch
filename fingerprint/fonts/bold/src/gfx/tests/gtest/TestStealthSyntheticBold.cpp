/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The synthetic bold of a face the font does not have, the same on Linux and Windows
// (gfx/thebes/StealthSyntheticBold.h): the rule of Firefox retail on Windows, where a
// bold is simulated by the rasteriser for an installed font (here: a face of the
// bundle) and struck again by Gecko for a webfont or a COLR font. The simulation is
// DWRITE_FONT_SIMULATIONS_BOLD on Windows and idwr's kSimulationBold for the ink on
// both OSes; its advance is the one DirectWrite's GetDesignGlyphAdvances gives the
// simulated face, (unitsPerEm + 25) / 50 added to the advance of a glyph with ink,
// and idwr reproduces it (invisible_DWriteCore, design_advances over simulations).
//
// Malgun Gothic (malgun.ttf, 2048 em, no bold of its own: the CJK fallback of a bold
// text) at 16px: 1 / 128 px per unit, so every number below is exact. From the file's
// hmtx: H 1484, space 720 (no ink), '0' 1128, U+6C34 and U+AC00 2048; d = 41.
//
// Before: Linux asked FreeType's embolden (its strength added to every advance, the
// space too, and idwr's kSimulationBold for the ink) and Windows took the webfont
// branch for the bundle (multi-strike), so that a bold CJK fallback differed between
// the two and from retail.

#include "gtest/gtest.h"

#include <stdlib.h>
#include <string.h>

#include <utility>

#include "FontData.h"
#include "ScaledFontBase.h"
#include "StealthSyntheticBold.h"
#include "StealthTestFonts.h"
#include "gfxFont.h"
#include "gfxFontEntry.h"
#include "gfxPlatform.h"
#include "gfxPlatformFontList.h"
#include "mozilla/FontPropertyTypes.h"
#include "mozilla/Preferences.h"
#include "mozilla/gfx/2D.h"
#include "nsFontMetrics.h"
#include "nsString.h"
#ifdef XP_WIN
#  include "gfxDWriteFonts.h"
#else
#  include "StealthIdwrTextVars.h"
#endif

using namespace mozilla;
using namespace mozilla::gfx;

namespace {

const char* const kPrefs[] = {
    "zoom.stealth.fpp.hw_seed",
    "zoom.stealth.text.system_quality",
    "gfx.font_rendering.cleartype_params.gamma",
    "gfx.font_rendering.cleartype_params.enhanced_contrast",
    "gfx.font_rendering.cleartype_params.cleartype_level",
    "gfx.font_rendering.cleartype_params.rendering_mode",
};

void UpdateTextVars() {
#ifdef XP_WIN
  gfxDWriteFont::UpdateSystemTextVars();
#else
  StealthIdwrUpdateTextVars();
#endif
}

// Back to stock Firefox, and the text vars recomputed, whatever the test did.
struct RestoreStock {
  ~RestoreStock() {
    for (const char* name : kPrefs) {
      Preferences::ClearUser(name);
    }
    UpdateTextVars();
  }
};

// The font a launcher declares with the engine on: ClearType, natural rendering.
void DeclareEngine() {
  Preferences::SetInt("zoom.stealth.text.system_quality", 5);
  Preferences::SetInt("gfx.font_rendering.cleartype_params.gamma", 1000);
  Preferences::SetInt("gfx.font_rendering.cleartype_params.enhanced_contrast", 0);
  Preferences::SetInt("gfx.font_rendering.cleartype_params.cleartype_level", 100);
  Preferences::SetInt("gfx.font_rendering.cleartype_params.rendering_mode", 0);
  // The engine on, last: with it on a change of the text prefs updates the text vars,
  // and a declaration without the rendering mode is refused.
  Preferences::SetInt("zoom.stealth.fpp.hw_seed", 7);
  UpdateTextVars();
}

constexpr double kSize = 16.0;

// A face of the bundle, asked for aSize px, regular or bold. The bundle is the font
// list of the product: a family name finds its shared-list face, built from data.
already_AddRefed<gfxFont> BundleFont(const char* aFamily, bool aBold) {
  gfxPlatformFontList* pfl = gfxPlatformFontList::PlatformFontList();
  if (!pfl) {
    return nullptr;
  }
  gfxFontStyle style;
  style.size = kSize;
  if (aBold) {
    style.weight = FontWeight::BOLD;
  }
  gfxFontEntry* entry = pfl->FindFontForFamily(nullptr, nsDependentCString(aFamily), &style);
  if (!entry) {
    return nullptr;
  }
  RefPtr<gfxFont> font = entry->FindOrMakeFont(&style);
  return (font && font->Valid()) ? font.forget() : nullptr;
}

// A webfont: the bytes of a bundled file made a platform font, as a downloaded
// @font-face is, and asked for aSize px, regular or bold.
already_AddRefed<gfxFont> Webfont(gfxFontEntry* aEntry, bool aBold) {
  gfxFontStyle style;
  style.size = kSize;
  if (aBold) {
    style.weight = FontWeight::BOLD;
  }
  RefPtr<gfxFont> font = aEntry->FindOrMakeFont(&style);
  return (font && font->Valid()) ? font.forget() : nullptr;
}

already_AddRefed<gfxFontEntry> MakeWebfontEntry(const char* aFile) {
  nsTArray<uint8_t> bytes = stealth_test_fonts::ReadBundledFont(aFile);
  gfxPlatformFontList* pfl = gfxPlatformFontList::PlatformFontList();
  if (bytes.IsEmpty() || !pfl) {
    return nullptr;
  }
  // FontData owns a malloc'd buffer and frees it.
  auto* buffer = static_cast<uint8_t*>(malloc(bytes.Length()));
  if (!buffer) {
    return nullptr;
  }
  memcpy(buffer, bytes.Elements(), bytes.Length());
  const uint8_t* owned = buffer;
  RefPtr<FontData> data = new FontData(std::move(owned), bytes.Length());
  return pfl->MakePlatformFont("StealthSyntheticBoldWebfont"_ns,
                               WeightRange(FontWeight::NORMAL),
                               WidthRange(FontWidth::NORMAL),
                               SlantStyleRange(FontSlantStyle::NORMAL), data);
}

// Does the typeface Skia draws this font's glyphs with simulate the bold (idwr's
// kSimulationBold on Linux, the simulation of the DirectWrite face on Windows)?
// -1: the font has no typeface.
int TypefaceSimulatesBold(gfxFont* aFont) {
  RefPtr<ScaledFont> scaled = aFont->GetScaledFont((DrawTarget*)nullptr);
  if (!scaled) {
    return -1;
  }
  SkTypeface* typeface = static_cast<ScaledFontBase*>(scaled.get())->GetSkTypeface();
  return typeface ? int(typeface->isSyntheticBold()) : -1;
}

constexpr uint32_t kH = 'H';
constexpr uint32_t kSpace = ' ';
constexpr uint32_t kZero = '0';
constexpr uint32_t kWater = 0x6C34;
constexpr uint32_t kHangul = 0xAC00;

}  // namespace

class StealthSyntheticBold : public ::testing::Test {
 protected:
  static void SetUpTestSuite() {
    // The platform and its font list.
    gfxPlatform::GetPlatform();
  }
  RestoreStock mRestore;
};

// The rule, from its facts (gfxDWriteFont, bold_simulation 1): a webfont or a COLR font
// is struck by Gecko, anything else is simulated by the rasteriser.
TEST(StealthSyntheticBoldRule, ARasteriserSimulatesAnInstalledFontNotAWebfontOrColr)
{
  //                                    webfont colr
  EXPECT_TRUE(StealthMultistrikeBoldRule(true, false));
  EXPECT_TRUE(StealthMultistrikeBoldRule(false, true));
  EXPECT_TRUE(StealthMultistrikeBoldRule(true, true));
  EXPECT_FALSE(StealthMultistrikeBoldRule(false, false));
}

// A face of the bundle without a bold of its own (the CJK fallback of a bold text):
// the rasteriser simulates it, as it does an installed font on retail. Gecko does not
// strike it, the typeface carries the simulation, and the glyph advances are the
// simulated face's: d = 41 added to a glyph with ink, nothing to the space.
TEST_F(StealthSyntheticBold, ABundleFaceIsSimulatedAsAnInstalledFont)
{
  DeclareEngine();
  RefPtr<gfxFont> regular = BundleFont("Malgun Gothic", false);
  RefPtr<gfxFont> bold = BundleFont("Malgun Gothic", true);
  ASSERT_TRUE(regular);
  ASSERT_TRUE(bold);
  ASSERT_NE(regular.get(), bold.get());

  EXPECT_FALSE(regular->ApplySyntheticBold());
  EXPECT_FALSE(bold->ApplySyntheticBold());
  EXPECT_EQ(0, TypefaceSimulatesBold(regular));
  EXPECT_EQ(1, TypefaceSimulatesBold(bold));

  // The regular face: the design advances of the file.
  EXPECT_DOUBLE_EQ(11.59375, regular->GetCharAdvance(kH));
  EXPECT_DOUBLE_EQ(5.625, regular->GetCharAdvance(kSpace));
  EXPECT_DOUBLE_EQ(16.0, regular->GetCharAdvance(kWater));
  // The simulated bold: (advance + 41) / 128, and the space, which has no ink, as it was.
  EXPECT_DOUBLE_EQ(11.9140625, bold->GetCharAdvance(kH));
  EXPECT_DOUBLE_EQ(9.1328125, bold->GetCharAdvance(kZero));
  EXPECT_DOUBLE_EQ(16.3203125, bold->GetCharAdvance(kWater));
  EXPECT_DOUBLE_EQ(16.3203125, bold->GetCharAdvance(kHangul));
  EXPECT_DOUBLE_EQ(5.625, bold->GetCharAdvance(kSpace));

  // The metrics the page reads (measureText, ch and ic units) are those advances.
  const auto& b = bold->GetMetrics(nsFontMetrics::eHorizontal);
  EXPECT_DOUBLE_EQ(5.625, b.spaceWidth);
  EXPECT_DOUBLE_EQ(9.1328125, b.zeroWidth);
  EXPECT_DOUBLE_EQ(16.3203125, b.ideographicWidth);
}

// A webfont (the page's own data) asked for a bold it lacks: Gecko strikes it again, as
// retail does. The metrics and the advance of every cluster grow by GetSyntheticBoldOffset()
// (0.25 + 0.75 * 16 / 48 = 0.5), the advance of the glyph itself is the regular one, and
// the typeface is not simulated: the same bold twice would be another drawing.
TEST_F(StealthSyntheticBold, AWebfontIsMultistruck)
{
  DeclareEngine();
  RefPtr<gfxFontEntry> entry = MakeWebfontEntry("consola7_00.ttf");
  ASSERT_TRUE(entry);
  RefPtr<gfxFont> regular = Webfont(entry, false);
  RefPtr<gfxFont> bold = Webfont(entry, true);
  ASSERT_TRUE(regular);
  ASSERT_TRUE(bold);

  EXPECT_FALSE(regular->ApplySyntheticBold());
  EXPECT_TRUE(bold->ApplySyntheticBold());
  EXPECT_DOUBLE_EQ(0.5, bold->GetSyntheticBoldOffset());
  EXPECT_EQ(0, TypefaceSimulatesBold(bold));

  // Consolas: 1126 units, 8.796875 px.
  EXPECT_DOUBLE_EQ(8.796875, regular->GetCharAdvance(kH));
  EXPECT_DOUBLE_EQ(8.796875, bold->GetCharAdvance(kH));
  const auto& r = regular->GetMetrics(nsFontMetrics::eHorizontal);
  const auto& b = bold->GetMetrics(nsFontMetrics::eHorizontal);
  EXPECT_DOUBLE_EQ(r.spaceWidth + 0.5, b.spaceWidth);
  EXPECT_DOUBLE_EQ(r.aveCharWidth + 0.5, b.aveCharWidth);
  EXPECT_DOUBLE_EQ(r.maxAdvance + 0.5, b.maxAdvance);
  EXPECT_DOUBLE_EQ(r.zeroWidth + 0.5, b.zeroWidth);
}

// A COLR font of the bundle (Segoe UI Emoji, the emoji fallback of a bold text) is
// struck by Gecko, as on retail, whatever it is: no simulation of its typeface.
TEST_F(StealthSyntheticBold, AColrFaceIsMultistruck)
{
  DeclareEngine();
  RefPtr<gfxFont> regular = BundleFont("Segoe UI Emoji", false);
  RefPtr<gfxFont> bold = BundleFont("Segoe UI Emoji", true);
  ASSERT_TRUE(regular);
  ASSERT_TRUE(bold);

  EXPECT_FALSE(regular->ApplySyntheticBold());
  EXPECT_TRUE(bold->ApplySyntheticBold());
  EXPECT_DOUBLE_EQ(0.5, bold->GetSyntheticBoldOffset());
  EXPECT_EQ(0, TypefaceSimulatesBold(bold));
  const auto& r = regular->GetMetrics(nsFontMetrics::eHorizontal);
  const auto& b = bold->GetMetrics(nsFontMetrics::eHorizontal);
  EXPECT_DOUBLE_EQ(r.spaceWidth + 0.5, b.spaceWidth);
  EXPECT_DOUBLE_EQ(regular->GetCharAdvance(kSpace), bold->GetCharAdvance(kSpace));
}

#ifndef XP_WIN
// Engine off: stock Linux, which never strikes the bold itself and asks FreeType's embolden.
TEST_F(StealthSyntheticBold, EngineOffBoldStaysStock)
{
  RefPtr<gfxFontEntry> entry = MakeWebfontEntry("consola7_00.ttf");
  ASSERT_TRUE(entry);
  RefPtr<gfxFont> bold = Webfont(entry, true);
  ASSERT_TRUE(bold);
  EXPECT_FALSE(bold->ApplySyntheticBold());
}
#endif
