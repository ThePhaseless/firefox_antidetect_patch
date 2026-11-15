/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "mozilla/gfx/StealthCanvasProjection.h"

#include <stdint.h>
#include <string.h>

#include "DrawEventRecorder.h"
#include "RecordedEventImpl.h"
#include "mozilla/gfx/2D.h"
#include "mozilla/gfx/StealthRefuse.h"
#include "nsTArray.h"

namespace mozilla {
namespace gfx {

namespace {

// Where R, G, B and A sit in a pixel of each supported format, and whether the
// fourth byte is a real alpha. A type, so the loops below know them when they
// are compiled.
template <int kR, int kG, int kB, int kA, bool kHasAlpha>
struct ProjPixel {
  static constexpr int R = kR;
  static constexpr int G = kG;
  static constexpr int B = kB;
  static constexpr bool hasAlpha = kHasAlpha;

  // A pixel as the projection sees it, in ONE canonical order whatever the
  // storage: R G B A from the high byte down, the low bit of R, G and B
  // cleared.
  static inline uint32_t Canonical(const uint8_t* aPx) {
    const uint32_t a = kHasAlpha ? aPx[kA] : 255u;
    return (uint32_t(aPx[kR] & 0xfe) << 24) | (uint32_t(aPx[kG] & 0xfe) << 16) |
           (uint32_t(aPx[kB] & 0xfe) << 8) | a;
  }
};

bool SupportedFormat(SurfaceFormat aFormat) {
  switch (aFormat) {
    case SurfaceFormat::B8G8R8A8:
    case SurfaceFormat::B8G8R8X8:
    case SurfaceFormat::R8G8B8A8:
    case SurfaceFormat::R8G8B8X8:
      return true;
    default:
      return false;
  }
}

// Calls aFn with the ProjPixel of aFormat; false for a format that is not
// supported.
template <class Fn>
bool WithFormat(SurfaceFormat aFormat, Fn&& aFn) {
  switch (aFormat) {
    case SurfaceFormat::B8G8R8A8:
      aFn(ProjPixel<2, 1, 0, 3, true>());
      return true;
    case SurfaceFormat::B8G8R8X8:
      aFn(ProjPixel<2, 1, 0, 3, false>());
      return true;
    case SurfaceFormat::R8G8B8A8:
      aFn(ProjPixel<0, 1, 2, 3, true>());
      return true;
    case SurfaceFormat::R8G8B8X8:
      aFn(ProjPixel<0, 1, 2, 3, false>());
      return true;
    default:
      return false;
  }
}

inline uint32_t Mix(uint32_t h) {
  h ^= h >> 16;
  h *= 0x85ebca6bu;
  h ^= h >> 13;
  h *= 0xc2b2ae35u;
  h ^= h >> 16;
  return h;
}

inline int32_t ChannelOf(uint32_t aValue, int aShift) {
  return int32_t((aValue >> aShift) & 0xffu);
}

// The squared distance between two canonical values, in RGBA channel units.
// Four differences of at most 255 each: 4 * 255^2 = 260100, far inside int32.
inline int32_t Dist2(uint32_t a, uint32_t b) {
  int32_t s = 0;
  for (int shift = 0; shift < 32; shift += 8) {
    const int32_t d = ChannelOf(a, shift) - ChannelOf(b, shift);
    s += d * d;
  }
  return s;
}

// Do these colours all lie on ONE straight segment, between the two of them
// farthest apart, within aTol channel units? That is what a pixel looks like
// when it is a blend of two colours: text (the ink over the background at a
// coverage level, at ANY contrast), the antialiased edge between two fills, a
// two-stop gradient. A real machine differs from another there in WHICH blend
// a pixel gets, never by a third colour, and a touched pixel would be a level
// that rasteriser does not produce (an 18th grey in DirectWrite text).
//
// Integer arithmetic only, so the content process, the GPU process and a
// worker, on Windows and on Linux, decide every pixel the same way: a float
// compared with a threshold could split them. The farthest pair is the first
// found in a fixed order; the distance from a colour r to the segment p-q is
// tested as |r-p|^2 * L - t^2 <= tol^2 * L, with t = (r-p).(q-p) and L = |q-p|^2,
// clamped to the end points.
//
// The answer is the one the plain search over the nine colours gives (the
// reference copy in TestStealthCanvasProjectionEquivalence.cpp is compared
// with this one byte for byte); two exits and a cheaper search reach it
// without that search for most pixels:
//   1. One colour or two (a hard edge, a flat area with a corner): on a
//      segment, whatever it is. The farthest pair is those two colours, and
//      every other colour is one of its ends, at distance 0.
//   2. Every pairwise distance within the tolerance: L <= tol^2, since each
//      channel of any two colours differs by at most that channel's range in
//      the nine, and the squares of the ranges sum to a bound of L. Then every
//      colour is within tol of p, and the test never fails for it: for t <= 0
//      the test IS |r-p|^2 <= tol^2; for t >= L it is |r-q|^2, and
//      |r-q|^2 = |r-p|^2 - 2t + L <= |r-p|^2; between, it is
//      |r-p|^2 * L - t^2 <= |r-p|^2 * L <= tol^2 * L. A smooth gradient lands
//      here.
//   3. Otherwise the search itself, over the distinct colours in order of
//      first appearance (the first farthest pair of the nine, ties included,
//      is the pair of their first appearances), in int32 where nothing can
//      overflow: only the product |r-p|^2 * L and t^2 (up to 6.8e10) need 64
//      bits.
bool OnOneSegment(const uint32_t (&aColours)[9], int32_t aTol) {
  // 1.
  const uint32_t first = aColours[0];
  uint32_t other = first;  // equal to first: no second colour seen yet
  bool twoOrFewer = true;
  for (int i = 1; i < 9; ++i) {
    const uint32_t v = aColours[i];
    if (v == first) {
      continue;
    }
    if (other == first) {
      other = v;
    } else if (v != other) {
      twoOrFewer = false;
      break;
    }
  }
  if (twoOrFewer) {
    return true;
  }

  const int32_t tol2 = aTol * aTol;

  // 2.
  {
    int32_t bound = 0;
    for (int shift = 0; shift < 32 && bound <= tol2; shift += 8) {
      int32_t lo = 255;
      int32_t hi = 0;
      for (uint32_t v : aColours) {
        const int32_t ch = ChannelOf(v, shift);
        lo = ch < lo ? ch : lo;
        hi = ch > hi ? ch : hi;
      }
      bound += (hi - lo) * (hi - lo);
    }
    if (bound <= tol2) {
      return true;
    }
  }

  // 3. At least three distinct colours.
  uint32_t u[9];
  int n = 0;
  for (uint32_t v : aColours) {
    bool seen = false;
    for (int j = 0; j < n && !seen; ++j) {
      seen = u[j] == v;
    }
    if (!seen) {
      u[n++] = v;
    }
  }
  int32_t len = -1;
  int pi = 0;
  int qi = 0;
  for (int i = 0; i < n; ++i) {
    for (int j = i + 1; j < n; ++j) {
      const int32_t d = Dist2(u[i], u[j]);
      if (d > len) {
        len = d;
        pi = i;
        qi = j;
      }
    }
  }
  const uint32_t p = u[pi];
  const uint32_t q = u[qi];
  for (int k = 0; k < n; ++k) {
    if (k == pi || k == qi) {
      continue;  // an end of the segment is on it
    }
    const uint32_t r = u[k];
    int32_t t = 0;
    for (int shift = 0; shift < 32; shift += 8) {
      const int32_t w = ChannelOf(r, shift) - ChannelOf(p, shift);
      const int32_t v = ChannelOf(q, shift) - ChannelOf(p, shift);
      t += w * v;
    }
    bool nearSegment;
    if (t <= 0) {
      nearSegment = Dist2(r, p) <= tol2;
    } else if (t >= len) {
      nearSegment = Dist2(r, q) <= tol2;
    } else {
      nearSegment = int64_t(Dist2(r, p)) * len - int64_t(t) * t <=
                    int64_t(tol2) * len;
    }
    if (!nearSegment) {
      return false;
    }
  }
  return true;
}

// One row of canonical values (the row, a pixel of padding on each side), and,
// made when a pixel of the row needs them, the Mix of each.
struct RowBuf {
  uint32_t* canon = nullptr;
  uint32_t* mix = nullptr;
  bool mixed = false;
};

inline const uint32_t* MixedRow(RowBuf* aRow, size_t aCount) {
  if (!aRow->mixed) {
    for (size_t i = 0; i < aCount; ++i) {
      aRow->mix[i] = Mix(aRow->canon[i]);
    }
    aRow->mixed = true;
  }
  return aRow->mix;
}

// The rows of a surface: aRect's columns of row aY (an aY outside the surface
// is the nearest row), a pixel of padding on each side (the nearest column of
// the surface).
template <class Px>
struct SurfaceRows {
  const uint8_t* mSrc;
  int32_t mStride;
  int32_t mWidth;
  int32_t mHeight;
  int32_t mX0;
  int32_t mRw;

