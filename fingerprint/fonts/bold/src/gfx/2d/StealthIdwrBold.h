/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef MOZILLA_GFX_STEALTHIDWRBOLD_H_
#define MOZILLA_GFX_STEALTHIDWRBOLD_H_

#include <stdint.h>

namespace mozilla {
namespace gfx {

class UnscaledFont;

// DWRITE_GLYPH_METRICS, in design units.
struct StealthIdwrGlyphMetrics {
  int32_t mLeftSideBearing;
  uint32_t mAdvanceWidth;
  int32_t mRightSideBearing;
  int32_t mTopSideBearing;
  uint32_t mAdvanceHeight;
  int32_t mBottomSideBearing;
  int32_t mVerticalOriginY;
};

// IDWriteFontFace::GetDesignGlyphMetrics of the font's face made with
// DWRITE_FONT_SIMULATIONS_BOLD, from idwr: the advance and the box of a glyph with ink
// grow by (unitsPerEm + 25) / 50. The same code on every OS, so that the metrics Gecko
// takes of a simulated bold face are the ones DirectWrite gives Windows retail, and the
// ones the rasteriser (idwr's kSimulationBold) draws with. The default instance of the
// face the unscaled font gives; false when idwr cannot take the font.
bool StealthIdwrBoldDesignMetrics(UnscaledFont* aUnscaled, uint16_t aGlyph,
                                  StealthIdwrGlyphMetrics* aOut);

}  // namespace gfx
}  // namespace mozilla

#endif  // MOZILLA_GFX_STEALTHIDWRBOLD_H_
