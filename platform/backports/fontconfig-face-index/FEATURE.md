# platform/backports/fontconfig-face-index

Category: backport
Prefs: none read directly
Test: StealthFcBundleFonts.EachFaceOfACollectionIsMadeWithItsOwnIndex (gfx/tests/gtest/TestStealthFcFontList.cpp)

## What it does

Mozilla bug 2077661, mozilla-central commit 53aca1462bf3b9965d1eae9a2bf3b74767e6c6da (2026-10-13), carried as its diff before the
tag has it. UnscaledFontFontconfig::CreateFromFontDescriptor confirmed a font file with FcFontMatch on a pattern of FC_FILE and
FC_INDEX, then replaced the path and the index with the answer's. FcFontMatch chooses by likeness, not by index, so for a collection
(.ttc) it answered with another face of the same file and WebRender drew the wrong face. The index asked for is now kept, and the
answer's index is read only when fontconfig returns another path.

Not ours: the folder has no budget. BACKPORT.json names the commit and the sha256 of its diff of the file, upstream-53aca1462bf3.diff
is that diff, and `check` requires hooks.patch to carry it byte for byte (index lines and hunk offsets apart). The folder goes when
the Mozilla tag has the commit: `engine.py port --to <tag>` and `engine.py check --against <tag>` fail on a tag that does.

Not taken with it, on purpose: the FcPatternDestroy of the FcFontMatch answer arrived with bug 2088688 (15121caee00a, the
ValidateFontDescriptor refactor), which is not this commit.

## Hooks in Mozilla files

- `gfx/2d/ScaledFontFontconfig.cpp` (UnscaledFontFontconfig::CreateFromFontDescriptor, the block after FcFontMatch, hard): the diff of the commit.