  void Fill(uint32_t* aRow, int32_t aY) const {
    const int32_t y = aY < 0 ? 0 : (aY >= mHeight ? mHeight - 1 : aY);
    const uint8_t* line = mSrc + ptrdiff_t(y) * mStride;
    const int32_t left = mX0 > 0 ? mX0 - 1 : 0;
    const int32_t right = mX0 + mRw < mWidth ? mX0 + mRw : mWidth - 1;
    aRow[0] = Px::Canonical(line + 4 * ptrdiff_t(left));
    for (int32_t i = 1; i <= mRw; ++i) {
      aRow[i] = Px::Canonical(line + 4 * ptrdiff_t(mX0 - 1 + i));
    }
    aRow[mRw + 1] = Px::Canonical(line + 4 * ptrdiff_t(right));
  }
};

// The rows of a block with the pixels around it (StealthBlockFrame): row aY
// (-1 .. height) of the block, a padding pixel on each side. A side the frame
// has no pixels on is the nearest row or column of the block, as the edge of
// a surface is.
template <class Px>
struct BlockRows {
  const uint8_t* mBase;
  int32_t mStride;
  int32_t mWidth;
  int32_t mHeight;
  const StealthBlockFrame* mFrame;

  void Fill(uint32_t* aRow, int32_t aY) const {
    const StealthBlockFrame& f = *mFrame;
    int32_t y = aY;
    if (y < 0 && !f.top) {
      y = 0;
    } else if (y >= mHeight && !f.bottom) {
      y = mHeight - 1;
    }
    const uint8_t* line;
    if (y < 0) {
      line = f.top;
    } else if (y >= mHeight) {
      line = f.bottom;
    } else {
      line = mBase + ptrdiff_t(y) * mStride;
    }
    for (int32_t x = 0; x < mWidth; ++x) {
      aRow[1 + x] = Px::Canonical(line + 4 * ptrdiff_t(x));
    }
    if (f.left) {
      const uint8_t* px;
      if (y < 0) {
        px = f.corners;
      } else if (y >= mHeight) {
        px = f.corners + 8;
      } else {
        px = f.left + 4 * ptrdiff_t(y);
      }
      aRow[0] = Px::Canonical(px);
    } else {
      aRow[0] = aRow[1];
    }
    if (f.right) {
      const uint8_t* px;
      if (y < 0) {
        px = f.corners + 4;
      } else if (y >= mHeight) {
        px = f.corners + 12;
      } else {
        px = f.right + 4 * ptrdiff_t(y);
      }
      aRow[mWidth + 1] = Px::Canonical(px);
    } else {
      aRow[mWidth + 1] = aRow[mWidth];
    }
  }
};

// The projection of aRowCount rows of aRw pixels, the first being row aY0 of
// aRows, written to aOut (the first pixel of the first row) with aOutStride.
// Reads only the bits it does not write, so aOut may be where aRows read.
template <class Px, class Rows>
void ProjectRows(const Rows& aRows, int32_t aRw, int32_t aY0, int32_t aRowCount,
                 uint8_t* aOut, ptrdiff_t aOutStride, bool aPremultiplied,
                 uint32_t aSeed, int32_t aTolerance) {
  // Three rows of canonical values, each padded by one pixel on both sides,
  // so the inner loop has no bounds tests; and the Mix of each, kept for the
  // rows that need it.
  const size_t n = size_t(aRw) + 2;
  AutoTArray<uint32_t, 6 * 258> storage;
  storage.SetLength(6 * n);
  RowBuf bufs[3];
  for (size_t k = 0; k < 3; ++k) {
    bufs[k].canon = storage.Elements() + k * n;
    bufs[k].mix = storage.Elements() + (3 + k) * n;
  }
  RowBuf* up = &bufs[0];
  RowBuf* mid = &bufs[1];
  RowBuf* down = &bufs[2];
  aRows.Fill(up->canon, aY0 - 1);
  aRows.Fill(mid->canon, aY0);

  for (int32_t r = 0; r < aRowCount; ++r) {
    aRows.Fill(down->canon, aY0 + r + 1);
    down->mixed = false;
    uint8_t* out = aOut + ptrdiff_t(r) * aOutStride;
    const uint32_t* const U = up->canon;
    const uint32_t* const M = mid->canon;
    const uint32_t* const D = down->canon;
    for (int32_t i = 1; i <= aRw; ++i, out += 4) {
      const uint32_t c = M[i];
      const uint32_t alpha = c & 0xffu;
      if (alpha == 0) {
        continue;
      }
      // An edge: a 4-neighbour differs. A flat area is left exactly as drawn.
      if (c == U[i] && c == D[i] && c == M[i - 1] && c == M[i + 1]) {
        continue;
      }
      // And not a blend of TWO colours: the 3x3 neighbourhood must hold a third,
      // independent one (a shadow over a fill and the background, an emoji, the
      // junction of three shapes). Text at any contrast and the edge between two
      // fills are left exactly as drawn. This replaced a band on the step to the
      // neighbours (zoom.stealth.canvas.edge_step), which no step value could
      // make separate low-contrast coloured text from a gradient: a commercial
      // fingerprinting service's own rgba(102,204,0,0.2) line has the steps of
      // a gradient on retail too.
      const uint32_t around9[9] = {U[i - 1], U[i], U[i + 1],
                                   M[i - 1], c,    M[i + 1],
                                   D[i - 1], D[i], D[i + 1]};
      if (OnOneSegment(around9, aTolerance)) {
        continue;
      }
      // The 3x3 neighbourhood through a SUM: independent of row order and of
      // which neighbour is which, so a flipped or re-laid-out copy of the same
      // pixels gets the same key.
      const uint32_t* const mu = MixedRow(up, n);
      const uint32_t* const mm = MixedRow(mid, n);
      const uint32_t* const md = MixedRow(down, n);
      const uint32_t around = mu[i - 1] + mu[i] + mu[i + 1] + mm[i - 1] +
                              mm[i + 1] + md[i - 1] + md[i] + md[i + 1];
      const uint32_t key =
          Mix(aSeed ^ Mix(c * 0x9e3779b1u + 0x632be5abu) ^ (around * 0x27d4eb2fu));
      // The LOW bit of the key. db967d50 took the top one; a version with
      // zoom.stealth.canvas.edge_share chose WHICH edges to touch from the top
      // eight bits, and the bit written had to stay independent of that choice,
      // so it moved down. edge_share is gone, and both bits of Mix are uniform;
      // the low one stays because the measured builds of 2026-10-19 used it.
      uint8_t bit = uint8_t(key & 1u);
      const uint8_t r0 = uint8_t(c >> 24);
      const uint8_t g0 = uint8_t(c >> 16);
      const uint8_t b0 = uint8_t(c >> 8);
      if (bit && aPremultiplied && Px::hasAlpha &&
          ((r0 | 1u) > alpha || (g0 | 1u) > alpha || (b0 | 1u) > alpha)) {
        bit = 0;  // a premultiplied channel never exceeds its alpha
      }
      // WHICH channels carry the bit: only one whose value differs from that
      // channel in all eight neighbours. Values that differ are two apart once
      // the low bit is cleared, so a bit of noise on either side cannot swap
      // or level them, and every difference between neighbours keeps the sign
      // the drawing gave it: no new local extremum in any direction. The bit
      // on all three channels at once turned a channel constant across a shape
      // (the 0 of a red-green WebGL gradient) into isolated 1s, and a slow
      // gradient into +-1 spikes, the high-frequency signature that a page
      // reading back its own render can count (test_fingerprint_surface.py of
      // the wrapper, 117 spikes against 0). A channel left out keeps the drawn
      // value, low bit included. Channels equal to each other decide together,
      // so a grey stays grey.
      const uint8_t ch[3] = {r0, g0, b0};
      bool apart[3];
      for (int k = 0; k < 3; ++k) {
        const int shift = 24 - 8 * k;
        apart[k] = true;
        for (int m = 0; m < 9 && apart[k]; ++m) {
          apart[k] = m == 4 || uint8_t(around9[m] >> shift) != ch[k];
        }
      }
      bool carry[3];
      for (int k = 0; k < 3; ++k) {
        carry[k] = apart[k];
        for (int j = 0; j < 3; ++j) {
          carry[k] = carry[k] && (ch[j] != ch[k] || apart[j]);
        }
      }
      if (carry[0]) {
        out[Px::R] = uint8_t(r0 | bit);
      }
      if (carry[1]) {
        out[Px::G] = uint8_t(g0 | bit);
      }
      if (carry[2]) {
        out[Px::B] = uint8_t(b0 | bit);
      }
    }
    RowBuf* t = up;
    up = mid;
    mid = down;
    down = t;
  }
}

// A seed without its tolerance is a declaration only half carried: refused,
// not read as some built-in tolerance.
int32_t CheckedTolerance(const StealthCanvasNoise& aNoise) {
  if (aNoise.mEdgeTolerance < 0 || aNoise.mEdgeTolerance > 255) {
    StealthRefuse(
        "stealth: the canvas noise has a seed but no declared edge tolerance "
        "(zoom.stealth.canvas.edge_tolerance is %d, not 0-255)",
        int(aNoise.mEdgeTolerance));
  }
  return aNoise.mEdgeTolerance;
}

inline uint32_t SeedOf(const StealthCanvasNoise& aNoise) {
  return Mix(uint32_t(aNoise.mSeed) ^ 0x2545f491u);
}

}  // namespace

bool StealthProjectPixels(const uint8_t* aSrc, int32_t aSrcStride,
                          const IntSize& aSrcSize, SurfaceFormat aFormat,
                          const IntRect& aRect, uint8_t* aDst,
                          int32_t aDstStride, bool aPremultiplied,
                          const StealthCanvasNoise& aNoise) {
  if (!aNoise || !aSrc || !aDst || !SupportedFormat(aFormat)) {
    return false;
  }
  const IntRect rect = aRect.Intersect(IntRect(IntPoint(), aSrcSize));
  if (rect.IsEmpty()) {
    return false;
  }
  const uint32_t seed = SeedOf(aNoise);
  const int32_t tolerance = CheckedTolerance(aNoise);
  uint8_t* const out = aDst + ptrdiff_t(rect.Y() - aRect.Y()) * aDstStride +
                       4 * ptrdiff_t(rect.X() - aRect.X());
  return WithFormat(aFormat, [&](auto aPx) {
    using Px = decltype(aPx);
    const SurfaceRows<Px> rows = {aSrc,        aSrcStride,   aSrcSize.width,
                                  aSrcSize.height, rect.X(), rect.Width()};
    ProjectRows<Px>(rows, rect.Width(), rect.Y(), rect.Height(), out,
                    aDstStride, aPremultiplied, seed, tolerance);
  });
}

bool StealthProjectBlock(uint8_t* aPixels, int32_t aStride,
                         const IntSize& aSize, SurfaceFormat aFormat,
                         bool aPremultiplied, const StealthBlockFrame& aFrame,
                         const StealthCanvasNoise& aNoise) {
  if (!aNoise || !aPixels || !SupportedFormat(aFormat) || aSize.width <= 0 ||
      aSize.height <= 0) {
    return false;
  }
  const uint32_t seed = SeedOf(aNoise);
  const int32_t tolerance = CheckedTolerance(aNoise);
  return WithFormat(aFormat, [&](auto aPx) {
    using Px = decltype(aPx);
    const BlockRows<Px> rows = {aPixels, aStride, aSize.width, aSize.height,
                                &aFrame};
    ProjectRows<Px>(rows, aSize.width, 0, aSize.height, aPixels, aStride,
                    aPremultiplied, seed, tolerance);
  });
}

bool StealthProjectBlockInCanvas(
    uint8_t* aPixels, int32_t aStride, const IntSize& aSize,
    SurfaceFormat aFormat, bool aPremultiplied, const IntPoint& aOrigin,
    const StealthBlockEdges& aMayHave, const StealthPixelReader& aRead,
    const StealthCanvasNoise& aNoise) {
  if (!aNoise || !aPixels || !SupportedFormat(aFormat) || aSize.width <= 0 ||
      aSize.height <= 0) {
    return false;
  }
  const int32_t w = aSize.width;
  const int32_t h = aSize.height;
  // The ring: top, bottom (w pixels each), left, right (h pixels each) and the
  // four corners (top-left, top-right, bottom-left, bottom-right).
  nsTArray<uint8_t> ring;
  ring.SetLength((2 * size_t(w) + 2 * size_t(h) + 4) * 4);
  uint8_t* const topBuf = ring.Elements();
  uint8_t* const bottomBuf = topBuf + 4 * size_t(w);
  uint8_t* const leftBuf = bottomBuf + 4 * size_t(w);
  uint8_t* const rightBuf = leftBuf + 4 * size_t(h);
  uint8_t* const cornerBuf = rightBuf + 4 * size_t(h);

  // Coordinates are summed in 64 bits and nothing is read where they leave
  // int32: a request that far out has no pixels there.
  auto read = [&](int64_t aX, int64_t aY, int32_t aW, int32_t aH,
                  uint8_t* aOut) {
    if (aX < INT32_MIN || aX > INT32_MAX || aY < INT32_MIN || aY > INT32_MAX) {
      return false;
    }
    return aRead(int32_t(aX), int32_t(aY), aW, aH, aOut);
  };
  const int64_t x0 = aOrigin.x;
  const int64_t y0 = aOrigin.y;

  // The canvas holds pixels beside the block only where a read of them says
  // so; a side whose read answers false has none, and the nearest pixel of the
  // block is its neighbour there.
  StealthBlockFrame frame;
  if (aMayHave.top && read(x0, y0 - 1, w, 1, topBuf)) {
    frame.top = topBuf;
  }
  if (aMayHave.bottom && read(x0, y0 + h, w, 1, bottomBuf)) {
    frame.bottom = bottomBuf;
  }
  if (aMayHave.left && read(x0 - 1, y0, 1, h, leftBuf)) {
    frame.left = leftBuf;
  }
  if (aMayHave.right && read(x0 + w, y0, 1, h, rightBuf)) {
    frame.right = rightBuf;
  }
  // A corner is there when the two sides that meet at it are: the canvas is a
  // rectangle. If the canvas then does not answer, the neighbourhood is not
  // known and nothing is projected.
  if (frame.top && frame.left && !read(x0 - 1, y0 - 1, 1, 1, cornerBuf)) {
    return false;
  }
  if (frame.top && frame.right && !read(x0 + w, y0 - 1, 1, 1, cornerBuf + 4)) {
    return false;
  }
  if (frame.bottom && frame.left &&
      !read(x0 - 1, y0 + h, 1, 1, cornerBuf + 8)) {
    return false;
  }
  if (frame.bottom && frame.right &&
      !read(x0 + w, y0 + h, 1, 1, cornerBuf + 12)) {
    return false;
  }
  frame.corners = cornerBuf;
  return StealthProjectBlock(aPixels, aStride, aSize, aFormat, aPremultiplied,
                             frame, aNoise);
}

already_AddRefed<DataSourceSurface> StealthProjectedRegion(
    DataSourceSurface* aSource, const IntRect& aRect, bool aPremultiplied,
    const StealthCanvasNoise& aNoise) {
  if (!aSource || aRect.IsEmpty()) {
    return nullptr;
  }
  const SurfaceFormat format = aSource->GetFormat();
  RefPtr<DataSourceSurface> out =
      Factory::CreateDataSourceSurface(aRect.Size(), format);
  if (!out) {
    return nullptr;
  }
  DataSourceSurface::ScopedMap src(aSource, DataSourceSurface::READ);
  DataSourceSurface::ScopedMap dst(out, DataSourceSurface::WRITE);
  if (!src.IsMapped() || !dst.IsMapped()) {
    return nullptr;
  }
  const IntSize size = aSource->GetSize();
  const IntRect inside = aRect.Intersect(IntRect(IntPoint(), size));
  // The plain copy first, so every pixel the projection leaves alone (a flat
  // area, alpha 0, a part of aRect outside the surface) is the drawn one.
  const int32_t bpp = BytesPerPixel(format);
  for (int32_t y = inside.Y(); y < inside.YMost(); ++y) {
    memcpy(dst.GetData() + ptrdiff_t(y - aRect.Y()) * dst.GetStride() +
               bpp * ptrdiff_t(inside.X() - aRect.X()),
           src.GetData() + ptrdiff_t(y) * src.GetStride() +
               bpp * ptrdiff_t(inside.X()),
           size_t(inside.Width()) * bpp);
  }
  StealthProjectPixels(src.GetData(), src.GetStride(), size, format, aRect,
                       dst.GetData(), dst.GetStride(), aPremultiplied, aNoise);
  return out.forget();
}

// The projected stand-in reads as projected here too.
already_AddRefed<DataSourceSurface> StealthProjectOriginal(
    SourceSurface* aOriginal, const IntSize& aSize,
    const StealthStandIn& aStandIn) {
  RefPtr<DataSourceSurface> data = aOriginal->GetDataSurface();
  if (data && aStandIn.noise) {
    return StealthProjectedRegion(data, IntRect(IntPoint(), aSize),
                                  aStandIn.premultiplied, aStandIn.noise);
  }
  return data.forget();
}

// Since 157 a canvas recording wraps its snapshots in a surface whose
// GetType() is CANVAS_RECORDING (gfx/layers/ipc/CanvasChild.cpp); what it
// wraps is what GetUnderlyingType() answers. Those are the surfaces this was
// written for, so the test is on the underlying type: a plain RECORDING
// surface answers RECORDING there too.
bool StealthCanProjectRecording(SourceSurface* aSurface,
                                const StealthCanvasNoise& aNoise) {
  return aSurface && aSurface->GetUnderlyingType() == SurfaceType::RECORDING &&
         aNoise;
}

void StealthRecordProjection(const DrawTargetRecording* aDT,
                             DrawEventRecorderPrivate* aRecorder,
                             SourceSurface* aSurface, const void* aStandIn,
                             bool aPremultiplied,
                             const StealthCanvasNoise& aNoise) {
  aRecorder->RecordEvent(
      aDT, RecordedStealthProjectSurface(aSurface, aStandIn, aPremultiplied,
                                         aNoise));
}

}  // namespace gfx
}  // namespace mozilla
