/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_STEALTHSYNTHETICBOLD_H
#define GFX_STEALTHSYNTHETICBOLD_H

// How a bold face the font does not have is made, the same on every OS: the rule of
// Firefox retail on Windows (gfxDWriteFontEntry::CreateFontInstance and
// gfxDWriteFont::gfxDWriteFont, gfx.font_rendering.directwrite.bold_simulation at its
// default, 1: "use DWrite simulation for installed fonts except COLR fonts, but not
// webfonts"):
//
//   an installed font (the faces of the bundle stand for them)
//       -> the rasteriser's simulation of bold: DWRITE_FONT_SIMULATIONS_BOLD on
//          Windows, idwr's kSimulationBold on both OSes for the ink, and the advance
//          idwr gives the simulated face (FontFace::GetDesignGlyphAdvances: d =
//          (unitsPerEm + 25) / 50 added to the advance of a glyph with ink). No
//          multi-strike, no FreeType embolden.
//   a webfont (@font-face, the page's own data) or a font with a COLR table
//       -> Gecko's multi-strike (gfxFont::mApplySyntheticBold): the glyphs are drawn
//          again at one-device-pixel offsets, the advance of every cluster grows by
//          GetSyntheticBoldOffset() (gfxFont::PostShapingFixup) and the font metrics
//          by the same amount (gfxDWriteFont::ComputeMetrics).
//
// The bundle's faces are built from data (mIsDataUserFont), which retail's installed
// fonts are not: left alone they took the webfont branch on Windows, and on Linux
// stock asked FC_EMBOLDEN, whose strength FreeType adds to every advance. A face of the
// bundle is one of the shared list's own faces (mShmemFace); a webfont never is.

#include "StealthDeclarationGate.h"
#include "gfxFont.h"
#include "gfxFontEntry.h"
#include "gfxFontUtils.h"

namespace mozilla {
namespace gfx {

// A face of the bundle: data like a webfont, but one of the shared list's faces.
inline bool StealthIsBundleFace(const gfxFontEntry& aEntry) {
  return aEntry.mIsDataUserFont && aEntry.mShmemFace && !aEntry.mIsLocalUserFont;
}

// What "IsDataUserFont" means on retail Windows: a webfont.
inline bool StealthIsWebfont(const gfxFontEntry& aEntry) {
  return aEntry.mIsDataUserFont && !StealthIsBundleFace(aEntry);
}

// The retail rule from its facts, so that it can be tested without a font:
// Gecko strikes the bold itself (true) or the rasteriser simulates it (false).
inline bool StealthMultistrikeBoldRule(bool aIsWebfont, bool aHasColr) {
  return aIsWebfont || aHasColr;
}

// With the engine on, a font asked for a bold it lacks: true when Gecko strikes it,
// false when the rasteriser simulates it. Stock (engine off, or no bold needed):
// nothing is decided here and the caller keeps what it had; see StealthBoldDecided.
inline bool StealthBoldDecided(gfxFontEntry* aFontEntry,
                               const gfxFontStyle* aStyle) {
  return StealthEngineActive() && aFontEntry && aStyle &&
         aStyle->NeedsSyntheticBold(aFontEntry);
}

inline bool StealthApplySyntheticBold(gfxFontEntry* aFontEntry,
                                      const gfxFontStyle* aStyle) {
  if (!StealthBoldDecided(aFontEntry, aStyle)) {
    return false;
  }
  const bool isWebfont = StealthIsWebfont(*aFontEntry);
  const bool hasColr =
      !isWebfont && aFontEntry->HasFontTable(TRUETYPE_TAG('C', 'O', 'L', 'R'));
  return StealthMultistrikeBoldRule(isWebfont, hasColr);
}

// The rasteriser simulates the bold (the retail rule, installed font, no COLR).
inline bool StealthBoldSimulated(gfxFontEntry* aFontEntry,
                                 const gfxFontStyle* aStyle) {
  return StealthBoldDecided(aFontEntry, aStyle) &&
         !StealthApplySyntheticBold(aFontEntry, aStyle);
}

// What gfxDWriteFont::ComputeMetrics widens when ApplySyntheticBold(): the space,
// the average character and the widest advance, and the zero and ideograph widths
// when the font has the glyph (negative: not found).
inline void StealthSyntheticBoldMetrics(gfxFloat aDelta,
                                        gfxFont::Metrics& aMetrics) {
  aMetrics.spaceWidth += aDelta;
  aMetrics.aveCharWidth += aDelta;
  aMetrics.maxAdvance += aDelta;
  if (aMetrics.zeroWidth > 0) {
    aMetrics.zeroWidth += aDelta;
  }
  if (aMetrics.ideographicWidth > 0) {
    aMetrics.ideographicWidth += aDelta;
  }
}

}  // namespace gfx
}  // namespace mozilla

#endif  // GFX_STEALTHSYNTHETICBOLD_H
