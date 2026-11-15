# fingerprint/fonts/idwr

Category: spoof
Prefs: zoom.stealth.text.system_quality (copied into the text gfxVars by StealthIdwrTextVars.cpp), zoom.stealth.fpp.hw_seed (the engine-on predicate)
Test: gtest StealthSkiaIdwr.*, StealthSkiaIdwrWin.*, StealthSkiaStrokeLevels.*, StealthIdwrTextVars.*, StealthIdwrFontconfig.*, Idwr.*, IdwrLibm.* (gfx/tests/gtest, gfx/idwr/tests/gtest)

## What it does

Draws the text of a canvas with idwr, the portable port of DirectWrite's rasteriser, through Skia, on Linux and on Windows, so the masks are DirectWrite's on every host. With the engine on, a font idwr refuses has no typeface (never FreeType, never DirectWrite). With the engine off, Skia draws as stock. The same folder carries the ucrtbase math libxul uses on Linux (gfx/idwr/libm_ucrt.c) and the vendored idwr sources.

The hooks that call into it sit in Mozilla files owned by other folders and carry `STEALTH-HOOK(fingerprint/fonts/idwr)`: gfx/2d/ScaledFontDWrite.cpp, gfx/thebes/gfxPlatformGtk.cpp, gfx/2d/moz.build (fingerprint/fonts/bundle and fingerprint/canvas/noise-projection own those patches).

## Hooks in Mozilla files

