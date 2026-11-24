/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_STEALTHDESIGNFONTACCESS_H
#define GFX_STEALTHDESIGNFONTACCESS_H

// The design-space metrics of a gfxHarfBuzzShaper. gfxHarfBuzzShaper.h carries
// one line for them (`friend struct StealthDesignFontAccess;`) and one member
// (mDesignFont); everything else lives in StealthDesignMetrics.cpp. A struct
// and not three methods of the class so that the Mozilla header holds no
// declaration of ours beyond those two lines. Cross-platform: the shaper is
// shared by every backend, only the FreeType one asks for these values.

#include <stdint.h>

#include "harfbuzz/hb.h"

class gfxHarfBuzzShaper;

// The release of the design font, called with the member from the shaper's
// destructor, right after the shaping font's own hb_font_destroy. Takes the
// pointer (null is fine, as for hb_font_destroy). The release stays in the body
// of the destructor, at the moment it always had, and is not a RAII member:
// that would move it to the end of the member destruction.
void StealthReleaseDesignFont(hb_font_t* aFont);

struct StealthDesignFontAccess {
  // A second hb_font on the shaper's face, built on demand, used for nothing
  // but design-space metrics and never for shaping; owned by the shaper
  // (destroyed in its destructor). Null when the font has no usable unitsPerEm
  // or no face. Takes the shaper's mutex (recursive).
  static hb_font_t* GetFont(const gfxHarfBuzzShaper& aShaper);

  // Ink box of glyph aGID in FONT UNITS (hb_glyph_extents_t's own sign
  // convention). A glyph with no outline gives an empty box and true. False
  // only when there is no design font.
  static bool GlyphExtents(const gfxHarfBuzzShaper& aShaper, uint16_t aGID,
                           int32_t& aXBearing, int32_t& aYBearing,
                           int32_t& aWidth, int32_t& aHeight);

  // Advance of glyph aGID in FONT UNITS. False only when there is no design
  // font.
  static bool Advance(const gfxHarfBuzzShaper& aShaper, uint16_t aGID,
                      int32_t& aAdvance);
};

#endif  // GFX_STEALTHDESIGNFONTACCESS_H
