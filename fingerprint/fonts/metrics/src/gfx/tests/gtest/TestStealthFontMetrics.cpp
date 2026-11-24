/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The average character width on the FreeType path with the stealth engine on
// is the one gfxDWriteFont::ComputeMetrics computes
// (StealthDWriteAveCharWidth, gfx/thebes/StealthDesignMetrics.h). FreeType
// rounds it to whole pixels and Windows does not, so a default textarea
// (monospace, Consolas, 13px) at DPR 1.5 was 146.667px wide on Linux against
// 143px on Windows.
//
// A real font: the bundled Consolas (1126 xAvgCharWidth and 'x' advance on a
// 2048 em) at 19.5 device px, which is 13px at DPR 1.5, loaded as a data font
// so every case gets a fresh entry and metrics computed under its own prefs.

#include "gtest/gtest.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <algorithm>
#include <utility>

#include "FontData.h"
#include "StealthDesignFontAccess.h"
#include "gfxFT2FontBase.h"
#include "gfxFont.h"
#include "gfxFontEntry.h"
#include "gfxPlatform.h"
#include "gfxPlatformFontList.h"
#include "gfxRect.h"
#include "harfbuzz/hb-ot.h"
#include "harfbuzz/hb.h"
#include "mozilla/FontPropertyTypes.h"
#include "mozilla/Preferences.h"
#include "mozilla/ScopeExit.h"
#include "mozilla/gfx/StealthGlyphCoverage.h"
#include "nsCOMPtr.h"
#include "nsDirectoryServiceDefs.h"
#include "nsDirectoryServiceUtils.h"
#include "nsFontMetrics.h"
#include "nsIFile.h"
#include "nsIInputStream.h"
#include "nsMathUtils.h"
#include "nsNetUtil.h"
#include "nsStreamUtils.h"
#include "nsString.h"
#include "nsThreadUtils.h"

