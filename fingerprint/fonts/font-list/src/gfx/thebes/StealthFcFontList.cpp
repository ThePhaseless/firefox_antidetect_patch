/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthFcFontList.h"

#include <fontconfig/fontconfig.h>
#include <harfbuzz/hb.h>

#include <utility>

#include "FontData.h"
#include "SharedFontList-impl.h"
#include "StealthBundleFontList.h"
#include "gfxFcPlatformFontList.h"
#include "gfxFontUtils.h"
#include "mozilla/RefPtr.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "mozilla/gfx/2D.h"
#include "nsString.h"
#include "nsTArray.h"

using mozilla::MakeAndAddRef;
using mozilla::MakeRefPtr;
using mozilla::gfx::Factory;
using mozilla::gfx::SharedFTFace;
using mozilla::gfx::UnscaledFontFontconfig;
namespace fontlist = mozilla::fontlist;

// Global namespace on purpose: gfxFontconfigFontEntry declares
// `friend struct StealthFcAccess;` (gfxFcPlatformFontList.h) so that this file
// can reach gfxFontEntry::InitializeFrom, which is protected.
struct StealthFcAccess {
  static void InitializeFrom(gfxFontconfigFontEntry* aEntry,
                             fontlist::Face* aFace,
                             const fontlist::Family* aFamily) {
    aEntry->InitializeFrom(aFace, aFamily);
  }
  static void AddUnscaledFont(gfxFontconfigFontEntry* aEntry,
                              const RefPtr<UnscaledFontFontconfig>& aFont) {
    aEntry->mUnscaledFontCache.Add(aFont);
  }
};

void StealthDeclareFontFile(FcPattern* aPattern, const char* aFile,
                            int aIndex) {
  // STEALTH: put back the file that `CreatePatternForFace` has just removed.
  //
  // That function gives fontconfig a FAKE file name and then deletes FC_FILE
  // and FC_INDEX, because a font downloaded by a page has no file. Our bundle's
  // faces do have one, and hiding it costs: with no file in the pattern,
  // `CreateScaledFont` builds an `UnscaledFont` without a path,
  // `GetFontDescriptor` fails and Gecko sends the font BYTES to WebRender
  // instead of the path. Measured 65.9 MB in the parent process against 1.9 on
  // an empty page - known bug B154.
  //
  // A caller that passes no file sees no difference: the branch does not run.
  if (aFile && *aFile) {
    FcPatternAddString(aPattern, FC_FILE,
                       reinterpret_cast<const FcChar8*>(aFile));
    FcPatternAddInteger(aPattern, FC_INDEX, aIndex);
  }
}

hb_face_t* StealthBaseHBFaceRef(gfxFontEntry* aEntry) {
  // Qualified call: the base implementation, not the Fontconfig override
  // (calling the override here would recurse).
  //
  // A named object, not a temporary: the AutoHBFace conversion is
  // ref-qualified `const&` precisely to make the dangling form impossible.
  // This call was already correct - the temporary would have lived until the
  // semicolon - and only changes shape.
  const auto autoFace(aEntry->gfxFontEntry::GetHBFace());
  return hb_face_reference(autoFace);
}

uint32_t StealthTableFaceIndex(SharedFTFace* aFace) {
  return aFace ? uint32_t(aFace->GetFace()->face_index & 0x7FFF) : 0;
}

bool StealthFaceDataHasTable(gfxFontconfigFontEntry* aEntry,
                             uint32_t aTableTag, bool* aResult) {
  // A face of a .ttc made from data (the bundle's) answers for ITS face. Mozilla
  // reads the table directory at the start of the data, which is face 0: for
  // face 0 (and for a font that is not a collection) the guard says no and
  // Mozilla's own line runs, on the same directory.
  auto* ufd = aEntry->GetUserFontData();
  if (!ufd) {
    return false;
  }
  const uint32_t index = StealthTableFaceIndex(aEntry->GetFTFace());
  if (!index) {
    return false;
  }
  *aResult = !!gfxFontUtils::FindTableDirEntry(ufd->Data(), aTableTag, index);
  return true;
}

bool StealthFaceDataTable(gfxFontconfigFontEntry* aEntry, uint32_t aTableTag,
                          hb_blob_t** aResult) {
  // As StealthFaceDataHasTable, for the blob of the table.
  auto* ufd = aEntry->GetUserFontData();
  if (!ufd) {
    return false;
  }
  const uint32_t index = StealthTableFaceIndex(aEntry->GetFTFace());
  if (!index) {
    return false;
  }
  *aResult = gfxFontUtils::GetTableFromFontData(ufd->Data(), aTableTag, index);
  return true;
}

