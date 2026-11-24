/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthFontListHooks.h"

#include "SharedFontList-impl.h"
#include "gfxFontEntry.h"
#include "gfxPlatformFontList.h"
#include "mozilla/MemoryReporting.h"
#include "nsIMemoryReporter.h"
#include "nsTArray.h"
#include "nsXULAppAPI.h"

#ifdef XP_WIN
#  include "mozilla/gfx/UnscaledFontDWrite.h"
#endif

namespace fontlist = mozilla::fontlist;

// ---------------------------------------------------------------------------
// ReadCMAP (gfxDWriteFontList.cpp, gfxFcPlatformFontList.cpp).
// ---------------------------------------------------------------------------
// Every back end's ReadCMAP asked `!IsUserFont() && mShmemFace`, and that rule
// is WRONG for a bundled face: it is constructed from file data (so
// IsUserFont() is true) while being one of the list's own faces. The
// consequence was that no bundled face's cmap ever reached shared memory, and
// IsFullyInitialized() was false for every family forever. The hook keeps
// Mozilla's expression and its `&& mShmemFace`, and ORs in the bundled case.
// Under bundle-only every face in the list is instantiated from its bundle
// file, so mIsDataUserFont is true for all of them; publishing is what makes
// the family character map a real union instead of the deliberate empty
// "unusable family" map. A `src: local()` reference borrows the list's face
// but carries the @font-face rule's own weight/stretch/style ranges, so its
// cmap must not overwrite the slot the list's own face owns.
bool StealthPublishCharacterMapCore(bool aMozilla, bool aBundleOnly,
                                    bool aIsDataUserFont,
                                    bool aIsLocalUserFont) {
  return aMozilla || (aBundleOnly && aIsDataUserFont && !aIsLocalUserFont);
}

bool StealthPublishCharacterMap(const gfxFontEntry* aEntry, bool aMozilla) {
  return StealthPublishCharacterMapCore(
      aMozilla, gfxPlatformFontList::PlatformFontList()->StealthBundleOnly(),
      aEntry->mIsDataUserFont, aEntry->mIsLocalUserFont);
}

// ---------------------------------------------------------------------------
// GetFacesInitDataForFamily (gfxDWriteFontList.cpp).
// ---------------------------------------------------------------------------
// Bundle-only: the faces come from the manifest; no platform query runs. Same
// contract as the platforms' GetFacesInitDataForFamily.
bool StealthFacesForFamilyCore(
    bool aBundleOnly, const nsACString& aFamilyName,
    nsTArray<fontlist::Face::InitData>& aFaces) {
  if (!aBundleOnly) {
    return false;
  }
  StealthBundleFontList::Get()->GetFaces(aFamilyName, aFaces);
  return true;
}

bool StealthFacesForFamily(const gfxPlatformFontList* aList,
                           const fontlist::Family* aFamily,
                           nsTArray<fontlist::Face::InitData>& aFaces) {
  if (!aList->StealthBundleOnly()) {
    return false;
  }
  return StealthFacesForFamilyCore(
      true, aFamily->DisplayName().AsString(aList->SharedFontList()), aFaces);
}

// ---------------------------------------------------------------------------
// The substitute-table call sites (GetDirectWriteSubstitutes and
// GetFontSubstitutes: four calls in the tag, two in InitSharedFontListForPlatform
// and two in InitFontListForPlatform, all under the same condition).
// ---------------------------------------------------------------------------
// STEALTH: under bundle-only the aliases come from the manifest and are
// applied for every OS in gfxPlatformFontList::FindAndAddFamiliesLocked.
// These two build the platform's own table instead, and GetFontSubstitutes()
// reads it from the HOST REGISTRY (HKLM\...\FontSubstitutes), so the set of
// resolvable alias names varied by machine and existed on no other OS.
// Suppressed only when the manifest actually carries aliases; against a
// v1/v2 manifest the old behaviour stands (StealthBundleFontList::
// UsesHostSubstitutes decides it).
bool StealthSkipsHostSubstitutesCore(bool aBundleOnly) {
  return !StealthBundleFontList::UsesHostSubstitutes(aBundleOnly);
}

bool StealthSkipsHostSubstitutes(const gfxPlatformFontList* aList) {
  return StealthSkipsHostSubstitutesCore(aList->StealthBundleOnly());
}

// ---------------------------------------------------------------------------
// InitFontListForPlatform (gfxDWriteFontList.cpp): no host enumeration.
// ---------------------------------------------------------------------------
// Skip the host system-font enumeration entirely; only the bundled collection
// populates the list, so no host font enters. If no fonts were found,
// something is out of whack and Mozilla bails to the GDI backend: not when
// bundle-only, where Count()==kBundledCount is the expected, correct state.
bool StealthNoFontsFoundCore(bool aBundleOnly, bool aMozilla) {
  return aMozilla && !aBundleOnly;
}