namespace {

const char* const kStealthFontMetricsPrefs[] = {
    "zoom.stealth.fpp.hw_seed",
    "zoom.stealth.text.system_quality",
    "gfx.font_rendering.cleartype_params.rendering_mode",
};

// Back to stock Firefox (nothing declared), whatever the test did.
struct RestoreStealthFontMetricsStock {
  ~RestoreStealthFontMetricsStock() {
    for (const char* name : kStealthFontMetricsPrefs) {
      mozilla::Preferences::ClearUser(name);
    }
  }
};

// The default textarea font at DPR 1.5: 13px * 1.5.
constexpr double kStealthConsolasSize = 19.5;
// 60 app units per CSS px / 1.5.
constexpr int32_t kStealthAppUnitsPerDevPixel = 40;

// The bundled file, as the product ships it in <GRE>/fonts. Its absence is a
// real failure (the font is part of the product), so the caller asserts; the
// places looked at go to aTried for the message.
RefPtr<FontData> StealthLoadBundledConsolas(nsCString& aTried) {
  for (const char* key : {NS_GRE_DIR, NS_XPCOM_CURRENT_PROCESS_DIR}) {
    nsCOMPtr<nsIFile> dir;
    if (NS_FAILED(NS_GetSpecialDirectory(key, getter_AddRefs(dir)))) {
      aTried.AppendPrintf(" [%s: no such directory]", key);
      continue;
    }
    // The directory itself, then its parent (a gtest libxul lives one level
    // below the application).
    for (int level = 0; level < 2 && dir; ++level) {
      nsCOMPtr<nsIFile> file;
      if (NS_FAILED(dir->Clone(getter_AddRefs(file))) ||
          NS_FAILED(file->Append(u"fonts"_ns)) ||
          NS_FAILED(file->Append(u"consola7_00.ttf"_ns))) {
        break;
      }
      nsAutoCString path;
      file->GetNativePath(path);
      aTried.AppendPrintf(" [%s]", path.get());
      nsCString bytes;
      nsCOMPtr<nsIInputStream> stream;
      if (NS_SUCCEEDED(
              NS_NewLocalFileInputStream(getter_AddRefs(stream), file))) {
        const nsresult rv = NS_ConsumeStream(stream, UINT32_MAX, bytes);
        stream->Close();
        if (NS_SUCCEEDED(rv) && !bytes.IsEmpty()) {
          // FontData owns a malloc'd buffer and frees it.
          auto* buffer = static_cast<uint8_t*>(malloc(bytes.Length()));
          if (!buffer) {
            return nullptr;
          }
          memcpy(buffer, bytes.get(), bytes.Length());
          const uint8_t* owned = buffer;
          return new FontData(std::move(owned), bytes.Length());
        }
      }
      nsCOMPtr<nsIFile> parent;
      dir->GetParent(getter_AddRefs(parent));
      dir = parent;
    }
  }
  return nullptr;
}

// A NEW entry on aData (main thread), so the font made from it next has its
// metrics computed under the prefs set now.
already_AddRefed<gfxFontEntry> StealthMakeConsolasEntry(FontData* aData) {
  gfxPlatformFontList* pfl = gfxPlatformFontList::PlatformFontList();
  if (!pfl) {
    return nullptr;
  }
  return pfl->MakePlatformFont(
      "StealthFontMetricsConsolas"_ns,
      mozilla::WeightRange(mozilla::FontWeight::NORMAL),
      mozilla::WidthRange(mozilla::FontWidth::NORMAL),
      mozilla::SlantStyleRange(mozilla::FontSlantStyle::NORMAL), aData);
}

// gfxFont::Metrics::aveCharWidth of the font at 19.5px on aEntry: making the
// font is what runs gfxFT2FontBase::InitMetrics, on the calling thread. -1 if
// no font could be made.
gfxFloat StealthMeasureConsolasAve(gfxFontEntry* aEntry) {
  if (!aEntry) {
    return -1.0;
  }
  gfxFontStyle style;
  style.size = kStealthConsolasSize;
  RefPtr<gfxFont> font = aEntry->FindOrMakeFont(&style);
  if (!font || !font->Valid()) {
    return -1.0;
  }
  return font->GetMetrics(nsFontMetrics::eHorizontal).aveCharWidth;
}

gfxFloat StealthConsolasAveCharWidth(FontData* aData) {
  RefPtr<gfxFontEntry> fe = StealthMakeConsolasEntry(aData);
  return StealthMeasureConsolasAve(fe);
}

// nsFontMetrics::AveCharWidth at 40 app units per device px: its own
// expression, CEIL_TO_TWIPS(aveCharWidth) (gfx/src/nsFontMetrics.cpp). A real
// nsFontMetrics needs a pres context, which a gfx gtest does not have.
nscoord StealthNsFontMetricsAveCharWidth(gfxFloat aAveCharWidth) {
  return nscoord(ceil(aAveCharWidth * kStealthAppUnitsPerDevPixel));
}

// A fresh font of the bundled Consolas at aSize, on a FreeType backend (null
// if none could be made): its glyph metrics are computed under the prefs set
// when it is first asked.
RefPtr<gfxFont> StealthMakeConsolasFont(FontData* aData, double aSize) {
  RefPtr<gfxFontEntry> fe = StealthMakeConsolasEntry(aData);
  if (!fe) {
    return nullptr;
  }
  gfxFontStyle style;
  style.size = aSize;
  RefPtr<gfxFont> font = fe->FindOrMakeFont(&style);
  // On Linux the font is a gfxFontconfigFont, which says FONT_TYPE_FONTCONFIG;
  // gfxFT2Font says FONT_TYPE_FT2. Both are gfxFT2FontBase.
  if (!font || !font->Valid() ||
      (font->GetType() != gfxFont::FONT_TYPE_FT2 &&
       font->GetType() != gfxFont::FONT_TYPE_FONTCONFIG)) {
    return nullptr;
  }
  return font;
}

// A size that is not a whole number of pixels: FreeType takes its ppem from it
// rounded, DirectWrite scales by it as it is.
constexpr double kStealthFractionalSize = 13.383333;

class StealthFontMetrics : public ::testing::Test {
 protected:
  static void SetUpTestSuite() {
    // The platform and its font list, built with the engine off.
    gfxPlatform::GetPlatform();
  }
  void SetUp() override {
    nsCString tried;
    mData = StealthLoadBundledConsolas(tried);
    ASSERT_TRUE(mData) << "the bundled consola7_00.ttf could not be read; looked"
                       << " at:" << tried.get();
  }
  void DeclareEngine(int32_t aQuality, int32_t aRenderingMode) {
    mozilla::Preferences::SetInt("zoom.stealth.fpp.hw_seed", 7);
    mozilla::Preferences::SetInt("zoom.stealth.text.system_quality", aQuality);
    mozilla::Preferences::SetInt(
        "gfx.font_rendering.cleartype_params.rendering_mode", aRenderingMode);
  }
  RestoreStealthFontMetricsStock mRestore;
  RefPtr<FontData> mData;
};

}  // namespace