bool StealthDropPatternWithoutFamily(
    const RefPtr<gfxFontconfigFontFamily>& aFamily) {
  // Bundle-only: drop every pattern that arrives while aFontFamily is still
  // null (see the comment of the header: AddPatternToFontList).
  return !aFamily;
}

bool StealthSkipsSystemFontSetCore(bool aBundleOnly) { return aBundleOnly; }

bool StealthSkipsSystemFontSet(const gfxPlatformFontList* aList) {
  return StealthSkipsSystemFontSetCore(aList->StealthBundleOnly());
}

hb_blob_t* StealthHBFaceTable(gfxFontEntry* aEntry, uint32_t aTableTag) {
  // As in StealthBaseHBFaceRef: a named object instead of the temporary. It
  // was correct before too (the temporary lives until the semicolon), but the
  // AutoHBFace conversion is now `const&` to prevent the dangling form.
  const auto face(aEntry->GetHBFace());
  return hb_face_reference_table(face, aTableTag);
}

void StealthDeclareTextOptions(FcPattern* aPattern) {
  // STEALTH: the declaration goes into the PATTERN, not into the readers.
  //
  // There are TWO readers of these values, and fixing one leaves the other on
  // the machine: `PrepareFontOptions` (which the caller, CreateFontInstance,
  // calls right after this function) builds the FreeType load flags, and
  // `ScaledFontFontconfig::InstanceData` (gfx/2d, lines 140-185) reads the SAME
  // pattern again to build the options that go to WebRender, which is the path
  // that really rasterizes. With only the first one fixed, the measurement did
  // not move by a bit: this is the one-place rule seen live, the same fact
  // computed in two places.
  //
  // Writing it into the pattern makes the deciding place one again, and the
  // two readers stay the upstream code they were.
  //
  // The pattern they work on has already been through, as the upstream comment
  // in `PrepareFontOptions` says, "user and system fontconfig configurations":
  // so `/etc/fonts` decided how we rasterize the faces that WE ship.
  // Measured on 2026-08-16 through the product, same binary and same page:
  // pixel hash 3842037683 with the host's fontconfig (which on this machine
  // is `hintslight`), 1512591551 with an empty configuration, 2489286717 with
  // `hintnone`. A page reads those bytes with `getImageData`.
  //
  // These are TWO and not six: `FC_RGBA`, `FC_LCD_FILTER` and
  // `FC_EMBEDDED_BITMAP` measure identical in every configuration tried, and
  // stay where they are.
  //
  // No fallback if the declaration is missing: that would mean asking the
  // machine again, and `StealthDeclarationGate` refuses to start before
  // getting here.
  const int32_t hintstyle =
      mozilla::StaticPrefs::zoom_stealth_text_freetype_hintstyle();
  if (hintstyle >= 0) {
    FcPatternDel(aPattern, FC_HINT_STYLE);
    FcPatternDel(aPattern, FC_HINTING);
    FcPatternAddInteger(aPattern, FC_HINT_STYLE, hintstyle);
    FcPatternAddBool(aPattern, FC_HINTING,
                     hintstyle == FC_HINT_NONE ? FcFalse : FcTrue);
  }
  const int32_t antialias =
      mozilla::StaticPrefs::zoom_stealth_text_freetype_antialias();
  if (antialias >= 0) {
    FcPatternDel(aPattern, FC_ANTIALIAS);
    FcPatternAddBool(aPattern, FC_ANTIALIAS, antialias ? FcTrue : FcFalse);
  }
}

