/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The declared content origin (gfx::StealthDeclaredOriginShift), which
// mozInnerScreenX/Y and every mouse event's screenX/Y follow. A window in
// fullscreen is the declared screen: its content starts at (0, 0), as on
// retail. Before 2026-11-01 the main window kept the maximized window's 85
// device pixels of UI after requestFullscreen().

#include <cmath>
#include <vector>

#include "StealthDeclarationGate.h"
#include "Units.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "mozilla/ScopeExit.h"

using namespace mozilla;

namespace {

constexpr int32_t kAuPerDevPx = 60;
const char* const kPrefs[] = {
    "zoom.stealth.fpp.hw_seed",
    "zoom.stealth.screen.frame_border",
    "zoom.stealth.screen.maximized_ui",
    "zoom.stealth.screen.popup_ui",
    "zoom.stealth.screen.popup_position",
    "zoom.stealth.screen.ui_normal",
    "zoom.stealth.screen.ui_compact",
    "zoom.stealth.screen.compact_below_css",
    "zoom.stealth.screen.restored_position",
    "zoom.stealth.screen.min_inner_width_css",
    "zoom.stealth.screen.min_inner_height_css",
};

// A SYNTHETIC window frame, not a retail measurement: the values at 100% the
// first-resize measurements were taken with, plus popup values. In the order of
// StealthWindowFrame: border, maximizedUi, popupUi, popupPosition, uiNormal,
// uiCompact, compactBelowCss, restoredPosition, minInnerWidthCss,
// minInnerHeightCss.
const gfx::StealthWindowFrame kSyntheticFrame = {8,  85,  62,  26, 85,
                                                 73, 720, 4,   500, 120};

// The synthetic work area, in device pixels, at 100%.
constexpr int32_t kSyntheticAvailWidth = 1920;
constexpr int32_t kSyntheticAvailHeight = 1032;

// The declared frame, the engine on.
void DeclareFrame(const gfx::StealthWindowFrame& aFrame) {
  Preferences::SetInt(kPrefs[0], 7);
  Preferences::SetInt(kPrefs[1], aFrame.mBorder);
  Preferences::SetInt(kPrefs[2], aFrame.mMaximizedUi);
  Preferences::SetInt(kPrefs[3], aFrame.mPopupUi);
  Preferences::SetInt(kPrefs[4], aFrame.mPopupPosition);
  Preferences::SetInt(kPrefs[5], aFrame.mUiNormal);
  Preferences::SetInt(kPrefs[6], aFrame.mUiCompact);
  Preferences::SetInt(kPrefs[7], aFrame.mCompactBelowCss);
  Preferences::SetInt(kPrefs[8], aFrame.mRestoredPosition);
  Preferences::SetInt(kPrefs[9], aFrame.mMinInnerWidthCss);
  Preferences::SetInt(kPrefs[10], aFrame.mMinInnerHeightCss);
}

void Declare() { DeclareFrame(kSyntheticFrame); }

nsPoint Declared(const Maybe<LayoutDeviceIntPoint>& aPopup, bool aFullscreen) {
  // A real origin of zero: the shift is then the declared origin itself.
  const Maybe<nsPoint> shift = gfx::StealthDeclaredOriginShift(
      nsPoint(0, 0), aPopup, Nothing(), aFullscreen, kAuPerDevPx);
  EXPECT_TRUE(shift);
  return shift ? *shift : nsPoint(-1, -1);
}

}  // namespace

TEST(StealthWindowGeometry, FullscreenContentStartsAtTheScreenOrigin)
{
  auto restore = MakeScopeExit([] {
    for (const char* pref : kPrefs) {
      Preferences::ClearUser(pref);
    }
  });
  Declare();
  // The main window in fullscreen: no UI above the content.
  EXPECT_EQ(Declared(Nothing(), true), nsPoint(0, 0));
  // A popup in fullscreen too, wherever it was.
  EXPECT_EQ(Declared(Some(LayoutDeviceIntPoint(300, 200)), true),
            nsPoint(0, 0));
}

