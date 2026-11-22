/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The Windows text quality and ClearType parameters with the stealth engine on
// come from the declaration, never from the host ([B362] in the workbench's
// 70-known-bugs.md). The host is not touched: on a machine with ClearType on
// (the host answers CLEARTYPE_QUALITY), a declared ANTIALIASED_QUALITY that
// comes back as declared is the proof that SystemParametersInfo was not asked.

#include "gtest/gtest.h"

#include "gfxDWriteFonts.h"
#include "gfxPlatform.h"
#include "mozilla/Preferences.h"
#include "mozilla/gfx/gfxVars.h"

#include "StealthTextQuality.h"

using mozilla::Preferences;
using mozilla::gfx::gfxVars;

namespace {

const char* const kPrefs[] = {
    "zoom.stealth.fpp.hw_seed",
    "zoom.stealth.text.system_quality",
    "gfx.font_rendering.cleartype_params.gamma",
    "gfx.font_rendering.cleartype_params.enhanced_contrast",
};

// Back to stock Firefox, and the text vars recomputed, whatever the test did.
struct RestoreStock {
  ~RestoreStock() {
    for (const char* name : kPrefs) {
      Preferences::ClearUser(name);
    }
    gfxDWriteFont::UpdateSystemTextVars();
  }
};

}  // namespace

TEST(StealthTextQuality, TheDeclarationIsReadAndTheHostIsNot)
{
  gfxPlatform::GetPlatform();
  RestoreStock restore;
  Preferences::SetInt("zoom.stealth.fpp.hw_seed", 7);  // the engine on
  Preferences::SetInt("gfx.font_rendering.cleartype_params.gamma", 1800);
  Preferences::SetInt("gfx.font_rendering.cleartype_params.enhanced_contrast",
                      50);
  // DEFAULT_QUALITY, ANTIALIASED_QUALITY, CLEARTYPE_QUALITY.
  for (int32_t quality : {0, 4, 5}) {
    Preferences::SetInt("zoom.stealth.text.system_quality", quality);
    gfxDWriteFont::UpdateSystemTextVars();
    EXPECT_EQ(quality, gfxVars::SystemTextQuality()) << quality;
    // The declared parameters apply at EVERY quality: skipped outside
    // ClearType, the compiled 2.2 and 1.0 would decide grayscale text.
    EXPECT_FLOAT_EQ(1.8f, gfxVars::SystemTextGamma()) << quality;
    EXPECT_FLOAT_EQ(0.5f, gfxVars::SystemTextEnhancedContrast()) << quality;
  }
}

TEST(StealthTextQuality, WithTheEngineOffTheHostDecides)
{
  gfxPlatform::GetPlatform();
  RestoreStock restore;
  // Stock Firefox: a declaration left in the profile is not read.
  Preferences::SetInt("zoom.stealth.text.system_quality", 0);
  gfxDWriteFont::UpdateSystemTextVars();
  const int32_t stock = gfxVars::SystemTextQuality();
  EXPECT_TRUE(stock == 0 || stock == 4 || stock == 5) << stock;
  Preferences::SetInt("zoom.stealth.text.system_quality", 4);
  gfxDWriteFont::UpdateSystemTextVars();
  EXPECT_EQ(stock, gfxVars::SystemTextQuality());
}

namespace {

// A factory that counts the calls that reach it, standing for the host's
// DirectWrite.
struct CountingFactory {
  HRESULT CreateRenderingParams(IDWriteRenderingParams** aParams) {
    ++mCalls;
    *aParams = nullptr;
    return S_OK;
  }
  int mCalls = 0;
};

}  // namespace

// The call that reads the host's DirectWrite defaults is not made with the
// engine on: the answer is E_FAIL, which UpdateClearTypeVars handles as a failed
// factory (declared values only). With the engine off the call reaches the
// factory as in stock Firefox. The ClearType prefs block applies whatever the
// declared quality, and only with the engine on.
TEST(StealthTextQuality, TheRenderingParamsAreNotAskedOfTheHost)
{
  gfxPlatform::GetPlatform();
  RestoreStock restore;
  CountingFactory factory;
  RefPtr<IDWriteRenderingParams> params;

  // Engine off (the negative control).
  HRESULT hr = mozilla::gfx::StealthDWriteFactory(&factory)
                   ->CreateRenderingParams(getter_AddRefs(params));
  EXPECT_EQ(S_OK, hr);
  EXPECT_EQ(1, factory.mCalls);
  EXPECT_FALSE(mozilla::gfx::StealthClearTypeParamsApply(false));
  EXPECT_TRUE(mozilla::gfx::StealthClearTypeParamsApply(true));

  // Engine on.
  Preferences::SetInt("zoom.stealth.fpp.hw_seed", 7);
  factory.mCalls = 0;
  hr = mozilla::gfx::StealthDWriteFactory(&factory)
           ->CreateRenderingParams(getter_AddRefs(params));
  EXPECT_EQ(E_FAIL, hr);
  EXPECT_EQ(0, factory.mCalls);
  EXPECT_TRUE(mozilla::gfx::StealthClearTypeParamsApply(false));
  EXPECT_TRUE(mozilla::gfx::StealthClearTypeParamsApply(true));
}
