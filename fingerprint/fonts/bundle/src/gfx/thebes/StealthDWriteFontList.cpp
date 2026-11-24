/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The DirectWrite half of the uniform bundle-only font list.
//
// gfxDWriteFontList.cpp keeps only hooks (STEALTH-HOOK markers); what they
// decide, and why, is written here, one section per hook, in the order of that
// file. The comments are the ones the hooks carried inline.
//
// ---------------------------------------------------------------------------
// CreateFontInstance: the bundle path travels with the unscaled font.
// ---------------------------------------------------------------------------
// STEALTH: the bundle path travels with the unscaled font. Without it,
// `GetFontDescriptor` fails and Gecko sends the font BYTES to WebRender;
// and it cannot work the path out by itself because our loader is not an
// `IDWriteLocalFontFileLoader`. For every other font it stays empty and the
// upstream behavior does not move.
//
// The member it comes from (gfxDWriteFontEntry::mBundleFilePath) was declared
// in gfxDWriteFontList.h with this comment:
//
// STEALTH: the path of the bundle file, empty for every other font.
//
// The byte-serving to WebRender goes through `UnscaledFontDWrite`, which
// cannot work the path out by itself: it takes it from an
// `IDWriteLocalFontFileLoader`, and our loader lends bytes in memory.
// Declaring it here is the only way to make it get there, and it keeps Gecko
// from sending the font BYTES - 65.9 MB in the parent, measured on Linux
// (known bug B154).
//
// ---------------------------------------------------------------------------
// ReadCMAP and CreateFontFace.
// ---------------------------------------------------------------------------
// ReadCMAP asks StealthPublishCharacterMap (StealthFontListHooks.cpp), which is
// true for a bundled face although it is built from file data. CreateFontFace passes
// mBundleFaceIndex instead of 0, so one face of a multi-face .ttc file is
// addressed by index; the member is 0 for every other font.
//
// ---------------------------------------------------------------------------
// ReadFaceNames.
// ---------------------------------------------------------------------------
// STEALTH [B317]: the bundle's faces are in no DirectWrite collection (their
// Index() is kNoIndex), so the lookup below can only fail for them.
// The base reads their names from the bundle file, on every platform.
//
// ---------------------------------------------------------------------------
// ReadFaceNamesForFamily.
// ---------------------------------------------------------------------------
// STEALTH [B317]: see ReadFaceNames above. Returning early here, as the
// collection lookup below did, left every bundled family without its
// src:local() names and its alternate family names.
//
// ---------------------------------------------------------------------------
// InitSharedFontListForPlatform: the family list.
// ---------------------------------------------------------------------------
// Uniform bundle: the family list is our manifest, not the DWrite collection
// enumeration (host fonts never enter). The collections above are still set up
// so mGDIInterop etc. stay valid; CreateFontEntry rasterizes each face
// straight from its bundle file. (The bundled collection is not enumerated
// either: see StealthBundleFontList::NeedsPlatformBundledCollection.)
//
// ---------------------------------------------------------------------------
// The substitute-table call sites (InitSharedFontListForPlatform has
// GetDirectWriteSubstitutes and GetFontSubstitutes; InitFontListForPlatform
// has the same two, apart).
// ---------------------------------------------------------------------------
// STEALTH: under bundle-only the aliases come from the manifest and are
// applied for every OS in gfxPlatformFontList::FindAndAddFamiliesLocked.
// These two build the platform's own table instead, and GetFontSubstitutes()
// reads it from the HOST REGISTRY (HKLM\...\FontSubstitutes) - so the set of
// resolvable alias names varied by machine (third-party software adds
// entries) and existed on no other OS. Measured 2026-08-07: "HELV" and
// "Small Fonts" resolved here and nowhere else, giving 8 fonts resolved on
// Windows against 6 on Linux.
//
// Note bundle-only made this WORSE rather than better: the pref
// gfx.windows-font-substitutes.always defaults false, i.e. "substitute only
// when the original family is absent", and with the family list cut to 72
// no alias name is ever present, so every possible substitution registered.
//
// Suppressed only when the manifest actually carries aliases; against a
// v1/v2 manifest the old behaviour stands, because removing the aliases
// outright would suppress a signal a real Windows Firefox does emit.
// (StealthBundleFontList::UsesHostSubstitutes decides it.)
//
// At the call sites in InitFontListForPlatform:
// STEALTH: see the note at the shared-list call site above - under
// bundle-only with a v3 manifest the aliases are ours, not the host's.
//
// ---------------------------------------------------------------------------
// InitFontListForPlatform: no host enumeration.
// ---------------------------------------------------------------------------
// Stealth bundle-only: skip the host system-font enumeration entirely; only
// the bundled collection (above) populates the list, so no host font enters.
//
// if no fonts found, something is out of whack, bail and use GDI backend
// (skip this when stealth bundle-only is active: we intentionally add no
// system fonts, so Count()==kBundledCount is the expected, correct state).