TEST(StealthWindowGeometry, OutsideFullscreenNothingChanges)
{
  auto restore = MakeScopeExit([] {
    for (const char* pref : kPrefs) {
      Preferences::ClearUser(pref);
    }
  });
  Declare();
  // The maximized main window: the UI height below the screen top.
  EXPECT_EQ(Declared(Nothing(), false), nsPoint(0, 85 * kAuPerDevPx));
  // A popup: a border in, the popup UI down from where it really is.
  EXPECT_EQ(Declared(Some(LayoutDeviceIntPoint(300, 200)), false),
            nsPoint((300 + 8) * kAuPerDevPx, (200 + 62) * kAuPerDevPx));
  // The shift is relative to the real origin, so frames keep their offset.
  const Maybe<nsPoint> shift = gfx::StealthDeclaredOriginShift(
      nsPoint(10 * kAuPerDevPx, 20 * kAuPerDevPx), Nothing(), Nothing(), true,
      kAuPerDevPx);
  ASSERT_TRUE(shift);
  EXPECT_EQ(*shift, nsPoint(-10 * kAuPerDevPx, -20 * kAuPerDevPx));
}

// An out-of-process iframe that starts before the parent sent its dimensions
// has a real outer size of 0x0, and inner 0x0 with it. Retail answers 0x0 for
// outerWidth/outerHeight there; the declared window (1936x1048) only stands in
// for a real window that has a size. Before this the declaration was put over
// the 0x0, and a page read outer 1936x1048 around inner 0x0.
TEST(StealthWindowGeometry, ARealZeroOuterSizeStaysZero)
{
  EXPECT_FALSE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(0, 0)));
}

TEST(StealthWindowGeometry, AnyOtherRealOuterSizeIsStillDeclared)
{
  // The states outside the zero one are unchanged: the declaration replaces
  // the real size, whatever it is (a headless widget, a popup, a main window).
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(1280, 1024)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(500, 400)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(1, 1)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(0, 600)));
  EXPECT_TRUE(gfx::StealthOuterSizeIsDeclared(LayoutDeviceIntSize(800, 0)));
}

// The MAIN window after Page.setViewportSize (gfx::StealthWindowState). Retail
// restores the window on that resize: it sits at the restored position, its
// outer size is what Juggler's resizeBy makes of it, and the UI density is
// decided again from the new chrome height. Until the state existed the page
// read the MAXIMIZED window: outer 1936x1048 around inner 390x844, screenX -8,
// content origin (0, 85).

namespace {

// One window: the work area in device pixels at a scale, and the frame the
// core declares for it.
struct Scenario {
  float mScale;
  int32_t mAvailWidth;
  int32_t mAvailHeight;
  gfx::StealthWindowFrame mFrame;
};

// The maximized window as StealthDeclaredMaximizedWindow builds it: a border
// off the screen on every side around the work area.
LayoutDeviceIntRect MaximizedOf(const Scenario& aScenario) {
  const int32_t b = aScenario.mFrame.mBorder;
  return LayoutDeviceIntRect(-b, -b, aScenario.mAvailWidth + 2 * b,
                             aScenario.mAvailHeight + 2 * b);
}

// The content area of that maximized window in CSS pixels, rounded as Gecko
// rounds: the inner size a page reads unresized.
CSSIntSize MaximizedContentOf(const Scenario& aScenario) {
  const gfx::StealthWindowFrame& f = aScenario.mFrame;
  const LayoutDeviceIntSize device(aScenario.mAvailWidth,
                                   aScenario.mAvailHeight - f.mMaximizedUi);
  return gfx::RoundedToInt(device / CSSToLayoutDeviceScale(aScenario.mScale));
}

// The state after a resize from the window the state describes: the inner size
// goes from aFrom to aTo.
gfx::StealthWindowState Resize(const Scenario& aScenario,
                               const gfx::StealthWindowState& aState,
                               const CSSIntSize& aFrom, const CSSIntSize& aTo) {
  return gfx::StealthNextWindowState(aState, aFrom, aTo, MaximizedOf(aScenario),
                                     aScenario.mFrame, aScenario.mScale);
}

// The first Page.setViewportSize: from the maximized window.
gfx::StealthWindowState FirstResize(const Scenario& aScenario,
                                    const CSSIntSize& aTo) {
  return Resize(aScenario, gfx::StealthWindowState(),
                MaximizedContentOf(aScenario), aTo);
}

CSSIntSize OuterCss(const gfx::StealthWindowState& aState,
                    const Scenario& aScenario) {
  const Maybe<LayoutDeviceIntRect> rect =
      gfx::StealthRestoredWindowRect(aState, aScenario.mFrame);
  EXPECT_TRUE(rect);
  return rect ? gfx::RoundedToInt(rect->Size() /
                                  CSSToLayoutDeviceScale(aScenario.mScale))
              : CSSIntSize();
}

const Scenario kSynthetic100 = {1.0f, kSyntheticAvailWidth,
                                kSyntheticAvailHeight, kSyntheticFrame};

}  // namespace

