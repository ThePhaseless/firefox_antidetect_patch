# fingerprint/fonts/font-list

Category: spoof
Prefs: gfx.font_rendering.fallback.async, zoom.stealth.fonts.generics, zoom.stealth.text.freetype_antialias, zoom.stealth.text.freetype_hintstyle
Test: gtest StealthFontListHooks.* (PublishCharacterMap, NoFontsFound, SkipsHostCollection, SkipsHostSubstitutes, FaceIndex, UsePrefFontList, UseCmaps, MayDeferCmapLoading, BundledFontsApply; TestStealthFontListHooks.h, included by TestStealthFcFontList.cpp on Linux and TestStealthBundledCollection.cpp on Windows), StealthFcFontList.* (DeclareFontFile, DeclaredFontFile, TextOptions, TableFaceIndex, PreferFileUnscaledFont, PatternWithoutFamily, SkipsSystemFontSet), StealthFcBundleFonts.* (the font of a file of the bundle, each face of a collection, FacesForFamilyComeFromTheManifestOnlyUnderBundleOnly, CommonFallbackIsTheManifestListUnderBundleOnly, ReportBundleFiles, FaceDataTableFallsThroughForAFaceWithAFile, FallbackNeverDefersUnderBundleOnly), StealthBundledCollection.*, StealthFontList.*, StealthFallbackNames.*, StealthTtcFace.*; wrapper e2e test_system_fonts_and_colors_are_windows_e2e.py, test_canvas_text_is_windows_e2e.py, test_fontconfig_reads_nothing_of_the_host_linux_e2e.py, test_screenshot_of_text_returns_linux_e2e.py; to write in the wrapper: test_bundle_font_names_e2e.py (src:local()), test_the_font_list_is_the_bundle_e2e.py

## What it does