bool StealthNoFontsFound(const gfxPlatformFontList* aList, bool aMozilla) {
  return StealthNoFontsFoundCore(aList->StealthBundleOnly(), aMozilla);
}

bool StealthSkipsHostCollectionCore(bool aBundleOnly, const void* aCollection,
                                    const void* aSystemCollection) {
  return aBundleOnly && aCollection == aSystemCollection;
}

bool StealthSkipsHostCollection(const gfxPlatformFontList* aList,
                                const IDWriteFontCollection* aCollection,
                                const IDWriteFontCollection* aSystemCollection) {
  return StealthSkipsHostCollectionCore(aList->StealthBundleOnly(),
                                        aCollection, aSystemCollection);
}

bool StealthSkipsBundledCollection(const gfxPlatformFontList* aList) {
  return StealthBundleFontList::SkipsPlatformBundledCollection(
      aList->SharedFontList() != nullptr, aList->StealthBundleOnly(),
      XRE_IsParentProcess());
}

// ---------------------------------------------------------------------------
// CreateFontFace and CreateFontInstance (gfxDWriteFontList.cpp).
// ---------------------------------------------------------------------------
// CreateFontFace passes the face index of the bundle entry instead of 0, so
// one face of a multi-face .ttc file is addressed by index; the member is 0 for
// every other font.
uint32_t StealthFaceIndex(uint16_t aBundleFaceIndex, uint32_t aMozillaIndex) {
  return aBundleFaceIndex ? aBundleFaceIndex : aMozillaIndex;
}

#ifdef XP_WIN
// STEALTH: the bundle path travels with the unscaled font. Without it,
// `GetFontDescriptor` fails and Gecko sends the font BYTES to WebRender; and it
// cannot work the path out by itself because our loader is not an
// `IDWriteLocalFontFileLoader`. For every other font the path is empty and the
// upstream behavior does not move. The path sits where Mozilla keeps the file
// name (UnscaledFontDWrite::StealthSeedFilePath, in
// StealthDWriteFontList.cpp). Known bug B154.
mozilla::gfx::UnscaledFontDWrite* StealthWithBundlePath(
    const std::wstring& aPath, mozilla::gfx::UnscaledFontDWrite* aFont) {
  if (!aPath.empty()) {
    aFont->StealthSeedFilePath(aPath);
  }
  return aFont;
}
#endif

// ---------------------------------------------------------------------------
// AddGenericFonts (gfxFcPlatformFontList.cpp) and GlobalFontFallback.
// ---------------------------------------------------------------------------
// AddGenericFonts: when pref fonts exist, Mozilla uses the standard pref font
// lookup. Stealth: also force this path when bundle-only, so the CSS generics
// resolve via the base-class ResolveGenericFontNames (StealthDeclaredGenericFont
// -> Windows fonts, through StealthPrependDeclaredGeneric) instead of
// fontconfig, which would map them to a host font we have dropped.
bool StealthUsePrefFontListCore(bool aMozilla, bool aBundleOnly) {
  return aMozilla || aBundleOnly;
}

bool StealthUsePrefFontList(const gfxPlatformFontList* aList, bool aMozilla) {
  return StealthUsePrefFontListCore(aMozilla, aList->StealthBundleOnly());
}

// GlobalFontFallback: under bundle-only it always takes the cmap route. The
// platform fallback engine (IDWriteFontFallback on Windows, the
// fontconfig-backed path on Linux) is consulted whenever a character is
// missing from the requested font, and it answers from the HOST, outside the
// families the manifest declares: a leak whether or not it explains a
// particular character. The cmap route searches OUR font list, in manifest
// order, and nothing else.
bool StealthUseCmapsCore(bool aMozilla, bool aBundleOnly) {
  return aMozilla || aBundleOnly;
}

bool StealthUseCmaps(const gfxPlatformFontList* aList, bool aMozilla) {
  return StealthUseCmapsCore(aMozilla, aList->StealthBundleOnly());
}