void StealthDeclaredFontFile(FcPattern* aPattern, std::string& aFile,
                             int& aIndex) {
  // STEALTH: ask the PATTERN whether it names a file, instead of inferring it
  // from the face having been created from memory.
  //
  // Mozilla's condition, right before, is `if (!face->GetFontData())`, that is
  // a PROXY: "created from memory" stands for "has no file". For our bundle's
  // faces that proxy is false - the bytes are the mapping OF a file, whose
  // path and index we know - and the consequence was that the `UnscaledFont`
  // was born without a path, `GetFontDescriptor` failed, and Gecko sent the
  // font BYTES to WebRender: 65.9 MB in the parent process against 1.9 on an
  // empty page (known bug B154).
  //
  // Upstream behavior does not move, case by case: a normal face leaves
  // Mozilla's block with the file already written (or with the error it was);
  // a face from data WITHOUT a file in the pattern (a page's font:
  // `CreatePatternForFace` removes the fake name) leaves `file` empty as
  // before. The only case that changes is ours, which was not foreseen before.
  if (!aFile.empty()) {
    return;
  }
  const FcChar8* fcFile;
  int index;
  if (FcPatternGetString(aPattern, FC_FILE, 0,
                         const_cast<FcChar8**>(&fcFile)) == FcResultMatch &&
      FcPatternGetInteger(aPattern, FC_INDEX, 0, &index) == FcResultMatch) {
    aFile = reinterpret_cast<const char*>(fcFile);
    aIndex = index;
  }
}

void StealthPreferFileUnscaledFont(
    gfxFontconfigFontEntry* aEntry, RefPtr<UnscaledFontFontconfig>& aFont,
    std::string& aFile, int aIndex, SharedFTFace* aFace) {
  // STEALTH: the choice is made on `file`, not on `GetFontData()`. It is the
  // same proxy corrected in StealthDeclaredFontFile: what decides whether an
  // UnscaledFont can describe itself with a path is HAVING a path, not where
  // the bytes came from.
  //
  // Mozilla has already chosen and cached; here only the bundle case is
  // corrected (UnscaledFont without a path but a known file). The first entry,
  // with no references left, dies and its weak pointer in the cache with it;
  // the next lookup by (file, index) finds this one.
  // `aFont->GetFile()` not empty: Mozilla has already used the path (and
  // `aFile` has been moved, it must not be read).
  if (!aFont->GetFile().empty() || aFile.empty()) {
    return;
  }
  aFont = new UnscaledFontFontconfig(std::move(aFile), aIndex, aFace);
  StealthFcAccess::AddUnscaledFont(aEntry, aFont);
}

bool StealthPopulateSharedList(gfxFcPlatformFontList* aList) {
  return aList->StealthBundleOnly() &&
         StealthPopulateSharedList(aList->SharedFontList());
}

bool StealthPopulateSharedList(fontlist::FontList* aList) {
  // Uniform bundle: build the shared family list + faces from our manifest,
  // skipping the fontconfig enumeration (host fonts never enter). Linux builds
  // faces eagerly, so AddFaces each family here.
  auto* bundle = StealthBundleFontList::Get();  // never null; it crashes first
  if (!aList) {
    return false;
  }
  nsTArray<fontlist::Family::InitData> famData(bundle->Families().Clone());
  aList->SetFamilyNames(famData);
  for (uint32_t i = 0; i < aList->NumFamilies(); i++) {
    auto& fam = aList->Families()[i];
    nsTArray<fontlist::Face::InitData> faceData;
    bundle->GetFaces(fam.DisplayName().AsString(aList), faceData);
    fam.AddFaces(aList, faceData);
  }
  return true;
}

already_AddRefed<gfxFontEntry> StealthCreateBundleFontEntry(
    gfxFcPlatformFontList* aList, fontlist::Face* aFace,
    const fontlist::Family* aFamily) {
  return StealthCreateBundleFontEntry(aFace, aFamily, aList->SharedFontList());
}