// ClearType (5) and a natural rendering mode: Windows measures in design space
// and takes int16(xAvgCharWidth) * float(size / upem), unrounded.
TEST_F(StealthFontMetrics, ClearTypeTakesTheOS2AverageUnrounded)
{
  // DWRITE_RENDERING_MODE_DEFAULT (0) and NATURAL_SYMMETRIC (5) both measure
  // natural.
  for (int32_t mode : {0, 5}) {
    DeclareEngine(5, mode);
    const gfxFloat ave = StealthConsolasAveCharWidth(mData);
    EXPECT_EQ(double(1126 * float(kStealthConsolasSize / 2048)), ave) << mode;
    EXPECT_EQ(429, StealthNsFontMetricsAveCharWidth(ave)) << mode;
  }
}

// Standard antialiasing (4): not ClearType, so Windows leaves design space and
// takes the 'x' advance, rounded to a whole pixel.
TEST_F(StealthFontMetrics, OutsideClearTypeTakesTheRoundedXAdvance)
{
  DeclareEngine(4, 0);
  const gfxFloat ave = StealthConsolasAveCharWidth(mData);
  EXPECT_EQ(double(NS_lround(1126 * float(kStealthConsolasSize / 2048))), ave);
  EXPECT_EQ(11.0, ave);
  EXPECT_EQ(440, StealthNsFontMetricsAveCharWidth(ave));
}

// ClearType with a GDI rendering mode (2, CLEARTYPE_GDI_CLASSIC) measures GDI
// classic: the rounded 'x' advance too.
TEST_F(StealthFontMetrics, GdiRenderingModeTakesTheRoundedXAdvance)
{
  DeclareEngine(5, 2);
  EXPECT_EQ(11.0, StealthConsolasAveCharWidth(mData));
}

// Engine off: stock Firefox, the declaration in the profile is not read and
// FreeType's whole-pixel value stays (1126 at ppem 20 is 10.996, rounded 11).
TEST_F(StealthFontMetrics, EngineOffKeepsMozillasValue)
{
  mozilla::Preferences::SetInt("zoom.stealth.text.system_quality", 5);
  mozilla::Preferences::SetInt(
      "gfx.font_rendering.cleartype_params.rendering_mode", 0);
  const gfxFloat ave = StealthConsolasAveCharWidth(mData);
  EXPECT_EQ(11.0, ave);
  EXPECT_EQ(440, StealthNsFontMetricsAveCharWidth(ave));
}

// Metrics are computed wherever a font is first measured, workers included
// (OffscreenCanvas measureText). The rendering mode reaches InitMetrics through
// the mirror StealthTextMeasuringInit registers (gfxFontCache::Init), never
// through Preferences, which is main-thread only (it asserts in debug builds).
// The pref is changed on the main thread between the two rounds: the mirror
// has to follow it.
TEST_F(StealthFontMetrics, MetricsOffTheMainThreadReadTheDeclaration)
{
  nsCOMPtr<nsIThread> thread;
  ASSERT_TRUE(NS_SUCCEEDED(
      NS_NewNamedThread("StealthFontMet", getter_AddRefs(thread))));
  auto shutdown = mozilla::MakeScopeExit([&] { thread->Shutdown(); });
  const struct {
    int32_t mRenderingMode;
    gfxFloat mExpected;
  } kRounds[] = {
      {0, double(1126 * float(kStealthConsolasSize / 2048))},  // natural
      {2, 11.0},  // CLEARTYPE_GDI_CLASSIC: the rounded 'x' advance
  };
  for (const auto& round : kRounds) {
    DeclareEngine(5, round.mRenderingMode);
    RefPtr<gfxFontEntry> fe = StealthMakeConsolasEntry(mData);
    ASSERT_TRUE(fe);
    gfxFontEntry* entry = fe;
    gfxFloat ave = -1.0;
    bool offMainThread = false;
    ASSERT_TRUE(NS_SUCCEEDED(NS_DispatchAndSpinEventLoopUntilComplete(
        "TestStealthFontMetrics"_ns, thread,
        NS_NewRunnableFunction("TestStealthFontMetrics", [&]() {
          offMainThread = !NS_IsMainThread();
          ave = StealthMeasureConsolasAve(entry);
        }))));
    EXPECT_TRUE(offMainThread);
    EXPECT_EQ(round.mExpected, ave) << round.mRenderingMode;
  }
}