// The ONE place that decides whether a fallback search may skip a family whose
// character maps are not loaded yet, kicking off an async load and moving on.
// Two sites ask (GlobalFontFallback and gfxFontGroup::FindFallbackFaceForChar)
// and the answer has to be the same in both: skipping makes the result depend
// on what this process happens to have touched already, and that is observable
// in measureText widths. Never under bundle-only: measured 2026-08-07, the
// regional-indicator pair through "Arial" gave 52.63 on BOTH platforms when it
// was the first thing a fresh page measured, and 63.53 (Windows) vs 80.07
// (Linux) once other families had been measured first. 68 bundled families is
// a small enough list to search synchronously, and a deterministic answer is
// the whole point of moving fallback into the manifest.
bool StealthMayDeferCmapLoadingCore(bool aBundleOnly, bool aPref) {
  return aPref && !aBundleOnly;
}

bool StealthMayDeferCmapLoading(const gfxPlatformFontList* aList, bool aPref) {
  return StealthMayDeferCmapLoadingCore(aList->StealthBundleOnly(), aPref);
}

// ---------------------------------------------------------------------------
// CommonFontFallback (gfxPlatformFontList.cpp).
// ---------------------------------------------------------------------------
// The list that decides which font renders a character its own font lacks.
// Mozilla fills aOut from the platform; under bundle-only, when the manifest
// carries a fallback table (a v4 manifest), the manifest's names, in its order,
// replace what the platform wrote. The platform's list (the upstream one) is
// what stays when the manifest has no table. The names of the manifest are the
// same on every host; only the classification of the character stays in
// StealthCommonFallbackFromManifest (StealthBundleFontList.cpp).
void StealthReplaceCommonFallbackFontsCore(
    bool aBundleOnly, uint32_t aCh, mozilla::intl::Script aRunScript,
    FontPresentation aPresentation, nsTArray<const char*>& aOut) {
  AutoTArray<const char*, 8> manifest;
  if (StealthCommonFallbackFromManifest(aBundleOnly, aCh, aRunScript,
                                        aPresentation, manifest)) {
    aOut.Clear();
    aOut.AppendElements(manifest);
  }
}

void StealthReplaceCommonFallbackFonts(const gfxPlatformFontList* aList,
                                       uint32_t aCh,
                                       mozilla::intl::Script aRunScript,
                                       FontPresentation aPresentation,
                                       nsTArray<const char*>& aOut) {
  StealthReplaceCommonFallbackFontsCore(aList->StealthBundleOnly(), aCh,
                                        aRunScript, aPresentation, aOut);
}

// ---------------------------------------------------------------------------
// The overloads that read the flag from the font list.
// ---------------------------------------------------------------------------
void StealthApplyAlias(const gfxPlatformFontList* aList, nsACString& aKey) {
  StealthApplyAlias(aList->StealthBundleOnly(), aKey);
}

void StealthPrependDeclaredGeneric(const gfxPlatformFontList* aList,
                                   mozilla::StyleGenericFontFamily aGeneric,
                                   const char* aLang,
                                   nsTArray<nsCString>& aFamilies) {
  StealthPrependDeclaredGeneric(aList->StealthBundleOnly(), aGeneric, aLang,
                                aFamilies);
}

void StealthPrependEmojiFamily(const gfxPlatformFontList* aList,
                               nsTArray<nsCString>& aFamilies) {
  StealthPrependEmojiFamily(aList->StealthBundleOnly(), aFamilies);
}

// ---------------------------------------------------------------------------
// InitializeFamily (gfxPlatformFontList.cpp): the eager character-map loader
// of the bundle.
// ---------------------------------------------------------------------------
// Declared in gfxPlatformFontList.h as a member, because CreateFontEntry is a
// protected virtual of gfxPlatformFontList; the loop is
// ::StealthLoadMissingCharacterMaps (StealthBundleFontList.cpp), which has the
// reason it runs after BOTH branches of Mozilla's `if (!aFamily->IsInitialized())`.
void gfxPlatformFontList::StealthLoadMissingCharacterMaps(
    fontlist::FontList* aList, fontlist::Family* aFamily, bool aLoadCmaps) {
  ::StealthLoadMissingCharacterMaps(
      aList, aFamily, aLoadCmaps && mStealthBundleOnly,
      [&](fontlist::Face* aFace) { return CreateFontEntry(aFace, aFamily); });
}

// ---------------------------------------------------------------------------
// MemoryReporter::CollectReports (gfxPlatformFontList.cpp).
// ---------------------------------------------------------------------------
// The bundled font files are the largest single allocation this build makes;
// they are reported with a size function of this file (Mozilla's
// FontListMallocSizeOf is static to gfxPlatformFontList.cpp).
MOZ_DEFINE_MALLOC_SIZE_OF(StealthFontListMallocSizeOf)

void StealthReportBundleFiles(nsIHandleReportCallback* aHandleReport,
                              nsISupports* aData) {
  StealthReportBundleFiles(StealthFontListMallocSizeOf, aHandleReport, aData);
}