TEST(StealthWindowGeometry, AnInnerSizeWithNoContentYetKeepsTheState)
{
  // The synced inner size is 0x0 until the first layout: the window has not
  // been sized and is still the maximized one.
  for (const CSSIntSize& inner :
       {CSSIntSize(0, 0), CSSIntSize(0, 844), CSSIntSize(390, 0)}) {
    const gfx::StealthWindowState state = Resize(
        kSynthetic100, gfx::StealthWindowState(), CSSIntSize(0, 0), inner);
    EXPECT_FALSE(state.mRestored) << inner.width << "x" << inner.height;
  }
  // A restored window stays what it was too.
  const gfx::StealthWindowState restored =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(restored.mRestored);
  EXPECT_EQ(Resize(kSynthetic100, restored, CSSIntSize(390, 844),
                   CSSIntSize(0, 0)),
            restored);
  // And an inner size that did not change.
  EXPECT_EQ(Resize(kSynthetic100, restored, CSSIntSize(390, 844),
                   CSSIntSize(390, 844)),
            restored);
}

TEST(StealthWindowGeometry, TheMaximizedContentIsTheMaximizedWindow)
{
  // Synthetic frame, at 100% and at 125% (where the content size rounds).
  for (float scale : {1.0f, 1.25f}) {
    const Scenario s = {scale, kSyntheticAvailWidth, kSyntheticAvailHeight,
                        kSyntheticFrame};
    const CSSIntSize content = MaximizedContentOf(s);
    EXPECT_FALSE(
        Resize(s, gfx::StealthWindowState(), CSSIntSize(1, 1), content)
            .mRestored)
        << "scale " << scale;
    // One CSS pixel less on either side is no longer the maximized content.
    EXPECT_TRUE(Resize(s, gfx::StealthWindowState(), content,
                       CSSIntSize(content.width - 1, content.height))
                    .mRestored)
        << "scale " << scale;
    EXPECT_TRUE(Resize(s, gfx::StealthWindowState(), content,
                       CSSIntSize(content.width, content.height - 1))
                    .mRestored)
        << "scale " << scale;
  }
}

// RED on the old behaviour: a 390x844 content area inside the maximized
// declaration answered the maximized outer size (1936x1048 at 100%).
TEST(StealthWindowGeometry, ASmallContentAreaIsNotTheMaximizedWindow)
{
  const gfx::StealthWindowState state =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(state.mRestored);
  EXPECT_NE(state.mOuter, MaximizedOf(kSynthetic100).Size());
}

// The way back to the maximized content size: retail does not maximize a
// restored window again. It stays restored, and the outer size goes through
// the same resize as any other (synthetic frame at 100%: a 1920x947 content
// area is a 1936x1040 window, not the 1936x1048 maximized one).
TEST(StealthWindowGeometry, ARestoredWindowIsNeverMaximizedAgain)
{
  const gfx::StealthWindowState restored =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(restored.mRestored);
  const gfx::StealthWindowState back =
      Resize(kSynthetic100, restored, CSSIntSize(390, 844),
             MaximizedContentOf(kSynthetic100));
  EXPECT_TRUE(back.mRestored);
  EXPECT_EQ(back.mOuter, LayoutDeviceIntSize(1936, 1040));
  EXPECT_NE(back.mOuter, MaximizedOf(kSynthetic100).Size());
}

TEST(StealthWindowGeometry, TheFirstResizeNeverGoesUnderTheMinimumWidth)
{
  // 390 CSS pixels wide is under the 500 the chrome needs: the window is 500
  // plus a border on each side, and a wider content area is that plus the
  // borders.
  const gfx::StealthWindowState narrow =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  EXPECT_EQ(narrow.mOuter.width, 500 + 2 * 8);
  const gfx::StealthWindowState wide =
      FirstResize(kSynthetic100, CSSIntSize(800, 600));
  EXPECT_EQ(wide.mOuter.width, 800 + 2 * 8);
  // And the same at 1.5, rounded through device pixels.
  const Scenario s = {1.5f, 1600, 1128, {11, 127, 106, 4, 127, 109, 720, 4, 500, 120}};
  EXPECT_EQ(FirstResize(s, CSSIntSize(390, 630)).mOuter.width, 750 + 2 * 11);
}

