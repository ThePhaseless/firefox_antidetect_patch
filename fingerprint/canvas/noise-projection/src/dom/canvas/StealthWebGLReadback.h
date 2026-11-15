/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef DOM_CANVAS_STEALTHWEBGLREADBACK_H_
#define DOM_CANVAS_STEALTHWEBGLREADBACK_H_

// The canvas noise (gfx::StealthProjectPixels) on every road by which a page
// reads the pixels of a WebGL canvas, called from hooks in
// ClientWebGLContext.cpp.
//
// Where the noise is NOT applied: ClientWebGLContext::GetSurfaceSnapshot. Its
// snapshot is also what the screen, -moz-element and the GPU-side copies are
// made from. A page reads it through HTMLCanvasElement::GetSurfaceSnapshot or
// through the readers below, which apply gfx::StealthProjectPixels once, on
// these stored pixels. The async snapshot (captureStream) is projected in
// DoReadPixelsAsync, through ProjectAsyncSnapshot.
//
// The function is a projection (applying it twice changes nothing), so the
// roads agree: readPixels into an array, readPixels into a PIXEL_PACK_BUFFER,
// toDataURL and toBlob, and captureStream frames give the same bytes for the
// same pixels.
//
// This is a header with inline definitions, included by ClientWebGLContext.cpp
// only: the PIXEL_PACK_BUFFER road sends commands with
// ClientWebGLContext::Run, whose Run_WithDestArgTypes is a template defined in
// that .cpp and can be instantiated nowhere else.

#include <cstdint>
#include <cstring>
#include <vector>

#include "CanvasUtils.h"
#include "ClientWebGLContext.h"
#include "HostWebGLContext.h"
#include "WebGLChild.h"
#include "WebGLMethodDispatcher.h"
#include "mozilla/AlreadyAddRefed.h"
#include "mozilla/Maybe.h"
#include "mozilla/RefPtr.h"
#include "mozilla/Span.h"
#include "mozilla/gfx/StealthCanvasProjection.h"

#define STEALTH_WEBGL_RPROC(_METHOD) \
  decltype(&HostWebGLContext::_METHOD), &HostWebGLContext::_METHOD

namespace mozilla {

// A friend of ClientWebGLContext (the declaration is in ClientWebGLContext.h):
// it reaches mNotLost, Run and DoReadPixels.
struct StealthWebGLReadback final {
  StealthWebGLReadback() = delete;

  // toDataURL/toBlob (GetImageBuffer and GetInputStream): the canvas noise, as
  // every reader of this canvas reads. aAlphaType is the alpha type
  // GetSurfaceSnapshot reported for aSnapshot. The snapshot itself is left
  // untouched; the result is a new surface, or aSnapshot again when the seed
  // is 0.
  static already_AddRefed<gfx::SourceSurface> ProjectReaderSnapshot(
      const ClientWebGLContext& aCtx, gfx::SourceSurface* aSnapshot,
      const gfxAlphaType aAlphaType) {
    return CanvasUtils::StealthProjectSnapshot(
        aSnapshot, aAlphaType != gfxAlphaType::NonPremult,
        aCtx.PrincipalOrNull());
  }

  // captureStream() is the only reader of the async snapshot
  // (DoReadPixelsAsync): its frames get the canvas noise like readPixels and
  // toDataURL. Projected there, once, on the stored pixels;
  // HTMLCanvasElement::GetSurfaceSnapshotAsync must not project this result
  // again (the same contract is stated where it is enforced, in
  // HTMLCanvasElement.cpp).
  //
  // aPremultiplied is the alpha type GetImageBuffer passes: only an alpha
  // context that is not premultiplied is NonPremult, that is
  // `!options.alpha || options.premultipliedAlpha`, computed when the read is
  // asked for.
  static RefPtr<gfx::SourceSurface> ProjectAsyncSnapshot(
      const ClientWebGLContext& aCtx, gfx::SourceSurface* aSurface,
      const bool aPremultiplied) {
    return CanvasUtils::StealthProjectSnapshot(aSurface, aPremultiplied,
                                               aCtx.PrincipalOrNull());
  }

  // readPixels into an array: the read itself (ClientWebGLContext::
  // DoReadPixels), then the noise on the bytes the page receives. Returns what
  // DoReadPixels returned.
  static bool ReadPixels(const ClientWebGLContext& aCtx,
                         const webgl::ReadPixelsDesc& aDesc,
                         const Span<uint8_t> aDest) {
    webgl::ReadPixelsResult written;
    if (!aCtx.DoReadPixels(aDesc, aDest, &written)) {
      return false;
    }
    ProjectReadPixels(aCtx, aDesc, aDest, written);
    return true;
  }