The font list of every browser is the bundle and nothing else (`mStealthBundleOnly`, true in every build): no
enumeration of the host on DirectWrite or fontconfig, the families and faces come from the manifest
(`fonts/bundle-fonts.list`, read by StealthBundleFontList), `src: local()` finds the PostScript and full names of the
bundled faces, the manifest's aliases replace the host substitute tables, the CSS generics, the emoji family and the
system-ui family are the declared Windows ones, the fallback list and the cmaps are deterministic (the cmap of a
bundled face is published to the shared list, and a fallback search never defers a family's cmap loading), and on
Linux the faces are made from the bundle files through FreeType with the file path declared to WebRender. The files
of the bundle and the lending of their bytes are fingerprint/fonts/bundle. `CoreTextFontList.cpp` (macOS) left the
series: no leg builds it (G25).

## Hooks in Mozilla files

One line each, with the marker `// STEALTH-HOOK(fingerprint/fonts/font-list)` on it. Every function they call
takes `this` (or a field, or the value Mozilla computed) and has a pure core `...Core(bool aBundleOnly, ...)` in
StealthFontListHooks.cpp, so the answer of stock Firefox (aBundleOnly = false) is testable.

- `gfx/thebes/gfxDWriteFontList.cpp`: registration `#include "StealthFontListHooks.h"` in a block of ours; wraps
  `StealthPublishCharacterMap(this, !IsUserFont()) && mShmemFace` (ReadCMAP),
  `StealthWithBundlePath(mBundleFilePath, new UnscaledFontDWrite(...))` (CreateFontInstance),
  `StealthFaceIndex(mBundleFaceIndex, 0)` (CreateFontFace), `StealthNoFontsFound(this, count == kBundledCount)`
  (InitFontListForPlatform), and in InitSharedFontListForPlatform the family list of the shared font list, two
  one-line hooks around Mozilla's own call and condition: the call that appends the system collection is
  `StealthAppendFamiliesFromCollection(mSystemFonts, families, &forceClassicFams)` (a member with the same arguments:
  under bundle-only it assigns the manifest's families and never enumerates the host collection, otherwise it makes
  Mozilla's call) and the condition `if (mBundledFonts)` wraps Mozilla's operand in
  `StealthBundledFontsApply(this, mBundledFonts)` (false under bundle-only, so the bundled collection is not appended
  and its timing is not recorded in the parent); guards at the head of `CreateFontEntry`, `GetFacesInitDataForFamily`, `ReadFaceNames`,
  `ReadFaceNamesForFamily`, `GetFontsFromCollection` (the system collection), `GetFontSubstitutes`,
  `GetDirectWriteSubstitutes` and `CreateBundledFontsCollection`. The four calls of the substitute functions in
  InitSharedFontListForPlatform and InitFontListForPlatform are Mozilla's again: the guard is in the callee, whose
  four callers all had the same condition, and `GetFontsFromCollection(mSystemFonts)` too (the bundled collection, its
  other caller, is not skipped).
- `gfx/thebes/gfxFcPlatformFontList.cpp`: registration `#include "StealthFcFontList.h"`; wrap
  `StealthPublishCharacterMap(this, !IsUserFont()) && mShmemFace` (ReadCMAP) and
  `StealthUsePrefFontList(this, usePrefFontList)` (AddGenericFonts); guards at the head of `HasFontTableInternal`,
  `GetFontTableInternal`, `CreateFontEntry` and `FindAndAddFamiliesLocked` (the two local lines above the old hook did
  not feed the base call); notice `StealthDeclareTextOptions(aPattern)` at the head of `PrepareFontOptions` (its only
  caller); anchors `StealthDeclaredFontFile`, `StealthPreferFileUnscaledFont` (end of block, G30),
  `StealthDropPatternWithoutFamily`, `StealthSkipsSystemFontSet` and `StealthPopulateSharedList(this)` (Q1: anchors with
  an early return). Declared exceptions (G35, G24, the network on AutoHBFace in fingerprint/fonts/bundle): the two
  lines `face = StealthBaseHBFaceRef(this)` and `auto* table = StealthHBFaceTable(this, aTableTag)`.
- `gfx/thebes/gfxPlatformFontList.cpp`: registration `#include "StealthFontListHooks.h"`; wraps
  `StealthUseCmaps(this, IsFontFamilyWhitelistActive())` and
  `StealthMayDeferCmapLoading(this, StaticPrefs::gfx_font_rendering_fallback_async())` in GlobalFontFallback (the
  other two lines of Mozilla's condition are Mozilla's again); guard `StealthSystemUIFamilies(aFamilies)` in
  GetSystemUIFontFamilies; anchors `StealthReportBundleFiles(aHandleReport, aData)`, `StealthReplaceCommonFallbackFonts`
  (Mozilla's platform call is Mozilla's again and runs first), `StealthApplyAlias(this, key)`,
  `StealthLoadMissingCharacterMaps(list, aFamily, aLoadCmaps)`, `StealthPrependDeclaredGeneric` and
  `StealthPrependEmojiFamily`. The line `mStealthBundleOnly = true;` of the constructor is gone: the member's default is true.
- `gfx/thebes/gfxPlatformFontList.h`: members `MayDeferCmapLoading`, `StealthBundleOnly`, `StealthReadFaceNames`,
  `RecordFaceNamesFromTable`, `StealthLoadMissingCharacterMaps`, `ReadFaceNamesForFamily` (ours, declared after
  Mozilla's, which is renamed `ReadFaceNamesForFamily_Mozilla`: one line rewritten, its inline empty stub stays) and
  `bool mStealthBundleOnly = true;`; the stub of `ReadFaceNames` is Mozilla's again with one guard line inside:
  `if (gfxPlatformFontList::StealthBundleOnly()) return StealthReadFaceNames(...)`.

## Where the comments went

The comments the hooks carried inline are next to the functions of ours: StealthFontListHooks.cpp (cmap publishing,
substitute tables, no host enumeration, bundle path and face index, generics and cmap route, the may-defer predicate,
the fallback list, the eager cmap loader, about:memory), StealthFcFontList.h and .cpp (the fontconfig hooks: the pattern
without a family, the system font set, the alias leak of `Sans:Linux` in FindAndAddFamiliesLocked, the generics), StealthDWriteFontList.cpp
(the DirectWrite sections) and StealthBundleFontList.cpp/.h (the bundle-only helpers).

## Not done in this pass

- Design row `moved` (G18, Q4): the single cache Add of `StealthPreferFileUnscaledFont` (Fc9).
- Q7: the lines of Mozilla in `GetHBFace` and `GetFontTableInternal` stay as declared exceptions.
- `RecordFaceNamesFromTable` stays a member of gfxPlatformFontList (one line in the header) instead of a lambda inside
  `ReadFaceNamesForFamily`: the thread-safety analysis of a lambda cannot be checked without a build.
- The gtest for `StealthLoadMissingCharacterMaps` (N12), `StealthWithBundlePath` and the Windows `FacesForFamily` need a
  `fontlist::FontList` or a real `IDWriteFontFace` and are covered by the e2e tests above.

## Our own files

- `gfx/tests/gtest/TestStealthBundledCollection.cpp`
- `gfx/tests/gtest/TestStealthFcFontList.cpp`
- `gfx/tests/gtest/TestStealthFontListHooks.h`
- `gfx/thebes/StealthFcFontList.cpp`
- `gfx/thebes/StealthFcFontList.h`
- `gfx/thebes/StealthFcFontList.mozbuild`
- `gfx/thebes/StealthFontListHooks.cpp`
- `gfx/thebes/StealthFontListHooks.h`
