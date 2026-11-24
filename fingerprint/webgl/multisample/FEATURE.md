# fingerprint/webgl/multisample

Category: spoof
Prefs: webgl.msaa-samples
Test: gfx/gl/gtest/TestStealthGLMultisample.cpp (StealthGLMultisample.TheDeclaredSampleCountDecides, StealthGLMultisample.BasicRenderDriverBlendsIntoAMultisampledTarget and StealthGLMultisample.BasicRenderDriverDropsMultisampleWhenNothingIsDeclared, the negative control with webgl.msaa-samples=0; Windows only); the WebGL surface of the host gate (webgl1/webgl2 attributes.antialias, SAMPLES) on the Windows runner, which has no GPU.

## What it does

Multisampling is part of the GPU the core declares (`webgl.msaa-samples`, 4 on
every identity, which every declared GPU pairs with: its declared MAX_SAMPLES is
4 or more). Mozilla's driver workarounds decide it from the host's renderer
instead: on the Microsoft Basic Render Driver, the software D3D device every
Windows machine without a GPU renders on, it is dropped (bug 978966, a Windows 8
blending bug), and a page read `antialias: false` and `SAMPLES 0`, a fact about
the host. The decision is taken back where it is born: when the core declares
samples and the driver can draw them, the context has them, whatever the
renderer. A declared 0 needs nothing here (Mozilla turns antialias off for every
context). Today's software device blends correctly into a 4x target: the gtest
draws one and reads the resolved pixel on the Windows CI host, which has no GPU.

## Hooks in Mozilla files

Both hooks of `GLContext::InitImpl` are anchors: the feature as the driver
reports it exists only between `InitFeatures()` and the driver workarounds, and
`MarkUnsupported` also clears four extension bits (ANGLE_/APPLE_/EXT_framebuffer_multisample,
EXT_multisampled_render_to_texture) that a page reads in the extension list; the
hooks keep exactly the old effect (the feature bit back, the extension bits
cleared), so no single wrap or guard gives the same bits.

- `gfx/gl/GLContext.cpp`, anchor after `InitFeatures();`: `StealthNoteReportedMultisample(this, mStealthReportedMultisample);` notes the feature as the driver reports it, before Mozilla's driver workarounds run.
- `gfx/gl/GLContext.cpp`, anchor after the `if (WorkAroundDriverBugs()) { ... }` block: `StealthRestoreMultisample(mAvailableFeatures, mStealthReportedMultisample);` puts the feature bit back when the core declares samples (webgl.msaa-samples > 0, StealthDeclaredMultisample): the declaration decides, not the host renderer. Never more than the driver reports.
- `gfx/gl/GLContext.h`, member after `mAvailableFeatures`: `bool mStealthReportedMultisample = false;`, the field the two anchors share (the value is written and read in the same call of InitImpl).
- `gfx/gl/GLContext.cpp`: the include of `StealthGLMultisample.h`, in a block of ours after Mozilla's includes.
- `gfx/gl/gtest/moz.build`: builds TestStealthGLMultisample.cpp.
- `gfx/gl/moz.build`: builds StealthGLMultisample.cpp.

## Our own files

- `gfx/gl/StealthGLMultisample.cpp`
- `gfx/gl/StealthGLMultisample.h`
- `gfx/gl/gtest/TestStealthGLMultisample.cpp`