  // The canvas noise for a readPixels into a PIXEL_PACK_BUFFER, after the host
  // wrote it: reads the same pixels into memory with the buffer unbound,
  // applies the noise as readPixels into an array applies it, and writes them
  // back over the buffer, so the buffer holds what a page's readPixels into an
  // array would have given. Only RGBA/UNSIGNED_BYTE, only with a seed, only
  // with the bound PBO big enough for the read (otherwise the host refused the
  // read and wrote nothing). It costs one more read, a tight one, and the small
  // reads of the pixels around it inside ProjectReadPixels. The write back is
  // ONE BufferSubData when the buffer's rows lie as the tight ones do (full
  // rows, no skipped pixels, the same stride: the usual read), else one per
  // row.
  static void ProjectReadPixelsPbo(const ClientWebGLContext& aCtx,
                                   const webgl::ReadPixelsDesc& aDesc,
                                   const WebGLsizeiptr aOffset) {
    const uint64_t offset = static_cast<uint64_t>(aOffset);
    if (aDesc.pi.format != LOCAL_GL_RGBA ||
        aDesc.pi.type != LOCAL_GL_UNSIGNED_BYTE || !aDesc.size.x ||
        !aDesc.size.y) {
      return;
    }
    if (!CanvasUtils::StealthNoise(aCtx.PrincipalOrNull())) {
      return;
    }
    const auto& bound = aCtx.State().mBoundBufferByTarget;
    const auto found = bound.find(LOCAL_GL_PIXEL_PACK_BUFFER);
    if (found == bound.end() || !found->second) {
      return;  // the host refused the read and raised the error
    }
    const RefPtr<WebGLBufferJS> pbo = found->second;
    // Where the page's packing put each row in the buffer. For UNSIGNED_BYTE
    // the alignment is in bytes.
    const auto& packing = aDesc.packState;
    const uint64_t rowPixels =
        packing.rowLength ? packing.rowLength : aDesc.size.x;
    const uint64_t align = packing.alignmentInTypeElems;
    const uint64_t stride = (rowPixels * 4 + align - 1) / align * align;
    const uint64_t needed = offset +
                            (packing.skipRows + aDesc.size.y - 1) * stride +
                            (packing.skipPixels + aDesc.size.x) * 4;
    const auto size =
        BufferParameter(aCtx, LOCAL_GL_PIXEL_PACK_BUFFER, LOCAL_GL_BUFFER_SIZE);
    if (!size || needed > uint64_t(*size)) {
      return;  // too small: the host refused the read and wrote nothing
    }
    // The same pixels read into memory, with the buffer unbound for the time of
    // the read, and the noise applied as readPixels into an array applies it.
    webgl::ReadPixelsDesc tight = aDesc;
    tight.packState = {};
    std::vector<uint8_t> bytes(size_t(aDesc.size.x) * aDesc.size.y * 4);
    aCtx.Run<STEALTH_WEBGL_RPROC(BindBuffer)>(LOCAL_GL_PIXEL_PACK_BUFFER, 0);
    webgl::ReadPixelsResult written;
    const bool read =
        aCtx.DoReadPixels(tight, Span<uint8_t>(bytes), &written);
    if (read) {
      ProjectReadPixels(aCtx, tight, Span<uint8_t>(bytes), written);
    }
    aCtx.Run<STEALTH_WEBGL_RPROC(BindBuffer)>(LOCAL_GL_PIXEL_PACK_BUFFER,
                                              pbo->mId);
    if (!read || written.subrect.IsEmpty()) {
      return;
    }
    const auto& sub = written.subrect;
    // Full rows laid as the buffer lays them: no gap between two rows to keep,
    // so the whole block goes in one command (a command per row was 1024 of
    // them for a 1024-row read).
    if (!packing.skipPixels && !sub.X() &&
        uint64_t(sub.Width()) * 4 == stride && written.byteStride == stride) {
      const uint64_t dst =
          offset + (packing.skipRows + uint64_t(sub.Y())) * stride;
      const uint8_t* src = bytes.data() + size_t(sub.Y()) * written.byteStride;
      aCtx.Run<STEALTH_WEBGL_RPROC(BufferSubData)>(
          LOCAL_GL_PIXEL_PACK_BUFFER, dst,
          Span<const uint8_t>(src, size_t(sub.Height()) * stride),
          /* unsynchronized */ false);
      return;
    }
    // Over the bytes the host wrote, row by row, so the gaps a packing leaves
    // between rows stay what they were.
    for (int32_t y = sub.Y(); y < sub.YMost(); ++y) {
      const uint64_t dst = offset + (packing.skipRows + uint64_t(y)) * stride +
                           (packing.skipPixels + uint64_t(sub.X())) * 4;
      const uint8_t* src =
          bytes.data() + size_t(y) * written.byteStride + size_t(sub.X()) * 4;
      aCtx.Run<STEALTH_WEBGL_RPROC(BufferSubData)>(
          LOCAL_GL_PIXEL_PACK_BUFFER, dst,
          Span<const uint8_t>(src, size_t(sub.Width()) * 4),
          /* unsynchronized */ false);
    }
  }

