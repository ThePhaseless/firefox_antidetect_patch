/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_STEALTHTEXTQUALITY_H
#define GFX_STEALTHTEXTQUALITY_H

// The Windows text quality and the ClearType parameters with the stealth
// engine on: declared, never asked of the host. Called from the hooks in
// gfxDWriteFonts.cpp (GetSystemTextQuality and
// gfxDWriteFont::UpdateClearTypeVars). Header-only on purpose:
// gfxDWriteFonts.cpp and its gtest are the only includers, and a header needs
// no line in gfx/thebes/moz.build.

#include <stdint.h>
#include <windows.h>
#include <dwrite.h>

#include "StealthDeclarationGate.h"
#include "mozilla/RefPtr.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "mozilla/gfx/2D.h"
#include "mozilla/gfx/StealthRefuse.h"

namespace mozilla {
namespace gfx {

// Not hooked, on purpose: GetSystemGDIGamma() in gfxDWriteFonts.cpp is stock
// Mozilla code and still reads SPI_GETFONTSMOOTHINGCONTRAST from the host
// (engine rule 7-bis). It only feeds the GDI-classic rendering settings
// (DWriteSettings::Get(true)), and canvas text never takes that road:
// CanvasRenderingContext2D sets allowForceGDIClassic = false on every font it
// uses. No page can read a pixel this value shapes.

/**
 * With the engine on, the text quality is DECLARED
 * (zoom.stealth.text.system_quality) and the host is never asked. It decides
 * two things a page reads: the antialiasing of canvas text (NONE, GRAY or
 * SUBPIXEL through GetSystemDefaultAAMode), and whether the declared ClearType
 * parameters apply at all (UpdateClearTypeVars reads them only under
 * CLEARTYPE_QUALITY). Asking SystemParametersInfo made the same binary draw
 * different text on a machine with ClearType off - an RDP session, a VM, a
 * server - which is engine rule 7-quater (70-known-bugs.md [B362]). The
 * declaration gate refuses a launch without it.
 *
 * Called only under StealthTextQualityDeclared() (the guard at the top of
 * GetSystemTextQuality): with the engine off the caller runs stock Firefox's
 * own SystemParametersInfo path. Only 0 (DEFAULT_QUALITY), 4
 * (ANTIALIASED_QUALITY) and 5 (CLEARTYPE_QUALITY) are accepted; anything else
 * refuses rather than asking the host.
 */
inline BYTE StealthDeclaredTextQuality() {
  const int32_t declared = StaticPrefs::zoom_stealth_text_system_quality();
  if (declared == DEFAULT_QUALITY || declared == ANTIALIASED_QUALITY ||
      declared == CLEARTYPE_QUALITY) {
    return BYTE(declared);
  }
  StealthRefuse(
      "stealth: zoom.stealth.text.system_quality is %d, not one of 0 "
      "(DEFAULT_QUALITY), 4 (ANTIALIASED_QUALITY), 5 (CLEARTYPE_QUALITY). "
      "Engine rule 7: a finite-domain value lives only in invisible_core, "
      "and a missing or malformed declaration refuses rather than asking "
      "the host.",
      int(declared));
}

/**
 * Is the ClearType state declared (engine on)? Asked by the guard of
 * GetSystemTextQuality, by StealthDWriteFactoryProxy below and by
 * StealthClearTypeParamsApply.
 *
 * DO NOT ASK THE MACHINE. The six values of UpdateClearTypeVars are read once
 * at startup and then stay fixed for the whole process, which makes them
 * exactly the kind of thing invisible_core declares - and the order there was
 * defaults -> SYSTEM -> prefs, so the system value sat in the MIDDLE and
 * survived whenever a pref was absent or out of range. That is an override
 * with a fallback, not a declaration, and it is the shape that let the codec
 * table look finished while leaking: on the development machine the host's
 * answer happens to be the one we want.
 *
 * Skipping the block leaves the hard-coded defaults (ClearType level 1.0,
 * contrast 1.0, gamma 2.2, RGB geometry, DEFAULT rendering mode). This comment
 * used to call them "the canonical Windows values". They are not: they are
 * stock Firefox's own starting point. An untuned Windows renders text at
 * DWrite's default gamma, measured 1.8 against the retail 151 (70-known-bugs.md
 * [B361]); 2.2 is no machine's default. With the engine on they are never what
 * a page sees: every one of them is declared (the declaration gate refuses a
 * launch without them), and the override in UpdateClearTypeVars always runs,
 * because the text quality it is gated on is declared as well
 * (StealthDeclaredTextQuality, [B362]). So these six numbers matter only with
 * the engine OFF, as stock Firefox. Note gamma 2.2 there against Skia's LINEAR
 * default on Linux (DrawTargetSkia.cpp:1850-1856) - that asymmetry is the
 * reason the two platforms rasterise glyph coverage differently, and it cannot
 * be closed while either side reads its host.
 *
 * With the engine on the declared parameters apply whatever the declared
 * quality (the condition of the prefs block in UpdateClearTypeVars is
 * `declared || SystemTextQuality() == CLEARTYPE_QUALITY`). Stock Firefox,
 * ClearType off, still renders with the system's DWrite parameters
 * (CreateRenderingParams), and the declared values stand for exactly those;
 * skipping them would leave the hard-coded 2.2 and 1.0 deciding grayscale text,
 * a compiled second value next to the declaration (engine rule 7, [B362]).
 */
inline bool StealthTextQualityDeclared() { return StealthEngineActive(); }

/**
 * The receiver of gfxDWriteFont::UpdateClearTypeVars' CreateRenderingParams
 * call, wrapped: with the ClearType state declared the call that would read the
 * host's DWrite defaults is never made and the answer is E_FAIL; otherwise it is
 * forwarded to the real factory, so the engine off is stock Firefox byte for
 * byte. The E_FAIL goes down the same road as a failed factory call in the
 * caller: its own `else` logs its gfxWarning, exactly as it always did with the
 * engine on. The receiver is wrapped, not the result, because the host is read
 * by the call itself.
 *
 * A template on the factory type so that a test can count the calls that reach
 * the host with a fake. operator-> returns the proxy itself, which lives until
 * the end of the full expression the hook sits in.
 */
template <typename F>
class StealthDWriteFactoryProxy {
 public:
  explicit StealthDWriteFactoryProxy(F* aFactory) : mFactory(aFactory) {}
  StealthDWriteFactoryProxy* operator->() { return this; }
  HRESULT CreateRenderingParams(IDWriteRenderingParams** aParams) {
    if (StealthTextQualityDeclared()) {
      return E_FAIL;
    }
    return mFactory->CreateRenderingParams(aParams);
  }

 private:
  F* mFactory;
};

template <typename F>
StealthDWriteFactoryProxy<F> StealthDWriteFactory(F* aFactory) {
  return StealthDWriteFactoryProxy<F>(aFactory);
}

template <typename F>
StealthDWriteFactoryProxy<F> StealthDWriteFactory(const RefPtr<F>& aFactory) {
  return StealthDWriteFactoryProxy<F>(aFactory.get());
}

/**
 * The condition of the ClearType prefs block of UpdateClearTypeVars: with the
 * engine on the declared parameters apply whatever the declared quality;
 * otherwise Mozilla's own condition (aStock: the system text quality is
 * CLEARTYPE_QUALITY).
 */
inline bool StealthClearTypeParamsApply(bool aStock) {
  return StealthTextQualityDeclared() || aStock;
}

}  // namespace gfx
}  // namespace mozilla

#endif  // GFX_STEALTHTEXTQUALITY_H
