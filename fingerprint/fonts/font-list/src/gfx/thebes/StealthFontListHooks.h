/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_STEALTHFONTLISTHOOKS_H
#define GFX_STEALTHFONTLISTHOOKS_H

// The functions the hooks of fingerprint/fonts/font-list call from
// gfxPlatformFontList.cpp, gfxDWriteFontList.cpp and gfxFcPlatformFontList.cpp.
// The Mozilla files keep one line per hook (the call and, in a guard, the
// return); what each hook decides, and why, is written next to the function
// here and in the other files of the folder (StealthFcFontList.*, and the
// bundle-only helpers in StealthBundleFontList.*). The comments the hooks
// used to carry in the Mozilla files are in FEATURE.md.
//
// Every function takes the font list (`this` of the hook) and, where the hook
// wraps a Mozilla expression, the value Mozilla computed. Each has a pure core
// `...Core(bool aBundleOnly, ...)` that decides from plain values: the
// font list is bundle-only in every build, so the core is what lets a test see
// the answer for aBundleOnly = false, the answer of stock Firefox.

#include <stdint.h>

#include <string>

#include "SharedFontList.h"
#include "StealthBundleFontList.h"
#include "mozilla/intl/UnicodeScriptCodes.h"
#include "nsString.h"
#include "nsTArray.h"

class gfxFontEntry;
class gfxPlatformFontList;
class nsIHandleReportCallback;
class nsISupports;
enum class FontPresentation : uint8_t;  // defined in gfxPlatform.h, same type
struct IDWriteFontCollection;

#ifdef XP_WIN
namespace mozilla::gfx {
class UnscaledFontDWrite;
}  // namespace mozilla::gfx
#endif

// ReadCMAP: whether the entry's character map goes into the shared font list.
// aMozilla is Mozilla's own term (`!IsUserFont()`). A bundled face is built
// from file data, so IsUserFont() is true for it and Mozilla's term rejects the
// whole list; a face made for src:local() is never published.
bool StealthPublishCharacterMapCore(bool aMozilla, bool aBundleOnly,
                                    bool aIsDataUserFont,
                                    bool aIsLocalUserFont);
bool StealthPublishCharacterMap(const gfxFontEntry* aEntry, bool aMozilla);

// GetFacesInitDataForFamily: under bundle-only the faces of the family come
// from the manifest and no platform query runs. True when it appended them.
bool StealthFacesForFamilyCore(
    bool aBundleOnly, const nsACString& aFamilyName,
    nsTArray<mozilla::fontlist::Face::InitData>& aFaces);
bool StealthFacesForFamily(
    const gfxPlatformFontList* aList, const mozilla::fontlist::Family* aFamily,
    nsTArray<mozilla::fontlist::Face::InitData>& aFaces);

// The host substitute tables (registry FontSubstitutes and DirectWrite's own
// list): skipped when the manifest carries the aliases
// (StealthBundleFontList::UsesHostSubstitutes). Called at the top of
// GetDirectWriteSubstitutes and GetFontSubstitutes, which are called from four
// places in the tag and all four had the same condition.
bool StealthSkipsHostSubstitutesCore(bool aBundleOnly);
bool StealthSkipsHostSubstitutes(const gfxPlatformFontList* aList);

// InitFontListForPlatform: "no font found" is the expected state when the
// list is the bundle and nothing else (aMozilla: the count equals the bundled
// count).
bool StealthNoFontsFoundCore(bool aBundleOnly, bool aMozilla);
bool StealthNoFontsFound(const gfxPlatformFontList* aList, bool aMozilla);

// GetFontsFromCollection: the system collection is not enumerated under
// bundle-only; the bundled collection still is (its other caller).
bool StealthSkipsHostCollectionCore(bool aBundleOnly, const void* aCollection,
                                    const void* aSystemCollection);