// The first resize, from the maximized window: the outer height is the new
// height, the bar of the MAXIMIZED window and the borders, in CSS rounding.
TEST(StealthWindowGeometry, TheFirstResizeUsesTheMaximizedBar)
{
  const gfx::StealthWindowState state =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  ASSERT_TRUE(state.mRestored);
  EXPECT_EQ(state.mOuter, LayoutDeviceIntSize(516, 844 + 85 + 2 * 8));
  EXPECT_FALSE(state.mCompact);
}

// The second resize, from a restored window: one border fewer, because the top
// border the maximized window kept off the screen is already inside the window.
// The bar is the one of the density the window has before the resize.
TEST(StealthWindowGeometry, TheSecondResizeCountsOneBorderLess)
{
  const CSSIntSize first(390, 844);
  const gfx::StealthWindowState one = FirstResize(kSynthetic100, first);
  ASSERT_TRUE(one.mRestored);

  // The same height again.
  const gfx::StealthWindowState same = Resize(
      kSynthetic100, one, CSSIntSize(390, 600), first);
  ASSERT_TRUE(same.mRestored);
  EXPECT_EQ(same.mOuter.height, 844 + 85 + 8);

  // A smaller one: the outer height follows, the width stays at the minimum.
  const gfx::StealthWindowState two =
      Resize(kSynthetic100, one, first, CSSIntSize(390, 700));
  ASSERT_TRUE(two.mRestored);
  EXPECT_EQ(two.mOuter, LayoutDeviceIntSize(516, 700 + 85 + 8));
}

// The density is decided again after the resize: the outer size comes from the
// bar BEFORE, the content top from the bar AFTER.
TEST(StealthWindowGeometry, TheDensityFlipsAfterTheResize)
{
  // Synthetic frame at 100%: 600 CSS pixels of content is a chrome under 720.
  const gfx::StealthWindowState state =
      FirstResize(kSynthetic100, CSSIntSize(390, 600));
  ASSERT_TRUE(state.mRestored);
  // The outer height came from the maximized (normal) bar, 85.
  EXPECT_EQ(state.mOuter.height, 600 + 85 + 2 * 8);
  EXPECT_TRUE(state.mCompact);
  // The content top is the compact bar below the window top.
  const Maybe<LayoutDeviceIntPoint> origin =
      gfx::StealthRestoredContentOrigin(state, kSyntheticFrame);
  ASSERT_TRUE(origin);
  EXPECT_EQ(origin->y, 4 + 73);

  // The window that stays tall keeps the normal bar.
  const gfx::StealthWindowState tall =
      FirstResize(kSynthetic100, CSSIntSize(390, 844));
  EXPECT_FALSE(tall.mCompact);
  EXPECT_EQ(gfx::StealthRestoredContentOrigin(tall, kSyntheticFrame)->y,
            4 + 85);
}

TEST(StealthWindowGeometry, TheWindowStateRoundTripsThroughItsField)
{
  // The maximized state is the field's default.
  EXPECT_EQ(gfx::StealthPackWindowState(gfx::StealthWindowState()), 0u);
  EXPECT_FALSE(gfx::StealthUnpackWindowState(0).mRestored);
  for (const bool compact : {false, true}) {
    gfx::StealthWindowState state;
    state.mRestored = true;
    state.mCompact = compact;
    state.mOuter = LayoutDeviceIntSize(1626, 1130);
    const gfx::StealthWindowState back =
        gfx::StealthUnpackWindowState(gfx::StealthPackWindowState(state));
    EXPECT_EQ(back, state);
  }
}