 private:
  // The canvas noise on what a page's readPixels wrote into aDest
  // (gfx::StealthProjectBlockInCanvas on the bytes the page received, in
  // place). aWritten is what the read wrote: the part of the requested
  // rectangle inside the framebuffer, and the row stride.
  static void ProjectReadPixels(const ClientWebGLContext& aCtx,
                                const webgl::ReadPixelsDesc& aDesc,
                                const Span<uint8_t> aDest,
                                const webgl::ReadPixelsResult& aWritten) {
    // RGBA/UNSIGNED_BYTE only, the format of every default framebuffer and the
    // one readPixels always accepts. The float and integer formats of a user
    // framebuffer need their own definition of the bit the noise owns (an open
    // entry in the workbench docs); until then they read as drawn.
    if (aDesc.pi.format != LOCAL_GL_RGBA ||
        aDesc.pi.type != LOCAL_GL_UNSIGNED_BYTE) {
      return;
    }
    const gfx::StealthCanvasNoise noise =
        CanvasUtils::StealthNoise(aCtx.PrincipalOrNull());
    if (!noise || aWritten.subrect.IsEmpty() || !aWritten.byteStride) {
      return;
    }
    // The pixels the page's read wrote, where it wrote them: row by row, from
    // the first of them, with the page's own packing. They ARE the framebuffer's
    // pixels, so the projection runs on them where they lie.
    const gfx::IntRect sub = aWritten.subrect;
    const auto& packing = aDesc.packState;
    const size_t firstByte =
        size_t(packing.skipRows + sub.Y()) * aWritten.byteStride +
        size_t(packing.skipPixels + sub.X()) * 4;
    const size_t lastByte = firstByte +
                            size_t(sub.Height() - 1) * aWritten.byteStride +
                            size_t(sub.Width()) * 4;
    if (lastByte > aDest.size()) {
      return;
    }
    // Its neighbours outside the block are the ones a read of the block grown
    // by a pixel returned: the pixels of the framebuffer around it, and, where
    // the framebuffer has none (the block is at its edge), the block's own edge
    // pixel. Which sides may have pixels: the read left a side out of the block
    // only because the framebuffer ended there, so a block that does not reach
    // the request's own edge has none beside it; one that does may have, and the
    // host says (a read of nothing answers false, and raises no error).
    const gfx::StealthBlockEdges mayHave = {
        !sub.Y(), uint64_t(sub.YMost()) == aDesc.size.y, !sub.X(),
        uint64_t(sub.XMost()) == aDesc.size.x};
    // The default framebuffer of a premultipliedAlpha context stores
    // premultiplied pixels; a user framebuffer stores whatever was drawn.
    const auto& options = aCtx.mNotLost->info.options;
    const bool premultiplied = !aCtx.State().mBoundReadFb && options.alpha &&
                               options.premultipliedAlpha;
    auto read = [&](int32_t aX, int32_t aY, int32_t aW, int32_t aH,
                    uint8_t* aOut) {
      return ReadStrip(aCtx, aDesc, aX, aY, aW, aH, aOut);
    };
    gfx::StealthProjectBlockInCanvas(
        aDest.data() + firstByte, int32_t(aWritten.byteStride),
        gfx::IntSize(sub.Width(), sub.Height()), gfx::SurfaceFormat::R8G8B8A8,
        premultiplied,
        gfx::IntPoint(aDesc.srcOffset.x + sub.X(), aDesc.srcOffset.y + sub.Y()),
        mayHave, read, noise);
  }

  // A read of the framebuffer, aW x aH pixels at (aX, aY), into aOut, tightly
  // packed, with what aDesc says of the format (RGBA/UNSIGNED_BYTE). False when
  // the framebuffer has no pixel of the rectangle, or not all of it.
  static bool ReadStrip(const ClientWebGLContext& aCtx,
                        const webgl::ReadPixelsDesc& aDesc, int32_t aX,
                        int32_t aY, int32_t aW, int32_t aH, uint8_t* aOut) {
    webgl::ReadPixelsDesc strip = aDesc;
    strip.srcOffset = {aX, aY};
    strip.size = {uint32_t(aW), uint32_t(aH)};
    strip.packState = {};
    const size_t stride = size_t(aW) * 4;
    webgl::ReadPixelsResult res;
    return aCtx.DoReadPixels(strip, Span<uint8_t>(aOut, stride * size_t(aH)),
                             &res) &&
           res.byteStride == stride && res.subrect.X() == 0 &&
           res.subrect.Y() == 0 && res.subrect.Width() == aW &&
           res.subrect.Height() == aH;
  }

  // The same IPC read as ClientWebGLContext::GetBufferParameter, for the
  // projection's own use. Nothing() when the context is lost or the host does
  // not answer.
  static Maybe<double> BufferParameter(const ClientWebGLContext& aCtx,
                                       const GLenum aTarget,
                                       const GLenum aPname) {
    RefPtr<webgl::NotLostData> notLost(aCtx.mNotLost);
    if (!notLost) {
      return Nothing();
    }
    const auto& child = notLost->outOfProcess;
    child->FlushPendingCmds();
    Maybe<double> ret;
    if (!child->SendGetBufferParameter(aTarget, aPname, &ret)) {
      ret.reset();
    }
    return ret;
  }
};

}  // namespace mozilla

#undef STEALTH_WEBGL_RPROC

#endif  // DOM_CANVAS_STEALTHWEBGLREADBACK_H_