bool StealthSkipsHostCollection(const gfxPlatformFontList* aList,
                                const IDWriteFontCollection* aCollection,
                                const IDWriteFontCollection* aSystemCollection);

// CreateBundledFontsCollection: no platform collection of the bundled files in
// a content process while the shared list is built
// (StealthBundleFontList::SkipsPlatformBundledCollection).
bool StealthSkipsBundledCollection(const gfxPlatformFontList* aList);

// CreateFontFace: the face index of a face of a .ttc (0 for every other font);
// aMozillaIndex is Mozilla's own value, the literal 0.
uint32_t StealthFaceIndex(uint16_t aBundleFaceIndex, uint32_t aMozillaIndex);

#ifdef XP_WIN
// CreateFontInstance: the bundle path travels with the unscaled font, so
// GetFontDescriptor does not fail and WebRender is given the path and not the
// bytes of the font ([B154]). aFont is the object Mozilla just built; an empty
// aPath (every other font) leaves it as Mozilla made it. Returns aFont.
mozilla::gfx::UnscaledFontDWrite* StealthWithBundlePath(
    const std::wstring& aPath, mozilla::gfx::UnscaledFontDWrite* aFont);
#endif

// AddGenericFonts (fontconfig): the CSS generics are resolved by the base
// class under bundle-only. aMozilla is Mozilla's `usePrefFontList`.
bool StealthUsePrefFontListCore(bool aMozilla, bool aBundleOnly);
bool StealthUsePrefFontList(const gfxPlatformFontList* aList, bool aMozilla);

// GlobalFontFallback: the cmap route is always taken under bundle-only.
// aMozilla is Mozilla's `IsFontFamilyWhitelistActive()`.
bool StealthUseCmapsCore(bool aMozilla, bool aBundleOnly);
bool StealthUseCmaps(const gfxPlatformFontList* aList, bool aMozilla);

// A fallback search may skip a family whose character maps are not loaded
// yet, and start an async load, only when the async pref is on and the font
// list is not bundle-only: aPref is Mozilla's
// StaticPrefs::gfx_font_rendering_fallback_async(). The one predicate both
// sites that ask use (GlobalFontFallback, gfxFontGroup::FindFallbackFaceForChar).
bool StealthMayDeferCmapLoadingCore(bool aBundleOnly, bool aPref);
bool StealthMayDeferCmapLoading(const gfxPlatformFontList* aList, bool aPref);

// CommonFontFallback: Mozilla has just filled aOut from the platform; under
// bundle-only, when the manifest carries a fallback table, aOut becomes the
// manifest's list, in its order.
void StealthReplaceCommonFallbackFontsCore(
    bool aBundleOnly, uint32_t aCh, mozilla::intl::Script aRunScript,
    FontPresentation aPresentation, nsTArray<const char*>& aOut);
void StealthReplaceCommonFallbackFonts(const gfxPlatformFontList* aList,
                                       uint32_t aCh,
                                       mozilla::intl::Script aRunScript,
                                       FontPresentation aPresentation,
                                       nsTArray<const char*>& aOut);

// FindAndAddFamiliesLocked, ResolveGenericFontNames, ResolveEmojiFontNames:
// the overloads of the bundle-only functions of StealthBundleFontList.h that
// read the flag from the font list.
void StealthApplyAlias(const gfxPlatformFontList* aList, nsACString& aKey);
void StealthPrependDeclaredGeneric(const gfxPlatformFontList* aList,
                                   mozilla::StyleGenericFontFamily aGeneric,
                                   const char* aLang,
                                   nsTArray<nsCString>& aFamilies);
void StealthPrependEmojiFamily(const gfxPlatformFontList* aList,
                               nsTArray<nsCString>& aFamilies);

// MemoryReporter::CollectReports: the bundled font files, with the report
// function of this file.
void StealthReportBundleFiles(nsIHandleReportCallback* aHandleReport,
                              nsISupports* aData);

#endif  // GFX_STEALTHFONTLISTHOOKS_H