// outerWidth/outerHeight, screenX/screenY and the content origin
// (mozInnerScreenX/Y, event screenX - clientX) all read the ONE state: the
// content sits at the restored position plus the border and the bar, and the
// window around it is the state's outer size.
TEST(StealthWindowGeometry, EveryRestoredValueDerivesFromTheSameState)
{
  auto restore = MakeScopeExit([] {
    for (const char* pref : kPrefs) {
      Preferences::ClearUser(pref);
    }
  });
  Declare();
  const Maybe<gfx::StealthWindowFrame> declared =
      gfx::StealthDeclaredWindowFrame();
  ASSERT_TRUE(declared);
  const gfx::StealthWindowFrame& frame = *declared;

  for (float scale : {1.0f, 1.25f, 1.5f, 2.0f}) {
    const Scenario s = {scale, kSyntheticAvailWidth, kSyntheticAvailHeight,
                        frame};
    const gfx::StealthWindowState state =
        FirstResize(s, CSSIntSize(390, 844));
    ASSERT_TRUE(state.mRestored) << "scale " << scale;

    // outerWidth/outerHeight and screenX/screenY as the page reads them.
    const Maybe<LayoutDeviceIntRect> rect =
        gfx::StealthRestoredWindowRect(state, frame);
    ASSERT_TRUE(rect) << "scale " << scale;
    EXPECT_EQ(rect->Size(), state.mOuter) << "scale " << scale;
    EXPECT_EQ(rect->TopLeft(), LayoutDeviceIntPoint(frame.mRestoredPosition,
                                                    frame.mRestoredPosition));
    EXPECT_NE(rect->TopLeft(), MaximizedOf(s).TopLeft());

    // The content origin: the window's top-left plus the border and the bar,
    // and the one the origin shift declares (from a real origin of zero).
    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(state, frame);
    ASSERT_TRUE(origin) << "scale " << scale;
    const int32_t bar = state.mCompact ? frame.mUiCompact : frame.mUiNormal;
    EXPECT_EQ(*origin - rect->TopLeft(),
              LayoutDeviceIntPoint(frame.mBorder, bar));
    const Maybe<nsPoint> shift = gfx::StealthDeclaredOriginShift(
        nsPoint(0, 0), Nothing(), origin, false, kAuPerDevPx);
    ASSERT_TRUE(shift) << "scale " << scale;
    EXPECT_EQ(*shift, nsPoint(origin->x * kAuPerDevPx, origin->y * kAuPerDevPx))
        << "scale " << scale;
  }
}

// What retail Windows 11 answers after the FIRST Page.setViewportSize, one row
// per measured case: the declaration the core makes for the panel and the
// scale, the size asked for, and the CSS values a page reads.
namespace {

struct RetailFirstResize {
  float mScale;
  // The panel in device pixels; the work area is the panel less the 48 CSS
  // pixel taskbar at this scale.
  int32_t mPanelWidth;
  int32_t mPanelHeight;
  // The frame at this scale: border, normal and compact bar.
  int32_t mBorder;
  int32_t mUiNormal;
  int32_t mUiCompact;
  // Page.setViewportSize(width, height).
  CSSIntSize mInner;
  // What the page reads: outerWidth/outerHeight, screenX/screenY,
  // mozInnerScreenX/Y.
  CSSIntSize mOuter;
  CSSIntPoint mScreen;
  float mContentOriginX;
  float mContentOriginY;
};

const RetailFirstResize kRetailFirstResize[] = {
    {1.0f, 1920, 1080, 8, 85, 73, CSSIntSize(390, 844), CSSIntSize(516, 945),
     CSSIntPoint(4, 4), 12.0f, 89.0f},
    {1.25f, 1920, 1080, 9, 106, 91, CSSIntSize(390, 690), CSSIntSize(514, 789),
     CSSIntPoint(3, 3), 10.4f, 88.0f},
    {1.5f, 1600, 1200, 11, 127, 109, CSSIntSize(390, 630), CSSIntSize(515, 730),
     CSSIntPoint(3, 3), 10.0f, 87.333f},
    {1.5f, 1920, 1080, 11, 127, 109, CSSIntSize(390, 550), CSSIntSize(515, 638),
     CSSIntPoint(3, 3), 10.0f, 75.333f},
    {2.0f, 1600, 1200, 13, 170, 146, CSSIntSize(390, 430), CSSIntSize(513, 516),
     CSSIntPoint(2, 2), 8.5f, 75.0f},
};

// The declared scenario of a measured case: the maximized window's bar is the
// one of the density its work area has (compact under 720 CSS pixels).
Scenario ScenarioOf(const RetailFirstResize& aCase) {
  const int32_t taskbar = int32_t(floorf(48.0f * aCase.mScale + 0.5f));
  const int32_t availHeight = aCase.mPanelHeight - taskbar;
  const bool compact = float(availHeight) / aCase.mScale < 720.0f;
  return {aCase.mScale,
          aCase.mPanelWidth,
          availHeight,
          {aCase.mBorder, compact ? aCase.mUiCompact : aCase.mUiNormal, 72, 4,
           aCase.mUiNormal, aCase.mUiCompact, 720, 4, 500, 120}};
}

}  // namespace