// The advance of a glyph is its DESIGN advance times the size as asked for
// (1126 font units for every Consolas glyph, on a 2048 em), the way DirectWrite
// scales it, not the one FreeType reaches through its integer ppem. 16.16, as
// gfxFont::GetGlyphWidth speaks.
TEST_F(StealthFontMetrics, DesignAdvanceAtAFractionalSize)
{
  int32_t stock = 0;
  {
    // Engine off: FreeType's own value (the negative control).
    RefPtr<gfxFont> font =
        StealthMakeConsolasFont(mData, kStealthFractionalSize);
    ASSERT_TRUE(font);
    stock = static_cast<gfxFT2FontBase*>(font.get())
                ->GetGlyphWidth(uint16_t(font->GetGlyph('x', 0)));
  }
  DeclareEngine(5, 0);
  RefPtr<gfxFont> font = StealthMakeConsolasFont(mData, kStealthFractionalSize);
  ASSERT_TRUE(font);
  const uint16_t gid = uint16_t(font->GetGlyph('x', 0));
  ASSERT_NE(0, gid);
  const int32_t declared =
      static_cast<gfxFT2FontBase*>(font.get())->GetGlyphWidth(gid);
  EXPECT_EQ(
      NS_lround(double(1126) * kStealthFractionalSize * 65536.0 / 2048.0),
      declared);
  EXPECT_NE(stock, declared);
}

// The ink box of a glyph is the font's own bounding box scaled by size / upem,
// with no hinting: read here straight from HarfBuzz, in the order of
// operations gfxDWriteFont::GetGlyphBounds uses (units first, then the float
// factor), and compared exactly.
TEST_F(StealthFontMetrics, DesignGlyphBoundsAreTheDesignBox)
{
  gfxRect stock;
  {
    // Engine off: FreeType's hinted bounds (the negative control).
    RefPtr<gfxFont> font =
        StealthMakeConsolasFont(mData, kStealthFractionalSize);
    ASSERT_TRUE(font);
    ASSERT_TRUE(static_cast<gfxFT2FontBase*>(font.get())
                    ->GetGlyphBounds(uint16_t(font->GetGlyph('x', 0)), &stock,
                                     true));
  }
  DeclareEngine(5, 0);
  RefPtr<gfxFont> font = StealthMakeConsolasFont(mData, kStealthFractionalSize);
  ASSERT_TRUE(font);
  const uint16_t gid = uint16_t(font->GetGlyph('x', 0));
  ASSERT_NE(0, gid);
  gfxFontEntry* fe = font->GetFontEntry();
  const uint16_t upem = fe->UnitsPerEm();
  ASSERT_NE(0, upem);

  hb_glyph_extents_t ext;
  {
    const auto face(fe->GetHBFace());
    hb_face_t* hbFace = face;
    ASSERT_NE(nullptr, hbFace);
    hb_font_t* hbFont = hb_font_create(hbFace);
    ASSERT_TRUE(hbFont);
    hb_ot_font_set_funcs(hbFont);
    hb_font_set_scale(hbFont, upem, upem);
    hb_font_set_ppem(hbFont, 0, 0);
    const hb_bool_t ok = hb_font_get_glyph_extents(hbFont, gid, &ext);
    hb_font_destroy(hbFont);
    ASSERT_TRUE(ok);
  }
  // HarfBuzz's y_bearing is the top measured upward and its height is
  // negative: both are negated to reach gfxRect's y-down box.
  gfxRect expected(double(ext.x_bearing), double(-ext.y_bearing),
                   double(ext.width), double(-ext.height));
  expected.Scale(float(kStealthFractionalSize / gfxFloat(upem)));

  gfxRect declared;
  ASSERT_TRUE(static_cast<gfxFT2FontBase*>(font.get())
                  ->GetGlyphBounds(gid, &declared, true));
  EXPECT_EQ(expected.X(), declared.X());
  EXPECT_EQ(expected.Y(), declared.Y());
  EXPECT_EQ(expected.Width(), declared.Width());
  EXPECT_EQ(expected.Height(), declared.Height());
  EXPECT_FALSE(stock.X() == declared.X() && stock.Y() == declared.Y() &&
               stock.Width() == declared.Width() &&
               stock.Height() == declared.Height());
}

