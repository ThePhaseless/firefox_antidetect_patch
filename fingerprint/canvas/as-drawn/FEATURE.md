# fingerprint/canvas/as-drawn

Category: other, spoof
Prefs: none read directly
Test: wrapper:tests/test_moz_element_paints_a_webgl_canvas_as_drawn_e2e.py::test_moz_element_paints_a_webgl_canvas_as_drawn (to write: a WebGL canvas with the noise projection active, painted through `background: -moz-element(#c)`, shows the drawn colour in a screenshot while `readPixels` of the same canvas differs; the noised `readPixels` is its negative control). Existing, for the page read-back: invisible_playwright/tests/test_canvas_reads_as_drawn.py (it does not cover these readers). The drag image and the taskbar preview have no page-visible effect and no test beyond the compile.

## What it does

The browser's own readers that SHOW a canvas (`-moz-element` painting, the drag image, the Windows taskbar preview, the chrome-only compareCanvases hook) read its pixels as drawn, without the noise projection that a page's read-back gets (`GetSurfaceSnapshot` applies it for WebGL/WebGPU contexts, `GetSurfaceSnapshotAsDrawn` skips it; both are owned by fingerprint/canvas/noise-projection). Every other caller of `nsLayoutUtils::SurfaceFromElement` is a page reading or drawing with the canvas and gets the noised snapshot, as Mozilla's code calls it. The flag `kStealthSfeAsDrawn` tells the two apart; the readers that show a canvas ask for it through `nsLayoutUtils::StealthSurfaceFromElementAsDrawn`.

## Hooks in Mozilla files

- `layout/base/nsLayoutUtils.cpp`: registration, `#include "StealthSurfaceFlags.h"` in a block of ours after Mozilla's includes. Wrap-call in `nsLayoutUtils::SurfaceFromElement(HTMLCanvasElement*, uint32_t, RefPtr<DrawTarget>&)`: Mozilla's `aElement->GetSurfaceSnapshot(pAlphaType, aTarget)` becomes `aElement->StealthGetSurfaceSnapshot(aSurfaceFlags, pAlphaType, aTarget)`, the called name replaced and the flags of the caller added in front, Mozilla's arguments in place. The member is defined in layout/base/StealthSurfaceFlags.h: exactly one of `GetSurfaceSnapshotAsDrawn` (the caller set `kStealthSfeAsDrawn`) or `GetSurfaceSnapshot` is called, with the same arguments. The snapshot with noise is never taken first.
- `layout/base/nsLayoutUtils.h`: one member line in `class nsLayoutUtils`, after the `SurfaceFromElement(HTMLVideoElement*, ...)` declaration: the template `StealthSurfaceFromElementAsDrawn(ElementT* aElement)`, defined in layout/base/StealthSurfaceFlags.h as `SurfaceFromElement(aElement, kStealthSfeAsDrawn)`, so the overload is the one the static type of the element picks. The declaration of `HTMLCanvasElement::StealthGetSurfaceSnapshot` is one member line in `dom/html/HTMLCanvasElement.h`, listed with the hooks of fingerprint/canvas/noise-projection (the same file).
- `layout/painting/nsImageRenderer.cpp`: registration (include), and in `nsImageRenderer::PrepareImage` the `-moz-element` branch asks for the element as drawn: Mozilla's `nsLayoutUtils::SurfaceFromElement(paintElement)` becomes `nsLayoutUtils::StealthSurfaceFromElementAsDrawn(paintElement)`, the called name replaced, the argument Mozilla's. `-moz-element` SHOWS the element, like the screen, so a canvas is painted as drawn. Category spoof because what it renders is what a page sees in a screenshot.
- `widget/nsBaseDragService.cpp` (`nsBaseDragSession::DrawDragForImage`): `aCanvas->GetSurfaceSnapshotAsDrawn()` in place of `GetSurfaceSnapshot()`. The drag image shows the canvas; a page never reads it back.
- `widget/windows/TaskbarPreview.cpp` (`TaskbarPreviewCallback::Done`): `canvas->GetSurfaceSnapshotAsDrawn()` in place of `GetSurfaceSnapshot()`. The taskbar shows the canvas; a page never reads it back. Windows only.

The last two are not spoof: a page cannot read either; they keep the host's own UI free of the noise.

## The flag: kStealthSfeAsDrawn (layout/base/StealthSurfaceFlags.h)

A canvas as DRAWN, without the canvas noise: for the browser's own
readers that show it and never hand its bytes to a page (-moz-element,
nsDOMWindowUtils). Every other caller is a page reading the canvas or
drawing with it, and gets what HTMLCanvasElement::GetSurfaceSnapshot
and OffscreenCanvas::GetSurfaceSnapshot give a page.

It is not in nsLayoutUtils' SFE_* enum, the place where Mozilla appends its
next flag: a port would merge two lines taking the same bit without a
conflict. It is on bit 31 (Mozilla's end at bit 8 in 157 and 159), marked
STEALTH-FLAG-SPACE(layout/base/nsLayoutUtils.h, SFE_), and
build/stealth_check_sources.py fails if an SFE_ flag takes it.

`HTMLCanvasElement::StealthGetSurfaceSnapshot` takes the arguments as Mozilla's `GetSurfaceSnapshot` does (the alpha type pointer and the draw target pointer), so the call passes exactly what Mozilla's line passed. The chrome-only compareCanvases hook (dom/base/StealthCanvasAsDrawn.h) asks for the canvases as drawn through the same template, `StealthSurfaceFromElementAsDrawn`.

The method names `GetSurfaceSnapshotAsDrawn` (HTMLCanvasElement, OffscreenCanvas) belong to fingerprint/canvas/noise-projection (G1); this folder only calls them.