TEST(StealthWindowGeometry, TheFirstResizeAtEveryDomainScale)
{
  for (const RetailFirstResize& r : kRetailFirstResize) {
    const Scenario s = ScenarioOf(r);
    const CSSToLayoutDeviceScale toDevice(r.mScale);
    const gfx::StealthWindowState state = FirstResize(s, r.mInner);
    ASSERT_TRUE(state.mRestored) << "scale " << r.mScale;

    const CSSIntSize outer = OuterCss(state, s);
    EXPECT_EQ(outer, r.mOuter) << "scale " << r.mScale << ", inner "
                               << r.mInner.width << "x" << r.mInner.height;

    const Maybe<LayoutDeviceIntRect> rect =
        gfx::StealthRestoredWindowRect(state, s.mFrame);
    ASSERT_TRUE(rect);
    EXPECT_EQ(gfx::RoundedToInt(rect->TopLeft() / toDevice), r.mScreen)
        << "scale " << r.mScale;

    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(state, s.mFrame);
    ASSERT_TRUE(origin);
    EXPECT_NEAR(float(origin->x) / r.mScale, r.mContentOriginX, 0.01)
        << "scale " << r.mScale;
    EXPECT_NEAR(float(origin->y) / r.mScale, r.mContentOriginY, 0.01)
        << "scale " << r.mScale;
  }
}

// The SECOND Page.setViewportSize, from a restored window, and the return to
// the maximized content size, as retail answers them: one sequence per panel,
// each starting from the first resize of the same row of kRetailFirstResize
// (first call, second call, return).
namespace {

struct RetailSequence {
  size_t mFirst;  // the row of kRetailFirstResize the window starts from
  // The second Page.setViewportSize and what the page reads after it.
  CSSIntSize mSecondInner;
  CSSIntSize mSecondOuter;
  float mSecondContentOriginY;  // mozInnerScreenY
  // The return to the maximized content size and what the page reads after it:
  // the window stays restored.
  CSSIntSize mReturnInner;
  CSSIntSize mReturnOuter;
  float mReturnContentOriginY;
};

const RetailSequence kRetailSequence[] = {
    {0, CSSIntSize(414, 896), CSSIntSize(516, 989), 89.0f,
     CSSIntSize(1920, 947), CSSIntSize(1936, 1040), 89.0f},
    {1, CSSIntSize(414, 640), CSSIntSize(514, 733), 88.0f,
     CSSIntSize(1536, 731), CSSIntSize(1550, 823), 88.0f},
    {2, CSSIntSize(414, 580), CSSIntSize(515, 672), 75.333f,
     CSSIntSize(1067, 667), CSSIntSize(1082, 746), 87.333f},
    {3, CSSIntSize(414, 500), CSSIntSize(515, 580), 75.333f,
     CSSIntSize(1280, 599), CSSIntSize(1295, 678), 75.333f},
    {4, CSSIntSize(414, 380), CSSIntSize(513, 460), 75.0f,
     CSSIntSize(800, 479), CSSIntSize(813, 558), 75.0f},
};

}  // namespace

TEST(StealthWindowGeometry, TheSecondResizeAtEveryDomainScale)
{
  for (const RetailSequence& r : kRetailSequence) {
    const RetailFirstResize& first = kRetailFirstResize[r.mFirst];
    const Scenario s = ScenarioOf(first);
    const gfx::StealthWindowState one = FirstResize(s, first.mInner);
    const gfx::StealthWindowState two =
        Resize(s, one, first.mInner, r.mSecondInner);
    ASSERT_TRUE(two.mRestored) << "scale " << first.mScale;
    EXPECT_EQ(OuterCss(two, s), r.mSecondOuter)
        << "scale " << first.mScale << ", panel " << first.mPanelWidth << "x"
        << first.mPanelHeight;
    // screenX/screenY do not move, the content origin follows the density the
    // window has after the resize.
    const Maybe<LayoutDeviceIntRect> rect =
        gfx::StealthRestoredWindowRect(two, s.mFrame);
    ASSERT_TRUE(rect);
    EXPECT_EQ(gfx::RoundedToInt(rect->TopLeft() /
                                CSSToLayoutDeviceScale(first.mScale)),
              first.mScreen);
    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(two, s.mFrame);
    ASSERT_TRUE(origin);
    EXPECT_NEAR(float(origin->x) / first.mScale, first.mContentOriginX, 0.01)
        << "scale " << first.mScale;
    EXPECT_NEAR(float(origin->y) / first.mScale, r.mSecondContentOriginY, 0.01)
        << "scale " << first.mScale;
  }
}