// The design font is released from the shaper's destructor through
// StealthReleaseDesignFont: it drops the font's reference on the face, so a face
// kept alive only by that font is destroyed. Negative control: before the
// release the face is still alive.
TEST_F(StealthFontMetrics, TheDesignFontReleaseDropsItsFaceReference)
{
  static hb_user_data_key_t key;
  int destroyed = 0;
  hb_face_t* face = hb_face_create(hb_blob_get_empty(), 0);
  ASSERT_NE(nullptr, face);
  hb_face_set_user_data(
      face, &key, &destroyed,
      [](void* aData) { ++*static_cast<int*>(aData); }, true);
  hb_font_t* font = hb_font_create(face);
  hb_face_destroy(face);  // only the font's reference is left
  EXPECT_EQ(0, destroyed);
  StealthReleaseDesignFont(font);
  EXPECT_EQ(1, destroyed);
  StealthReleaseDesignFont(nullptr);  // as hb_font_destroy: null is fine
}

namespace {

constexpr char kStealthCoverageLadderPref[] =
    "zoom.stealth.text.coverage_ladder";

struct RestoreStealthCoverageLadder {
  ~RestoreStealthCoverageLadder() {
    mozilla::Preferences::ClearUser(kStealthCoverageLadderPref);
  }
};

}  // namespace

// The coverage of an A8 glyph mask is snapped to the declared ladder
// (SkScalerContext::getImage reaches this through the SkGlyph overload, which
// only adds the kA8 check): a mask with every one of the 256 levels ends with
// only the ladder's levels, each the nearest one, and 0 and 255 do not move.
// With the ladder empty (not declared) the mask is the rasteriser's own.
TEST(StealthGlyphCoverage, A8MaskIsOnTheLadder)
{
  RestoreStealthCoverageLadder restore;
  uint8_t original[256];
  for (int i = 0; i < 256; ++i) {
    original[i] = uint8_t(i);
  }

  // Negative control: nothing declared, the mask stays as it is.
  uint8_t mask[256];
  memcpy(mask, original, sizeof(mask));
  mozilla::gfx::StealthQuantiseGlyphCoverage(mask, 16, 16, 16);
  EXPECT_EQ(0, memcmp(mask, original, sizeof(mask)));

  mozilla::Preferences::SetCString(kStealthCoverageLadderPref,
                                   "0,85,170,255"_ns);
  const uint8_t ladder[] = {0, 85, 170, 255};
  mozilla::gfx::StealthQuantiseGlyphCoverage(mask, 16, 16, 16);
  for (int i = 0; i < 256; ++i) {
    int nearest = 256;
    for (uint8_t level : ladder) {
      nearest = std::min(nearest, abs(i - int(level)));
    }
    EXPECT_EQ(nearest, abs(i - int(mask[i]))) << i;
    bool onLadder = false;
    for (uint8_t level : ladder) {
      onLadder = onLadder || mask[i] == level;
    }
    EXPECT_TRUE(onLadder) << i;
  }
  EXPECT_EQ(0, mask[0]);
  EXPECT_EQ(255, mask[255]);
}