already_AddRefed<gfxFontEntry> StealthCreateBundleFontEntry(
    fontlist::Face* aFace, const fontlist::Family* aFamily,
    fontlist::FontList* aList) {
  // Instantiate the face straight from its bundle file via FreeType;
  // NewSharedFTFaceFromData takes the .ttc face index directly.
  const nsCString file(aFace->mDescriptor.AsString(aList));
  // Stealth: ONE mapping per FILE, lent to every face - the same thing
  // Windows does, with the same object and the same lifetime.
  //
  // How we got here, in two steps. First FreeType received a `malloc` copy of
  // the whole file PER FACE, owned and freed by the old FTUserFontData, and
  // invisible to about:memory: measured 2026-08-14 on a page that touches 1,
  // 10, 34 and 68 families, the unclassified heap of the content process was
  // 0.6, 9.0, 98.7 and 319.9 MB, that is ~1.7 times the bytes of the files
  // touched - which is the faces/families ratio (129/68).
  //
  // Then (step 5.2m) we moved to the constructor by PATH, which made CloneFace
  // call `Factory::NewFTFace(path, index)`: no copy, but a second
  // implementation. Windows mapped the file and lent it to the DWrite stream,
  // Linux let FreeType open the file: two different answers to the same
  // question, and two CloneFace branches that also diverge in OTHER ways - the
  // by-path branch does NOT call `FT_Select_Charmap`, while the in-memory one
  // selects UNICODE or MS_SYMBOL. That is, on Linux the faces were born with
  // the charmap FreeType picks by itself, diverging not only from Windows but
  // from upstream.
  //
  // Now the two platforms do the same thing: `GetFaceBlob` maps the file once
  // and keeps it in an immortal cache, `FT_New_Memory_Face` borrows those bytes
  // without copying them (that is the contract of the call), and the in-memory
  // branch (from Firefox 159 `Factory::NewSharedFTFaceFromData`, before that
  // `FTUserFontData::CloneFace`) puts the charmap selection back. The pages
  // become the FILE's on both: shared by the operating system between
  // processes, and evictable instead of swappable.
  auto* bundle = StealthBundleFontList::Get();
  RefPtr<StealthBundleFontList::FileBlob> blob = bundle->GetFaceBlob(file);
  if (!blob || !blob->Length()) {
    return nullptr;
  }
  RefPtr<FontData> lent =
      new FontData(blob->Data(), blob->Length(), FontData::Borrowed::Yes);
  RefPtr<SharedFTFace> face =
      Factory::NewSharedFTFaceFromData(lent, aFace->mIndex);
  if (!face) {
    return nullptr;
  }
  // The PATH must be declared together with the bytes, or WebRender receives
  // the bytes. It is not a second source: it is the same function that
  // resolves the blob above, `GetFacePath`, which resolves through the same
  // directory as `GetFaceBlob`. If the path is missing we carry on anyway - the
  // font draws, only the copy is paid - so here we do NOT refuse.
  nsAutoCString facePath;
  if (!StealthBundleFontList::GetFacePath(file, facePath)) {
    facePath.Truncate();
  }
  nsAutoCString name(aFamily->DisplayName().AsString(aList));
  RefPtr fe = MakeRefPtr<gfxFontconfigFontEntry>(
      name, aFace->mWeight, aFace->mWidth, aFace->mStyle, std::move(face));
  // The data-font constructor builds its pattern with CreatePatternForFace,
  // which drops the file; it is declared again here, on the entry's own
  // pattern, before anything reads it.
  StealthDeclareFontFile(fe->GetPattern(),
                         facePath.IsEmpty() ? nullptr : facePath.get(),
                         aFace->mIndex);
  // Wire the entry back to its shared-list face, exactly as the non-stealth
  // path of CreateFontEntry does and as the CoreText bundle-only branch
  // (CoreTextFontList.cpp, CreateFontEntry) does. This branch omitted it -
  // found 2026-08-07 - which left mShmemFace null for EVERY bundled face on
  // Linux.
  //
  // The DWrite branch was named here too, citing gfxDWriteFontList.cpp:1211.
  // That was WRONG: 1211 is in the host-collection branch, and the bundle-only
  // branch (gfxDWriteFontList::CreateStealthBundleFontEntry, now in
  // StealthDWriteFontList.cpp) omitted the call just like this one did, until
  // 2026-08-08. So this comment asserted a symmetry that did not exist and
  // would have kept anyone from looking - which is the whole reason a
  // cross-reference in a comment has to be checked against the code it
  // names, not trusted.
  // Two consequences: gfxFont::SanitizeMetrics could not tell a bundled face
  // from any other font, so the manifest's vertical metrics were silently
  // never applied; and the entry's charmap could never be published back
  // into the shared list (the mShmemFace->SetCharacterMap path), leaving
  // families permanently not-fully-initialized, which is what lets the async
  // cmap path record a codepoint in mCodepointsWithNoFonts and keep that
  // verdict for the rest of the session.
  //
  // Setting mShmemFace here was necessary for that second consequence and NOT
  // sufficient: ReadCMAP still refused to publish, because it asked
  // `!IsUserFont()` and every bundled face is built from file data. That half
  // is fixed separately, in gfxFontEntry::ShouldPublishCharacterMap.
  StealthFcAccess::InitializeFrom(fe.get(), aFace, aFamily);
  return fe.forget();
}