TEST(StealthWindowGeometry, TheWayBackAtEveryDomainScale)
{
  for (const RetailSequence& r : kRetailSequence) {
    const RetailFirstResize& first = kRetailFirstResize[r.mFirst];
    const Scenario s = ScenarioOf(first);
    // The size asked for is the maximized content.
    ASSERT_EQ(r.mReturnInner, MaximizedContentOf(s)) << "scale " << first.mScale;
    const gfx::StealthWindowState one = FirstResize(s, first.mInner);
    const gfx::StealthWindowState two =
        Resize(s, one, first.mInner, r.mSecondInner);
    const gfx::StealthWindowState back =
        Resize(s, two, r.mSecondInner, r.mReturnInner);
    // Retail does not maximize the window again.
    ASSERT_TRUE(back.mRestored) << "scale " << first.mScale;
    EXPECT_EQ(OuterCss(back, s), r.mReturnOuter)
        << "scale " << first.mScale << ", panel " << first.mPanelWidth << "x"
        << first.mPanelHeight;
    // The density is decided again from the new chrome height: at 1.5 on
    // 1600x1200 the window turned compact on the second call and is normal
    // again here.
    const Maybe<LayoutDeviceIntPoint> origin =
        gfx::StealthRestoredContentOrigin(back, s.mFrame);
    ASSERT_TRUE(origin);
    EXPECT_NEAR(float(origin->y) / first.mScale, r.mReturnContentOriginY, 0.01)
        << "scale " << first.mScale;
  }
}

// KNOWN DIVERGENCE FROM RETAIL, recorded here and not hidden. The engine's
// window state moves only when the top-level inner size changes
// (StealthInnerSizeWithWindowState runs from UpdateInnerSizeSpoofedForRFP). A
// second Page.setViewportSize to the SAME size leaves the inner size as it is,
// so that hook is not called and the state, and with it the outer size, stays
// what the first call made: 945. Retail's Juggler runs resizeBy again, with the
// delta trunc(844 + 85 - 937) = -8 from the restored window's 937-high chrome,
// and answers 937 (the second-call rule measured in round 4, one border
// fewer). The repeated same-size call itself was not measured; 937 follows from
// that rule. A same-size call cannot be told apart from no call at this hook.
// When this divergence is closed the two expectations below change, and
// kRetailOuterHeightOnARepeat becomes the expected value.
TEST(StealthWindowGeometry, ARepeatedResizeToTheSameSizeIsAKnownDivergence)
{
  // Retail's answer for a repeated setViewportSize(390, 844) at 100%
  // (deduced, not measured): 844 + the bar 85 + one border 8.
  constexpr int32_t kRetailOuterHeightOnARepeat = 844 + 85 + 8;
  static_assert(kRetailOuterHeightOnARepeat == 937);

  const Scenario s = ScenarioOf(kRetailFirstResize[0]);  // 100%, b 8, bar 85
  const CSSIntSize size(390, 844);
  const gfx::StealthWindowState one = FirstResize(s, size);
  ASSERT_TRUE(one.mRestored);
  EXPECT_EQ(OuterCss(one, s), CSSIntSize(516, 945));

  // The second call to the same size: the inner size does not change, the
  // state is returned as it was.
  const gfx::StealthWindowState again = Resize(s, one, size, size);
  EXPECT_EQ(again, one);
  EXPECT_EQ(OuterCss(again, s).height, 945);
  // The divergence: retail answers 937 here, the engine 945.
  EXPECT_NE(OuterCss(again, s).height, kRetailOuterHeightOnARepeat);
}
