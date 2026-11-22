# fingerprint/fonts/idwr

Category: build
Prefs: none read directly
Test: the wrapper's e2e tests/test_canvas_text_is_windows_e2e.py (342 canvas text cases whose RGBA hashes are retail Windows Firefox's, on Windows, Debian and Ubuntu: text rendered by idwr; without the directory libxul has no idwr and the test is red); the gtest `Idwr.TexturesAreDirectWrites` (gfx/idwr/tests/gtest/TestIdwr.cpp: golden textures of DirectWrite, read in libxul; its suite `Idwr.*` must be in the default gtest filter of release.yml, G20/G42)

## What it does

`gfx/idwr` is the text rasterizer of invisible_DWriteCore: DirectWrite 10.0.26100.9711
in portable C, vendored at the commit in `gfx/idwr/moz.yaml` (fix it upstream and
vendor again, never here). It is built into libxul on x86_64 and aarch64, so canvas
and page text are drawn by the same code on every OS and give the bytes retail
Firefox on Windows gives. Nothing of Mozilla's text drawing changes in this folder:
the folder only adds the directory to the build; the text path that calls idwr is
the work of the other folders of fingerprint/fonts.

## Hooks in Mozilla files

- `gfx/moz.build` (registration, top level, before `TEST_DIRS`, a Mozilla line on each side): `DIRS += ["idwr"]`. One line with the marker, outside Mozilla's `DIRS` list. Without it libxul has no idwr and the text e2e is red.

## Our own files

- `gfx/idwr/IdwrHost.cpp`
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
- `gfx/idwr/src/cff/interp.c`
- `gfx/idwr/src/cff/interp.h`
- `gfx/idwr/src/cff/interp_procs.c`
- `gfx/idwr/src/cff/parse.c`
- `gfx/idwr/src/cff/path.c`
- `gfx/idwr/src/cff/qreduce.c`
- `gfx/idwr/src/cff/setup.c`
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