#include "gfxDWriteFontList.h"

#include <string>

#include "FontData.h"
#include "SharedFontList-impl.h"
#include "StealthBundleFontList.h"
#include "gfxDWriteCommon.h"
#include "gfxFontUtils.h"
#include "mozilla/RefPtr.h"
#include "nsString.h"
#include "nsThreadUtils.h"

using namespace mozilla;

// Uniform bundle path: instantiate the face straight from its bundle file (the
// manifest family list drives everything; the DWrite collection is not
// consulted). Like MakePlatformFont, but keeps multi-face .ttc files and
// addresses the wanted face by index (mBundleFaceIndex).
//
// A member and not a free function because it writes protected members of
// gfxDWriteFontEntry (mBundleFaceIndex, mBundleFilePath, mFaceType) and calls
// its protected InitializeFrom, all reachable from gfxDWriteFontList through
// the friend declaration in gfxDWriteFontEntry.
already_AddRefed<gfxFontEntry> gfxDWriteFontList::CreateStealthBundleFontEntry(
    fontlist::Face* aFace, const fontlist::Family* aFamily) {
  auto* bundle = StealthBundleFontList::Get();  // never null; it crashes first
  const nsCString file(aFace->mDescriptor.AsString(SharedFontList()));
  // Stealth: ONE copy of the file - the bundle cache's - lent to every face.
  // This used to be three copies per instantiation (the cache's, a per-call
  // nsTArray, and a malloc+memcpy) of which the DWrite stream then kept a
  // fourth permanently, PER FACE. On the 35.4 MB .ttc with two faces that was
  // 106 MB resident where 35.4 is enough, and the bundle is 218.7 MB over 126
  // files. The borrow is safe because the cache is immortal by construction:
  // StealthBundleFontList is deliberately leaked and never clears it.
  RefPtr<StealthBundleFontList::FileBlob> blob = bundle->GetFaceBlob(file);
  if (!blob || !blob->Length()) {
    return nullptr;
  }
  // The FontData only lends the cache's bytes (it never frees them), and
  // Mozilla's own CreateCustomFontFile makes the stream that holds it; the
  // FreeType path in StealthFcFontList.cpp lends them the same way.
  RefPtr<FontData> lent =
      new FontData(blob->Data(), blob->Length(), FontData::Borrowed::Yes);
  RefPtr<gfxDWriteFontFileStream> stream;
  RefPtr<IDWriteFontFile> fontFile;
  HRESULT hr = gfxDWriteFontFileLoader::CreateCustomFontFile(
      lent, getter_AddRefs(fontFile), getter_AddRefs(stream));
  if (FAILED(hr)) {
    return nullptr;
  }
  nsAutoCString uniqueName;
  if (NS_FAILED(gfxFontUtils::MakeUniqueUserFontName(uniqueName))) {
    return nullptr;
  }
  RefPtr entry = MakeRefPtr<gfxDWriteFontEntry>(
      uniqueName, fontFile, stream, aFace->mWeight, aFace->mWidth,
      aFace->mStyle);
  entry->mBundleFaceIndex = aFace->mIndex;
  // The path must be declared together with the bytes: it is the same function
  // that resolves the blob above, so it is not a second source. If it is
  // missing we carry on: the font draws, only the copy to WebRender is paid.
  nsAutoCString path;
  if (StealthBundleFontList::GetFacePath(file, path)) {
    // `get()` returns a `char16ptr_t`, which on Windows converts by itself to
    // `const wchar_t*` (`mfbt/Char16.h:49`): no reinterpret_cast.
    entry->mBundleFilePath = std::wstring(NS_ConvertUTF8toUTF16(path).get());
  }
  BOOL supported;
  DWRITE_FONT_FILE_TYPE fileType;
  UINT32 numFaces;
  if (FAILED(fontFile->Analyze(&supported, &fileType, &entry->mFaceType,
                               &numFaces)) ||
      !supported || aFace->mIndex >= numFaces) {
    return nullptr;
  }
  // Wire the entry back to its shared-list face. This was the last of the
  // three bundle-only branches still omitting it: Linux was fixed 2026-08-07,
  // macOS already had it, and a comment in gfxFcPlatformFontList.cpp asserted
  // THIS one did too, citing a line number that is in the host-collection
  // branch of gfxDWriteFontList::CreateFontEntry (gfxDWriteFontList.cpp, not
  // this function). The comment was wrong and the consequence was invisible -
  // mShmemFace stayed null for every bundled face on Windows, so
  // GetStealthBundleVMetrics returned false and the manifest's vertical
  // metrics were never applied here at all.
  //
  // Nothing LOOKED broken, because Windows fell back to DirectWrite's own
  // metrics and the manifest was computed to reproduce exactly those: the
  // cross-OS parity gate passed 68/68 on numbers that came from two different
  // sources happening to agree. That is a coincidence held in place by the
  // generator being right, not a mechanism - had DWrite changed how it
  // derives any metric, Windows would have drifted from the file that claims
  // to define it and nothing would have said so.
  entry->InitializeFrom(aFace, aFamily);
  return entry.forget();
}

