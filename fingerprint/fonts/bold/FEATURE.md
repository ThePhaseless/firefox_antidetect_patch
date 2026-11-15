# fingerprint/fonts/bold

Category: spoof
Prefs: none read directly (the engine-on predicate is StealthEngineActive)
Test: gtest StealthSyntheticBoldRule.*, StealthSyntheticBold.* (gfx/tests/gtest/TestStealthSyntheticBold.cpp)

## What it does

A bold face the font does not have is made the way Firefox retail on Windows makes it, on every OS. An installed font (the faces of the bundle stand for them) gets the rasteriser's bold simulation: idwr's, with the advance and the ink box DirectWrite gives a simulated bold face, and no multi-strike and no FreeType embolden. A webfont or a COLR font keeps Gecko's multi-strike and its advance growth. The rule and the bold metrics live in StealthSyntheticBold.h and StealthIdwrBold.h.

The hooks that call into it carry `STEALTH-HOOK(fingerprint/fonts/bold)` and sit in the Mozilla files owned by fingerprint/fonts/font-list (gfx/thebes/gfxDWriteFontList.cpp) and fingerprint/fonts/metrics (gfx/thebes/gfxDWriteFonts.cpp); the metrics hooks in gfx/thebes/StealthDesignMetrics.h pass the embolden flag to the same rule.

## Hooks in Mozilla files

None of its own: its hooks are in files of the folders named above.

## Our own files

- `gfx/2d/StealthIdwrBold.h`
- `gfx/tests/gtest/TestStealthSyntheticBold.cpp`
- `gfx/thebes/StealthSyntheticBold.h`