- `gfx/2d/ScaledFontFontconfig.cpp` (ScaledFontFontconfig::UseSubpixelPosition, CreateSkTypeface, SetupSkFontDrawOptions and GetDefaultAAMode, already-hook): One include and four one-line calls at the top of the functions that choose how Skia draws a Fontconfig font on Linux: with the idwr text engine declared they return the idwr typeface (or null for a font idwr refuses, never FreeType), subpixel positioning on, the idwr Skia font options and the declared antialias mode. Without the declaration they fall through to Mozilla's own lines, unchanged. The logic lives in StealthSkiaIdwrFontconfig.cpp.
- `gfx/moz.build` (before TEST_DIRS, already-hook): Builds gfx/idwr (invisible_DWriteCore's DirectWrite rasterizer) into libxul, on a line of its own outside Mozilla's DIRS list.
- `gfx/skia/generate_mozbuild.py` (footer (after FINAL_LIBRARY), already-hook): gfx/skia/moz.build is generated from this file, so the SOURCES line for the three idwr Skia sources (SkIdwrPathSink, SkScalerContext_idwr, SkTypeface_idwr) is part of the footer: regenerating Skia keeps it. Three comment lines say why the line is ours. The line in gfx/skia/moz.build is its generated copy.
- `gfx/skia/moz.build` (after FINAL_LIBRARY = 'xul', already-hook): Generated from gfx/skia/generate_mozbuild.py (the footer there carries the same line): builds the three idwr Skia sources into libxul on a line of its own, outside Mozilla's generated lists.

## Our own files

- `gfx/2d/StealthSkiaIdwr.cpp`
- `gfx/2d/StealthSkiaIdwr.h`
- `gfx/2d/StealthSkiaIdwr.mozbuild`
- `gfx/2d/StealthSkiaIdwrFontconfig.cpp`
- `gfx/2d/StealthSkiaIdwrWin.cpp`
- `gfx/idwr/IdwrHost.cpp`
- `gfx/idwr/libm_ucrt.c`
- `gfx/idwr/moz.build`
- `gfx/idwr/moz.yaml`
- `gfx/idwr/sources.mozbuild`
- `gfx/idwr/src/cff/cff_math.c`
- `gfx/idwr/src/cff/cff_port.h`
- `gfx/idwr/src/cff/cscan.c`
- `gfx/idwr/src/cff/cscan.h`
- `gfx/idwr/src/cff/dropout.c`
- `gfx/idwr/src/cff/front.c`
- `gfx/idwr/src/cff/front.h`
- `gfx/idwr/src/cff/glue.c`
- `gfx/idwr/src/cff/hint.c`
- `gfx/idwr/src/cff/interp.h`
- `gfx/idwr/src/cff/interp_loop.c`
- `gfx/idwr/src/cff/interp_procs.c`
- `gfx/idwr/src/cff/parse.c`
- `gfx/idwr/src/cff/path.c`
- `gfx/idwr/src/cff/qreduce.c`
- `gfx/idwr/src/cff/setup.c`
- `gfx/idwr/src/gecko_golden/IdwrGolden.inc`
- `gfx/idwr/src/idwr/cffraster.c`
- `gfx/idwr/src/idwr/cffraster.h`
- `gfx/idwr/src/idwr/color.c`
- `gfx/idwr/src/idwr/face.c`
- `gfx/idwr/src/idwr/face.h`
- `gfx/idwr/src/idwr/fallback.c`
- `gfx/idwr/src/idwr/fallback_nls.h`
- `gfx/idwr/src/idwr/fallback_tables.h`
- `gfx/idwr/src/idwr/font.c`
- `gfx/idwr/src/idwr/fullwidth_tables.h`
- `gfx/idwr/src/idwr/gdimetrics.c`
- `gfx/idwr/src/idwr/glyphrun.c`
- `gfx/idwr/src/idwr/idwr.h`
- `gfx/idwr/src/idwr/idwr_fallback.h`
- `gfx/idwr/src/idwr/idwr_internal.h`
- `gfx/idwr/src/idwr/idwr_math.c`
- `gfx/idwr/src/idwr/idwr_math.h`
- `gfx/idwr/src/idwr/idwr_math_tables.h`
- `gfx/idwr/src/idwr/lcid_table.h`
- `gfx/idwr/src/idwr/metrics.c`
- `gfx/idwr/src/idwr/mode.c`
- `gfx/idwr/src/idwr/nameweight.c`
- `gfx/idwr/src/idwr/outline.c`
- `gfx/idwr/src/idwr/sbit.c`
- `gfx/idwr/src/idwr/texture.c`
- `gfx/idwr/src/idwr/ttraster.c`
- `gfx/idwr/src/idwr/ttraster.h`
- `gfx/idwr/src/idwr/variation.c`
- `gfx/idwr/src/truetype/fatal.h`
- `gfx/idwr/src/truetype/fp_exact.h`
- `gfx/idwr/src/truetype/glyphrun_helpers.c`
- `gfx/idwr/src/truetype/glyphrun_layout.c`
- `gfx/idwr/src/truetype/glyphrun_tables.h`
- `gfx/idwr/src/truetype/glyphrun_texture.c`
- `gfx/idwr/src/truetype/interp.c`
- `gfx/idwr/src/truetype/native.c`
- `gfx/idwr/src/truetype/native.h`
- `gfx/idwr/src/truetype/orig.c`
- `gfx/idwr/src/truetype/orig.h`
- `gfx/idwr/src/truetype/orig_ports.h`
- `gfx/idwr/src/truetype/outline_driver.c`
- `gfx/idwr/src/truetype/outline_driver.h`
- `gfx/idwr/src/truetype/outline_stream.c`
- `gfx/idwr/src/truetype/portable.h`
- `gfx/idwr/src/truetype/scaler_fs.c`
- `gfx/idwr/src/truetype/scaler_fsg.c`
- `gfx/idwr/src/truetype/scaler_init.c`
- `gfx/idwr/src/truetype/scaler_orient.c`
- `gfx/idwr/src/truetype/scaler_sbit.c`
- `gfx/idwr/src/truetype/scaler_scl.c`
- `gfx/idwr/src/truetype/scaler_sfac.c`
- `gfx/idwr/src/truetype/scan_contour.c`
- `gfx/idwr/src/truetype/scan_fill.c`
- `gfx/idwr/src/truetype/scan_glyph.c`
- `gfx/idwr/src/truetype/scan_gray.c`
- `gfx/idwr/src/truetype/scan_line.c`
- `gfx/idwr/src/truetype/scan_measure.c`
- `gfx/idwr/src/truetype/scan_setup.c`
- `gfx/idwr/src/truetype/scan_spline.c`
- `gfx/idwr/src/truetype/tt_state.h`
- `gfx/idwr/tests/check_libxul_math.py`
- `gfx/idwr/tests/gtest/LibmUcrtCases.h`
- `gfx/idwr/tests/gtest/TestIdwr.cpp`
- `gfx/idwr/tests/gtest/TestIdwrLibm.cpp`
- `gfx/idwr/tests/gtest/moz.build`
- `gfx/skia/skia/include/ports/SkTypeface_idwr.h`
- `gfx/skia/skia/src/ports/SkIdwrPathSink.cpp`
- `gfx/skia/skia/src/ports/SkIdwrPathSink.h`
- `gfx/skia/skia/src/ports/SkScalerContext_idwr.cpp`
- `gfx/skia/skia/src/ports/SkScalerContext_idwr.h`
- `gfx/skia/skia/src/ports/SkTypeface_idwr.cpp`
- `gfx/skia/skia/src/ports/SkTypeface_idwr.h`
- `gfx/tests/gtest/StealthIdwr.mozbuild`
- `gfx/tests/gtest/StealthSkiaIdwrGolden.inc`
- `gfx/tests/gtest/StealthTestFonts.h`
- `gfx/tests/gtest/TestStealthIdwrTextVars.cpp`
- `gfx/tests/gtest/TestStealthSkiaIdwr.cpp`
- `gfx/tests/gtest/TestStealthSkiaIdwrThreads.cpp`
- `gfx/tests/gtest/TestStealthSkiaStrokeLevels.cpp`
- `gfx/tests/gtest/gen_skia_text_golden.py`
- `gfx/thebes/StealthIdwrTextVars.cpp`
- `gfx/thebes/StealthIdwrTextVars.h`
- `gfx/thebes/StealthIdwrTextVars.mozbuild`