// ---------------------------------------------------------------------------
// The bundle path travels with the unscaled font (the hook that gives it the
// path is StealthWithBundlePath).
// ---------------------------------------------------------------------------
// STEALTH: Mozilla's GetFontDescriptor answers from mFontFileName, the file
// name of the font with its terminator, which it reads from the IDWriteFont:
// `if (!mFont) return false;`. The bundle's faces are made from file data and
// have no IDWriteFont (the loader of our fonts is not an
// IDWriteLocalFontFileLoader, so Mozilla cannot get the name back), and
// Gecko then sends the BYTES of the font to WebRender: 65.9 MB in the parent
// process against 1.9 on an empty page (known bug B154). The path of the bundle file is
// put where Mozilla keeps the file name (path plus terminator), so the callback
// gets the bytes Mozilla would give it for a font installed at that path, with
// the same face index.
namespace mozilla::gfx {

void UnscaledFontDWrite::StealthSeedFilePath(const std::wstring& aPath) {
  mFontFileName.assign(aPath.begin(), aPath.end());
  mFontFileName.push_back(0);
}

bool UnscaledFontDWrite::StealthGetSeededDescriptor(FontDescriptorOutput aCb,
                                                    void* aBaton) {
  MOZ_ASSERT(NS_IsMainThread());
  // Mozilla's own cache of the name answers the same way: for a font whose name
  // it had already read the arguments are the ones it would pass; a font with
  // no name (the stock fonts not yet asked, a font made from a descriptor)
  // falls through to Mozilla's lines.
  if (mFontFileName.empty()) {
    return false;
  }
  aCb(reinterpret_cast<const uint8_t*>(mFontFileName.data()),
      mFontFileName.size() * sizeof(WCHAR), mFontFace->GetIndex(), aBaton);
  return true;
}

}  // namespace mozilla::gfx
