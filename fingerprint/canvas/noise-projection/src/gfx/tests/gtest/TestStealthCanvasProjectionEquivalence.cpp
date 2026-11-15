/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The projection was made linear in the pixels (gfx/2d/StealthCanvasProjection.cpp:
// exits that skip the pixels whose neighbourhood is flat or a blend of two
// colours, int32 distances, the rows of a read block taken where they lie
// instead of through a second, larger read), and its bytes must not have moved
// by one. The page reads them, and two builds of the engine, or one build
// before and after a speed-up, must give the same canvas for the same seed.
//
// So this file keeps, copied, the function as it was before (namespace eq,
// "Ref"), and compares the new one with it byte for byte, the whole output
// buffer, padding included, on images that put each decision of the function to
// the test: flat areas, a half and half, antialiased blends of two colours,
// gradients, random noise of several kinds, all tolerances, both alpha types,
// the four formats, odd sizes and 1xN, rectangles that touch every edge of the
// surface or leave it. The block read (StealthProjectBlockInCanvas) is
// compared with what the code did before it, a read of the rectangle grown by a
// pixel on every side projected as a surface.
//
// The reference is NOT to be edited to follow the function: if the projection
// changes on purpose, the decision doc changes first and this copy with it.
// A test of speed against the copy is at the end.

#include <string.h>

#include <algorithm>
#include <chrono>
#include <functional>
#include <string>
#include <vector>

#include "gtest/gtest.h"
#include "mozilla/gfx/2D.h"
#include "mozilla/gfx/StealthCanvasProjection.h"

using namespace mozilla;
using namespace mozilla::gfx;

namespace eq {

// ---------------------------------------------------------------------------
// The reference: StealthProjectPixels as it was before the rewrite. Only the
// array of the three rows is a std::vector, and a tolerance outside 0-255
// (which the real one refuses by crashing) answers false.

struct RefLayout {
  int r, g, b, a;
  bool hasAlpha;
};

bool RefLayoutOf(SurfaceFormat aFormat, RefLayout* aOut) {
  switch (aFormat) {
    case SurfaceFormat::B8G8R8A8:
      *aOut = {2, 1, 0, 3, true};
      return true;
    case SurfaceFormat::B8G8R8X8:
      *aOut = {2, 1, 0, 3, false};
      return true;
    case SurfaceFormat::R8G8B8A8:
      *aOut = {0, 1, 2, 3, true};
      return true;
    case SurfaceFormat::R8G8B8X8:
      *aOut = {0, 1, 2, 3, false};
      return true;
    default:
      return false;
  }
}

inline uint32_t RefMix(uint32_t h) {
  h ^= h >> 16;
  h *= 0x85ebca6bu;
  h ^= h >> 13;
  h *= 0xc2b2ae35u;
  h ^= h >> 16;
  return h;
}

inline uint32_t RefCanonical(const uint8_t* aPx, const RefLayout& aL) {
  const uint32_t a = aL.hasAlpha ? aPx[aL.a] : 255u;
  return (uint32_t(aPx[aL.r] & 0xfe) << 24) |
         (uint32_t(aPx[aL.g] & 0xfe) << 16) |
         (uint32_t(aPx[aL.b] & 0xfe) << 8) | a;
}

inline int64_t RefDist2(uint32_t a, uint32_t b) {
  int64_t s = 0;
  for (int shift = 0; shift < 32; shift += 8) {
    const int64_t d = int64_t((a >> shift) & 0xffu) - int64_t((b >> shift) & 0xffu);
    s += d * d;
  }
  return s;
}

bool RefOnOneSegment(const uint32_t (&aColours)[9], int64_t aTol) {
  int64_t len = -1;
  int pi = 0;
  int qi = 0;
  for (int i = 0; i < 9; ++i) {
    for (int j = i + 1; j < 9; ++j) {
      const int64_t d = RefDist2(aColours[i], aColours[j]);
      if (d > len) {
        len = d;
        pi = i;
        qi = j;
      }
    }
  }
  if (len <= 0) {
    return true;  // one colour
  }
  const uint32_t p = aColours[pi];
  const uint32_t q = aColours[qi];
  const int64_t tol2 = aTol * aTol;
  for (uint32_t r : aColours) {
    int64_t t = 0;
    for (int shift = 0; shift < 32; shift += 8) {
      const int64_t w = int64_t((r >> shift) & 0xffu) - int64_t((p >> shift) & 0xffu);
      const int64_t v = int64_t((q >> shift) & 0xffu) - int64_t((p >> shift) & 0xffu);
      t += w * v;
    }
    bool nearSegment;
    if (t <= 0) {
      nearSegment = RefDist2(r, p) <= tol2;
    } else if (t >= len) {
      nearSegment = RefDist2(r, q) <= tol2;
    } else {
      nearSegment = RefDist2(r, p) * len - t * t <= tol2 * len;
    }
    if (!nearSegment) {
      return false;
    }
  }
  return true;
}

bool RefProjectPixels(const uint8_t* aSrc, int32_t aSrcStride,
                      const IntSize& aSrcSize, SurfaceFormat aFormat,
                      const IntRect& aRect, uint8_t* aDst, int32_t aDstStride,
                      bool aPremultiplied, const StealthCanvasNoise& aNoise) {
  RefLayout l;
  if (!aNoise || !aSrc || !aDst || !RefLayoutOf(aFormat, &l)) {
    return false;
  }
  const IntRect rect = aRect.Intersect(IntRect(IntPoint(), aSrcSize));
  if (rect.IsEmpty()) {
    return false;
  }
  const int32_t w = aSrcSize.width;
  const int32_t h = aSrcSize.height;
  const uint32_t seed = RefMix(uint32_t(aNoise.mSeed) ^ 0x2545f491u);
  if (aNoise.mEdgeTolerance < 0 || aNoise.mEdgeTolerance > 255) {
    return false;
  }
  const int64_t tolerance = aNoise.mEdgeTolerance;

  const int32_t x0 = rect.X();
  const int32_t rw = rect.Width();
  std::vector<uint32_t> rows(3 * size_t(rw + 2));
  auto fill = [&](uint32_t* aRow, int32_t aY) {
    const int32_t y = aY < 0 ? 0 : (aY >= h ? h - 1 : aY);
    const uint8_t* line = aSrc + ptrdiff_t(y) * aSrcStride;
    for (int32_t i = 0; i < rw + 2; ++i) {
      int32_t x = x0 - 1 + i;
      x = x < 0 ? 0 : (x >= w ? w - 1 : x);
      aRow[i] = RefCanonical(line + 4 * x, l);
    }
  };
  uint32_t* up = rows.data();
  uint32_t* mid = up + (rw + 2);
  uint32_t* down = mid + (rw + 2);
  fill(up, rect.Y() - 1);
  fill(mid, rect.Y());

  for (int32_t y = rect.Y(); y < rect.YMost(); ++y) {
    fill(down, y + 1);
    uint8_t* out = aDst + ptrdiff_t(y - aRect.Y()) * aDstStride +
                   4 * ptrdiff_t(x0 - aRect.X());
    for (int32_t i = 1; i <= rw; ++i, out += 4) {
      const uint32_t c = mid[i];
      const uint32_t alpha = c & 0xffu;
      if (alpha == 0) {
        continue;
      }
      if (c == up[i] && c == down[i] && c == mid[i - 1] && c == mid[i + 1]) {
        continue;
      }
      const uint32_t around9[9] = {up[i - 1],  up[i],  up[i + 1],
                                   mid[i - 1], c,      mid[i + 1],
                                   down[i - 1], down[i], down[i + 1]};
      if (RefOnOneSegment(around9, tolerance)) {
        continue;
      }
      const uint32_t around = RefMix(up[i - 1]) + RefMix(up[i]) +
                              RefMix(up[i + 1]) + RefMix(mid[i - 1]) +
                              RefMix(mid[i + 1]) + RefMix(down[i - 1]) +
                              RefMix(down[i]) + RefMix(down[i + 1]);
      const uint32_t key = RefMix(seed ^ RefMix(c * 0x9e3779b1u + 0x632be5abu) ^
                                  (around * 0x27d4eb2fu));
      uint8_t bit = uint8_t(key & 1u);
      const uint8_t r0 = uint8_t(c >> 24);
      const uint8_t g0 = uint8_t(c >> 16);
      const uint8_t b0 = uint8_t(c >> 8);
      if (bit && aPremultiplied && l.hasAlpha &&
          ((r0 | 1u) > alpha || (g0 | 1u) > alpha || (b0 | 1u) > alpha)) {
        bit = 0;
      }
      const uint8_t ch[3] = {r0, g0, b0};
      bool apart[3];
      for (int k = 0; k < 3; ++k) {
        const int shift = 24 - 8 * k;
        apart[k] = true;
        for (int n = 0; n < 9 && apart[k]; ++n) {
          apart[k] = n == 4 || uint8_t(around9[n] >> shift) != ch[k];
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
        out[l.r] = uint8_t(r0 | bit);
      }
      if (carry[1]) {
        out[l.g] = uint8_t(g0 | bit);
      }
      if (carry[2]) {
        out[l.b] = uint8_t(b0 | bit);
      }
    }
    uint32_t* t = up;
    up = mid;
    mid = down;
    down = t;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Images.

struct Rng {
  uint32_t s;
  uint32_t Next() {
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    return s;
  }
  uint32_t Below(uint32_t aN) { return (Next() >> 8) % aN; }
};

struct Image {
  std::string name;
  int32_t w = 0;
  int32_t h = 0;
  std::vector<uint8_t> px;  // w * h * 4, tight, four bytes in the order of the format under test
  void Set(int32_t x, int32_t y, int r, int g, int b, int a) {
    uint8_t* p = &px[(size_t(y) * w + x) * 4];
    p[0] = uint8_t(r);
    p[1] = uint8_t(g);
    p[2] = uint8_t(b);
    p[3] = uint8_t(a);
  }
};

int Clamp255(int v) { return v < 0 ? 0 : (v > 255 ? 255 : v); }

enum Kind {
  kFlat,
  kFlatAlpha0,
  kFlatAlpha128,
  kFlatBlack,
  kHalf,
  kChecker,
  kTriangleBlend,
  kTrianglePremult,
  kGradientH,
  kGradient2D,
  kGradientSteep,
  kGradientAlpha,
  kNoiseRgba,
  kNoiseRgb,
  kNoiseAlpha01,
  kNoisePalette3,
  kNoiseNear3,
  kNoiseNear12,
  kNoiseNear40,
  kNoiseLine,
  kNoiseLineJitter,
  kKinds
};

const char* const kKindNames[kKinds] = {
    "flat",          "flat-alpha0",    "flat-alpha128",  "flat-black",
    "half",          "checker",        "triangle-blend", "triangle-premult",
    "gradient-h",    "gradient-2d",    "gradient-steep", "gradient-alpha",
    "noise-rgba",    "noise-rgb",      "noise-alpha01",  "noise-palette3",
    "noise-near3",   "noise-near12",   "noise-near40",   "noise-line",
    "noise-line-j2"};

Image Make(Kind aKind, int32_t aW, int32_t aH, uint32_t aSeed) {
  Image img;
  img.name = std::string(kKindNames[aKind]) + " " + std::to_string(aW) + "x" +
             std::to_string(aH) + " #" + std::to_string(aSeed);
  img.w = aW;
  img.h = aH;
  img.px.assign(size_t(aW) * aH * 4, 0);
  Rng rng{aSeed * 2654435761u + 0x9e3779b9u};
  // Two colours for the noise that lies along a segment, and the palette.
  const int baseColour[4] = {int(rng.Below(256)), int(rng.Below(256)),
                       int(rng.Below(256)), 255};
  const int farColour[4] = {int(rng.Below(256)), int(rng.Below(256)),
                      int(rng.Below(256)), 255};
  const int palette[3][4] = {{255, 255, 255, 255}, {17, 99, 201, 255}, {250, 30, 60, 255}};
  for (int32_t y = 0; y < aH; ++y) {
    for (int32_t x = 0; x < aW; ++x) {
      // Four draws per pixel, in this order, whatever the kind: the image does
      // not depend on the order a compiler evaluates arguments in.
      const int n0 = int(rng.Below(256));
      const int n1 = int(rng.Below(256));
      const int n2 = int(rng.Below(256));
      const int n3 = int(rng.Below(256));
      switch (aKind) {
        case kFlat:
          img.Set(x, y, 200, 100, 51, 255);
          break;
        case kFlatAlpha0:
          img.Set(x, y, 10, 20, 31, 0);
          break;
        case kFlatAlpha128:
          img.Set(x, y, 90, 40, 17, 128);
          break;
        case kFlatBlack:
          img.Set(x, y, 0, 0, 0, 255);
          break;
        case kHalf:
          if (x < aW / 2) {
            img.Set(x, y, 255, 255, 255, 255);
          } else {
            img.Set(x, y, 0, 0, 0, 255);
          }
          break;
        case kChecker:
          if (((x / 2) + (y / 2)) % 2) {
            img.Set(x, y, 255, 0, 0, 255);
          } else if ((x / 2) % 2) {
            img.Set(x, y, 0, 0, 255, 255);
          } else {
            img.Set(x, y, 255, 255, 255, 255);
          }
          break;
        case kTriangleBlend:
        case kTrianglePremult: {
          const int d = x * aH - y * aW;
          const int cov = Clamp255(128 + d * 24 / std::max(aW, aH));
          if (aKind == kTriangleBlend) {
            img.Set(x, y, 255 + (20 - 255) * cov / 255, 255 + (90 - 255) * cov / 255,
                    255 + (200 - 255) * cov / 255, 255);
          } else {
            img.Set(x, y, 20 * cov / 255, 90 * cov / 255, 200 * cov / 255, cov);
          }
          break;
        }
        case kGradientH:
          img.Set(x, y, aW > 1 ? x * 255 / (aW - 1) : 0, aW > 1 ? x * 255 / (aW - 1) : 0,
                  aW > 1 ? x * 255 / (aW - 1) : 0, 255);
          break;
        case kGradient2D:
          img.Set(x, y, aW > 1 ? x * 255 / (aW - 1) : 0, aH > 1 ? y * 255 / (aH - 1) : 0,
                  0, 255);
          break;
        case kGradientSteep:
          img.Set(x, y, (x * 37) & 255, (y * 91) & 255, ((x + y) * 5) & 255, 255);
          break;
        case kGradientAlpha:
          img.Set(x, y, x * 3 & 255, y * 5 & 255, (x + y) & 255,
                  Clamp255(40 + x * 6 + y * 2));
          break;
        case kNoiseRgba:
          img.Set(x, y, n0, n1, n2, n3);
          break;
        case kNoiseRgb:
          img.Set(x, y, n0, n1, n2, 255);
          break;
        case kNoiseAlpha01:
          img.Set(x, y, n0, n1, n2, (n3 & 1) ? 255 : 0);
          break;
        case kNoisePalette3: {
          const int* c = palette[n0 % 3];
          img.Set(x, y, c[0], c[1], c[2], c[3]);
          break;
        }
        case kNoiseNear3:
        case kNoiseNear12:
        case kNoiseNear40: {
          const int spread = aKind == kNoiseNear3 ? 4 : (aKind == kNoiseNear12 ? 13 : 41);
          img.Set(x, y, Clamp255(120 + n0 % spread), Clamp255(130 + n1 % spread),
                  Clamp255(140 + n2 % spread), Clamp255(250 - n3 % std::min(spread, 6)));
          break;
        }
        case kNoiseLine:
        case kNoiseLineJitter: {
          // A coverage in eighths between two colours, as antialiased text is,
          // and, for the jitter, up to 2 off it per channel: close to the
          // segment, which is what the tolerance decides.
          const int level = n0 % 9;
          const int jitter = aKind == kNoiseLineJitter ? 3 : 1;
          img.Set(x, y,
                  Clamp255(baseColour[0] + (farColour[0] - baseColour[0]) * level / 8 + (n1 % jitter) - (jitter - 1) / 2),
                  Clamp255(baseColour[1] + (farColour[1] - baseColour[1]) * level / 8 + (n2 % jitter) - (jitter - 1) / 2),
                  Clamp255(baseColour[2] + (farColour[2] - baseColour[2]) * level / 8 + (n3 % jitter) - (jitter - 1) / 2),
                  255);
          break;
        }
        default:
          break;
      }
    }
  }
  return img;
}

struct Size {
  int32_t w, h;
};

// Bytes of padding after each row of the source and of the destination.
struct Pad {
  int32_t src, dst;
};
const Size kSizes[] = {{1, 1},  {1, 7},  {9, 1},  {2, 2},   {3, 3},  {5, 7},
                       {16, 16}, {37, 23}, {64, 63}, {129, 17}, {258, 5}};

// What the four layouts and both alpha types give, paired so that every layout
// and both alpha types are met, and the premultiplied constraint (a channel
// never above its alpha) is tried on noise that breaks it as well as on noise
// that keeps it.
struct Mode {
  SurfaceFormat format;
  bool premultiplied;
};
const Mode kModes[] = {{SurfaceFormat::R8G8B8A8, true},
                       {SurfaceFormat::B8G8R8A8, false},
                       {SurfaceFormat::R8G8B8X8, true},
                       {SurfaceFormat::B8G8R8X8, false},
                       {SurfaceFormat::R8G8B8A8, false},
                       {SurfaceFormat::B8G8R8A8, true}};

// ---------------------------------------------------------------------------
// The comparison.

std::string Describe(const Image& aImg, const Mode& aMode, int32_t aSeed, int32_t aTol,
                     const IntRect& aRect) {
  return aImg.name + " format " + std::to_string(int(aMode.format)) + " premult " +
         std::to_string(aMode.premultiplied) + " seed " + std::to_string(aSeed) +
         " tol " + std::to_string(aTol) + " rect " + std::to_string(aRect.X()) + "," +
         std::to_string(aRect.Y()) + " " + std::to_string(aRect.Width()) + "x" +
         std::to_string(aRect.Height());
}

// A buffer of aRect's size, stride aStride, holding what the image holds
// inside aRect, and aFill elsewhere (outside the image, in the padding).
std::vector<uint8_t> DstFor(const Image& aImg, const IntRect& aRect, int32_t aStride,
                            uint8_t aFill) {
  std::vector<uint8_t> dst(size_t(aStride) * aRect.Height(), aFill);
  for (int32_t y = 0; y < aRect.Height(); ++y) {
    for (int32_t x = 0; x < aRect.Width(); ++x) {
      const int32_t sx = aRect.X() + x;
      const int32_t sy = aRect.Y() + y;
      if (sx >= 0 && sx < aImg.w && sy >= 0 && sy < aImg.h) {
        memcpy(&dst[size_t(y) * aStride + 4 * size_t(x)],
               &aImg.px[(size_t(sy) * aImg.w + sx) * 4], 4);
      }
    }
  }
  return dst;
}

// The reference and the function under test on the same input: the same answer,
// the same bytes in the whole destination (and the source left alone). Counts
// in *aChanged the pixels the function changed. False, with the first
// difference reported, if they differ.
bool SameOutput(const Image& aImg, const Mode& aMode, int32_t aSeed, int32_t aTol,
                const IntRect& aRect, int32_t aSrcPad, int32_t aDstPad,
                size_t* aChanged) {
  const int32_t srcStride = aImg.w * 4 + aSrcPad;
  std::vector<uint8_t> src(size_t(srcStride) * aImg.h, 0x5a);
  for (int32_t y = 0; y < aImg.h; ++y) {
    memcpy(&src[size_t(y) * srcStride], &aImg.px[size_t(y) * aImg.w * 4], size_t(aImg.w) * 4);
  }
  const std::vector<uint8_t> srcBefore = src;
  const int32_t dstStride = std::max(aRect.Width(), 0) * 4 + aDstPad;
  const std::vector<uint8_t> init = DstFor(aImg, aRect, dstStride, 0xcd);
  std::vector<uint8_t> dstRef = init;
  std::vector<uint8_t> dstNew = init;
  const StealthCanvasNoise noise{aSeed, aTol};
  const IntSize size(aImg.w, aImg.h);
  const bool refOk = RefProjectPixels(src.data(), srcStride, size, aMode.format, aRect,
                                      dstRef.data(), dstStride, aMode.premultiplied, noise);
  const bool newOk = StealthProjectPixels(src.data(), srcStride, size, aMode.format, aRect,
                                          dstNew.data(), dstStride, aMode.premultiplied, noise);
  if (refOk != newOk) {
    ADD_FAILURE() << "answers differ (" << refOk << " reference, " << newOk
                  << " new): " << Describe(aImg, aMode, aSeed, aTol, aRect);
    return false;
  }
  if (src != srcBefore) {
    ADD_FAILURE() << "the source was written: " << Describe(aImg, aMode, aSeed, aTol, aRect);
    return false;
  }
  if (dstRef != dstNew) {
    size_t i = 0;
    while (dstRef[i] == dstNew[i]) {
      ++i;
    }
    ADD_FAILURE() << "bytes differ at " << i << " (row " << i / dstStride << ", byte "
                  << i % dstStride << "; reference " << int(dstRef[i]) << ", new "
                  << int(dstNew[i]) << "): " << Describe(aImg, aMode, aSeed, aTol, aRect);
    return false;
  }
  if (aChanged) {
    for (size_t i = 0; i + 3 < init.size(); i += 4) {
      *aChanged += memcmp(&init[i], &dstNew[i], 4) != 0;
    }
  }
  return true;
}

// The same in place (source and destination one buffer).
bool SameInPlace(const Image& aImg, const Mode& aMode, int32_t aSeed, int32_t aTol,
                 const IntRect& aRect) {
  std::vector<uint8_t> a = aImg.px;
  std::vector<uint8_t> b = aImg.px;
  const StealthCanvasNoise noise{aSeed, aTol};
  const IntSize size(aImg.w, aImg.h);
  const bool refOk = RefProjectPixels(a.data(), aImg.w * 4, size, aMode.format, aRect,
                                      a.data() + 4 * (size_t(aRect.Y()) * aImg.w + aRect.X()),
                                      aImg.w * 4, aMode.premultiplied, noise);
  const bool newOk = StealthProjectPixels(b.data(), aImg.w * 4, size, aMode.format, aRect,
                                          b.data() + 4 * (size_t(aRect.Y()) * aImg.w + aRect.X()),
                                          aImg.w * 4, aMode.premultiplied, noise);
  if (refOk != newOk || a != b) {
    ADD_FAILURE() << "in place: " << (refOk != newOk ? "answers" : "bytes")
                  << " differ: " << Describe(aImg, aMode, aSeed, aTol, aRect);
    return false;
  }
  return true;
}

constexpr int32_t kTolerances[] = {0, 3, 4, 40, 255};
constexpr int32_t kSeeds[] = {8, -77};

}  // namespace eq

TEST(StealthCanvasProjection, EquivMatchesTheReferenceOnManyImages)
{
  size_t failures = 0;
  size_t cases = 0;
  size_t changed = 0;
  for (int k = 0; k < eq::kKinds; ++k) {
    for (const eq::Size& s : eq::kSizes) {
      const eq::Image img = eq::Make(eq::Kind(k), s.w, s.h, 1 + k + s.w);
      for (const eq::Mode& mode : eq::kModes) {
        for (int32_t tol : eq::kTolerances) {
          for (int32_t seed : eq::kSeeds) {
            ++cases;
            failures += !eq::SameOutput(img, mode, seed, tol, IntRect(0, 0, s.w, s.h),
                                        0, 0, &changed);
            if (failures >= 5) {
              FAIL() << "too many differences";
            }
          }
        }
      }
    }
  }
  EXPECT_EQ(0u, failures);
  EXPECT_GT(cases, 10000u);
  // The images must make the function work: if nothing were ever changed, equal
  // output would prove nothing.
  EXPECT_GT(changed, 20000u) << "the images never reach a decision that touches a pixel";
}

TEST(StealthCanvasProjection, EquivMatchesTheReferenceOnRectangles)
{
  // Rectangles that cut through the surface, touch each edge, are one pixel,
  // or leave it; strides with padding on both sides.
  size_t failures = 0;
  for (int k : {eq::kHalf, eq::kTriangleBlend, eq::kGradient2D, eq::kGradientSteep,
                eq::kNoiseRgba, eq::kNoiseNear12, eq::kNoiseLineJitter,
                eq::kNoisePalette3, eq::kGradientAlpha}) {
    for (const eq::Size s : {eq::Size{37, 23}, eq::Size{1, 9}, eq::Size{9, 1},
                             eq::Size{5, 5}, eq::Size{64, 17}}) {
      const eq::Image img = eq::Make(eq::Kind(k), s.w, s.h, 40 + k);
      const int32_t w = s.w;
      const int32_t h = s.h;
      const IntRect rects[] = {
          IntRect(0, 0, w, h),
          IntRect(1, 1, std::max(w - 2, 1), std::max(h - 2, 1)),
          IntRect(0, 0, 1, 1),
          IntRect(w - 1, h - 1, 1, 1),
          IntRect(0, 0, w, 1),
          IntRect(0, h - 1, w, 1),
          IntRect(0, 0, 1, h),
          IntRect(w - 1, 0, 1, h),
          IntRect(w / 2, h / 2, std::max(w / 2, 1), std::max(h / 2, 1)),
          IntRect(-3, -2, w + 5, h + 4),
          IntRect(w / 2, h / 2, w, h),
          IntRect(-1, 0, 3, h),
          IntRect(0, -1, w, 3),
          IntRect(w, h, 3, 3),     // beyond the surface: nothing
          IntRect(0, 0, 0, 5),     // empty
      };
      for (const IntRect& rect : rects) {
        for (const eq::Mode& mode : {eq::kModes[0], eq::kModes[3], eq::kModes[5]}) {
          for (int32_t tol : {0, 4, 100}) {
            for (const eq::Pad pad : {eq::Pad{0, 0}, eq::Pad{8, 12}}) {
              failures += !eq::SameOutput(img, mode, 8, tol, rect, pad.src, pad.dst,
                                          nullptr);
              if (failures >= 5) {
                FAIL() << "too many differences";
              }
            }
            if (rect.X() >= 0 && rect.Y() >= 0 && rect.XMost() <= w && rect.YMost() <= h &&
                !rect.IsEmpty()) {
              failures += !eq::SameInPlace(img, mode, 8, tol, rect);
            }
          }
        }
      }
    }
  }
  EXPECT_EQ(0u, failures);
}

TEST(StealthCanvasProjection, EquivMatchesTheReferenceOnEveryTolerance)
{
  // All 256 tolerances, on the images whose neighbourhoods sit near a segment
  // at some distance: the ones the tolerance decides.
  size_t failures = 0;
  size_t changedLow = 0;
  size_t changedHigh = 0;
  for (int k : {eq::kNoiseNear3, eq::kNoiseNear12, eq::kNoiseNear40, eq::kNoiseLine,
                eq::kNoiseLineJitter, eq::kTriangleBlend, eq::kGradientSteep,
                eq::kNoiseRgb}) {
    const eq::Image img = eq::Make(eq::Kind(k), 29, 21, 100 + k);
    for (int32_t tol = 0; tol <= 255; ++tol) {
      size_t changed = 0;
      failures += !eq::SameOutput(img, eq::kModes[0], 8, tol, IntRect(0, 0, 29, 21), 0, 0,
                                  &changed);
      if (k == eq::kNoiseNear12 && tol == 0) {
        changedLow = changed;
      }
      if (k == eq::kNoiseNear12 && tol == 255) {
        changedHigh = changed;
      }
      if (failures >= 5) {
        FAIL() << "too many differences";
      }
    }
  }
  EXPECT_EQ(0u, failures);
  // The tolerance does decide something here: 0 touches pixels, 255 none.
  EXPECT_GT(changedLow, 0u);
  EXPECT_EQ(0u, changedHigh);
}

TEST(StealthCanvasProjection, EquivMatchesTheReferenceOnRefusals)
{
  const eq::Image img = eq::Make(eq::kNoiseRgb, 9, 9, 3);
  std::vector<uint8_t> a = img.px;
  const std::vector<uint8_t> before = a;
  // No seed, a format that is not supported, an empty or distant rectangle, no
  // buffer: false, nothing written, as before.
  EXPECT_FALSE(StealthProjectPixels(a.data(), 36, IntSize(9, 9), SurfaceFormat::R8G8B8A8,
                                    IntRect(0, 0, 9, 9), a.data(), 36, true,
                                    StealthCanvasNoise{0, 4}));
  EXPECT_FALSE(StealthProjectPixels(a.data(), 36, IntSize(9, 9), SurfaceFormat::A8,
                                    IntRect(0, 0, 9, 9), a.data(), 36, true,
                                    StealthCanvasNoise{8, 4}));
  EXPECT_FALSE(StealthProjectPixels(a.data(), 36, IntSize(9, 9), SurfaceFormat::R8G8B8A8,
                                    IntRect(20, 20, 4, 4), a.data(), 36, true,
                                    StealthCanvasNoise{8, 4}));
  EXPECT_FALSE(StealthProjectPixels(nullptr, 36, IntSize(9, 9), SurfaceFormat::R8G8B8A8,
                                    IntRect(0, 0, 9, 9), a.data(), 36, true,
                                    StealthCanvasNoise{8, 4}));
  EXPECT_FALSE(StealthProjectPixels(a.data(), 36, IntSize(9, 9), SurfaceFormat::R8G8B8A8,
                                    IntRect(0, 0, 9, 9), nullptr, 36, true,
                                    StealthCanvasNoise{8, 4}));
  EXPECT_EQ(before, a);
}

TEST(StealthCanvasProjection, EquivIsAProjectionWhateverTheImage)
{
  // Idempotence of the new function on every kind of image, tolerance and
  // alpha type: the second application changes nothing.
  size_t failures = 0;
  for (int k = 0; k < eq::kKinds; ++k) {
    for (const eq::Size s : {eq::Size{37, 23}, eq::Size{1, 9}, eq::Size{16, 16}}) {
      const eq::Image img = eq::Make(eq::Kind(k), s.w, s.h, 200 + k);
      for (const eq::Mode& mode : eq::kModes) {
        for (int32_t tol : eq::kTolerances) {
          std::vector<uint8_t> once = img.px;
          const StealthCanvasNoise noise{8, tol};
          StealthProjectPixels(once.data(), s.w * 4, IntSize(s.w, s.h), mode.format,
                               IntRect(0, 0, s.w, s.h), once.data(), s.w * 4,
                               mode.premultiplied, noise);
          std::vector<uint8_t> twice = once;
          StealthProjectPixels(twice.data(), s.w * 4, IntSize(s.w, s.h), mode.format,
                               IntRect(0, 0, s.w, s.h), twice.data(), s.w * 4,
                               mode.premultiplied, noise);
          if (once != twice) {
            ++failures;
            ADD_FAILURE() << "not a projection: "
                          << eq::Describe(img, mode, 8, tol, IntRect(0, 0, s.w, s.h));
          }
        }
      }
    }
  }
  EXPECT_EQ(0u, failures);
}

namespace eq {

// A framebuffer F and a readPixels request (rx, ry, rw, rh) on it, as the host
// answers one: the part of the request inside F is written, row by row, with
// the request's stride. Returns the destination the page would get, and the
// part written (in request coordinates).
struct Request {
  int32_t rx, ry, rw, rh;
};

struct PageRead {
  std::vector<uint8_t> dest;
  size_t stride = 0;
  IntRect sub;
};

PageRead ReadPage(const Image& aF, const Request& aReq, size_t aStridePad) {
  PageRead out;
  out.stride = size_t(aReq.rw) * 4 + aStridePad;
  out.dest.assign(out.stride * aReq.rh, 0xcd);
  const int32_t readX = std::max(aReq.rx, 0);
  const int32_t readY = std::max(aReq.ry, 0);
  const int32_t x1 = std::min(aReq.rx + aReq.rw, aF.w);
  const int32_t y1 = std::min(aReq.ry + aReq.rh, aF.h);
  if (x1 <= readX || y1 <= readY) {
    return out;  // disjoint: nothing written, an empty subrect
  }
  out.sub = IntRect(readX - aReq.rx, readY - aReq.ry, x1 - readX, y1 - readY);
  for (int32_t y = 0; y < out.sub.Height(); ++y) {
    memcpy(&out.dest[(size_t(out.sub.Y()) + y) * out.stride + size_t(out.sub.X()) * 4],
           &aF.px[(size_t(readY + y) * aF.w + readX) * 4], size_t(out.sub.Width()) * 4);
  }
  return out;
}

// The pixels of F that a read of (x, y, w, h) in F's own coordinates returns,
// tightly packed, if F holds ALL of them; false otherwise.
bool ReadFramebuffer(const Image& aF, int32_t aX, int32_t aY, int32_t aW, int32_t aH,
                     uint8_t* aOut) {
  if (aX < 0 || aY < 0 || aX + aW > aF.w || aY + aH > aF.h) {
    return false;
  }
  for (int32_t y = 0; y < aH; ++y) {
    memcpy(aOut + size_t(y) * aW * 4, &aF.px[(size_t(aY + y) * aF.w + aX) * 4],
           size_t(aW) * 4);
  }
  return true;
}

// What the code did before the block read: a read of the request grown by one
// pixel on every side (the part of it inside F), projected as a surface, the
// pixels of the request put back. Copied from StealthWebGLReadback.h as it
// was, the framebuffer replaced by F.
void OldProjectReadPixels(const Image& aF, const Request& aReq, PageRead* aPage,
                          const Mode& aMode, const StealthCanvasNoise& aNoise) {
  if (aPage->sub.IsEmpty()) {
    return;
  }
  const Request wide = {aReq.rx - 1, aReq.ry - 1, aReq.rw + 2, aReq.rh + 2};
  const size_t wideStride = size_t(wide.rw) * 4;
  const PageRead wideRead = ReadPage(aF, wide, 0);
  // (ReadPage fills the rest with 0xcd where the old code had zeros: never read.)
  std::vector<uint8_t> wideBytes = wideRead.dest;
  const IntRect fb = wideRead.sub;
  if (fb.IsEmpty()) {
    return;
  }
  uint8_t* const fbBase = wideBytes.data() + size_t(fb.Y()) * wideStride + size_t(fb.X()) * 4;
  const IntRect asked = (aPage->sub + IntPoint(1, 1) - fb.TopLeft())
                            .Intersect(IntRect(IntPoint(), fb.Size()));
  if (asked.IsEmpty()) {
    return;
  }
  uint8_t* const askedBase = fbBase + size_t(asked.Y()) * wideStride + size_t(asked.X()) * 4;
  if (!RefProjectPixels(fbBase, int32_t(wideStride), fb.Size(), SurfaceFormat::R8G8B8A8, asked,
                        askedBase, int32_t(wideStride), aMode.premultiplied, aNoise)) {
    return;
  }
  const size_t bytes = size_t(asked.Width()) * 4;
  for (int32_t row = 0; row < asked.Height(); ++row) {
    const int32_t rx = asked.X() + fb.X() - 1;
    const int32_t ry = asked.Y() + fb.Y() - 1 + row;
    const size_t destOffset = size_t(ry) * aPage->stride + size_t(rx) * 4;
    if (destOffset + bytes > aPage->dest.size()) {
      return;
    }
    memcpy(aPage->dest.data() + destOffset, askedBase + size_t(row) * wideStride, bytes);
  }
}

// What the code does now: the block, where the page's bytes lie, and the small
// reads of the pixels around it. *aReads counts the reads asked of F, and
// *aHits those it could answer.
void NewProjectReadPixels(const Image& aF, const Request& aReq, PageRead* aPage,
                          const Mode& aMode, const StealthCanvasNoise& aNoise, int* aReads,
                          int* aHits) {
  if (aPage->sub.IsEmpty()) {
    return;
  }
  const IntRect sub = aPage->sub;
  const StealthBlockEdges mayHave = {!sub.Y(), sub.YMost() == aReq.rh, !sub.X(),
                                     sub.XMost() == aReq.rw};
  auto read = [&](int32_t aX, int32_t aY, int32_t aW, int32_t aH, uint8_t* aOut) {
    ++*aReads;
    const bool ok = ReadFramebuffer(aF, aX, aY, aW, aH, aOut);
    *aHits += ok;
    return ok;
  };
  StealthProjectBlockInCanvas(
      aPage->dest.data() + size_t(sub.Y()) * aPage->stride + size_t(sub.X()) * 4,
      int32_t(aPage->stride), IntSize(sub.Width(), sub.Height()), SurfaceFormat::R8G8B8A8,
      aMode.premultiplied, IntPoint(aReq.rx + sub.X(), aReq.ry + sub.Y()), mayHave, read,
      aNoise);
  // A side taken as having no pixels must really have none in F, or the
  // projection would differ from the old one where F has them.
  const auto inside = [&](int32_t aX, int32_t aY, int32_t aW, int32_t aH) {
    return aX >= 0 && aY >= 0 && aX + aW <= aF.w && aY + aH <= aF.h;
  };
  const int32_t x0 = aReq.rx + sub.X();
  const int32_t y0 = aReq.ry + sub.Y();
  if (!mayHave.top) {
    EXPECT_FALSE(inside(x0, y0 - 1, sub.Width(), 1));
  }
  if (!mayHave.bottom) {
    EXPECT_FALSE(inside(x0, y0 + sub.Height(), sub.Width(), 1));
  }
  if (!mayHave.left) {
    EXPECT_FALSE(inside(x0 - 1, y0, 1, sub.Height()));
  }
  if (!mayHave.right) {
    EXPECT_FALSE(inside(x0 + sub.Width(), y0, 1, sub.Height()));
  }
}

}  // namespace eq

TEST(StealthCanvasProjection, EquivBlockReadMatchesTheWideRead)
{
  size_t failures = 0;
  size_t changed = 0;
  for (int k : {eq::kHalf, eq::kTriangleBlend, eq::kGradient2D, eq::kGradientSteep,
                eq::kNoiseRgba, eq::kNoiseNear12, eq::kNoiseLineJitter,
                eq::kNoisePalette3, eq::kChecker, eq::kFlat}) {
    for (const eq::Size s : {eq::Size{23, 17}, eq::Size{1, 9}, eq::Size{9, 1},
                             eq::Size{40, 30}, eq::Size{3, 3}}) {
      const eq::Image fb = eq::Make(eq::Kind(k), s.w, s.h, 300 + k);
      const eq::Request requests[] = {
          {0, 0, s.w, s.h},              // the whole framebuffer: no pixel beside it
          {1, 1, std::max(s.w - 2, 1), std::max(s.h - 2, 1)},  // inside: all four sides
          {2, 3, 5, 4},
          {0, 0, s.w, 1},
          {0, s.h - 1, s.w, 1},
          {0, 0, 1, s.h},
          {s.w - 1, 0, 1, s.h},
          {-3, -2, s.w + 6, s.h + 4},    // leaves it on every side
          {-1, 0, 3, 3},
          {s.w - 2, s.h - 2, 6, 6},
          {-5, 1, 7, 4},                 // leaves it on the left only
          {1, -4, 4, 7},                 // on the top only
          {s.w + 2, 0, 4, 4},            // disjoint
          {0, 0, s.w + 3, s.h},          // beyond the right side
          {0, 0, s.w, s.h + 3},          // beyond the bottom
      };
      for (const eq::Request& req : requests) {
        if (req.rw <= 0 || req.rh <= 0) {
          continue;
        }
        for (const size_t pad : {size_t(0), size_t(8)}) {
          for (const eq::Mode& mode : {eq::kModes[0], eq::kModes[4]}) {
            for (int32_t tol : {0, 4, 100}) {
              const StealthCanvasNoise noise{8, tol};
              const eq::PageRead page = eq::ReadPage(fb, req, pad);
              eq::PageRead oldRead = page;
              eq::PageRead newRead = page;
              eq::OldProjectReadPixels(fb, req, &oldRead, mode, noise);
              int reads = 0;
              int hits = 0;
              eq::NewProjectReadPixels(fb, req, &newRead, mode, noise, &reads, &hits);
              if (oldRead.dest != newRead.dest) {
                ++failures;
                size_t i = 0;
                while (oldRead.dest[i] == newRead.dest[i]) {
                  ++i;
                }
                ADD_FAILURE() << "block read differs at byte " << i << " (row "
                              << i / page.stride << ", byte " << i % page.stride << "): "
                              << fb.name << " request " << req.rx << "," << req.ry << " "
                              << req.rw << "x" << req.rh << " pad " << pad << " tol " << tol
                              << " premult " << mode.premultiplied;
              }
              // Never more than the four sides and the four corners.
              EXPECT_LE(reads, 8);
              for (size_t i = 0; i + 3 < page.dest.size(); i += 4) {
                changed += memcmp(&page.dest[i], &newRead.dest[i], 4) != 0;
              }
              if (failures >= 5) {
                FAIL() << "too many differences";
              }
              // A request that is the whole framebuffer has no pixel beside it.
              if (req.rx == 0 && req.ry == 0 && req.rw == s.w && req.rh == s.h) {
                EXPECT_EQ(0, hits);
              }
            }
          }
        }
      }
    }
  }
  EXPECT_EQ(0u, failures);
  EXPECT_GT(changed, 1000u) << "no pixel of any read was touched: the test proves nothing";
}

TEST(StealthCanvasProjection, EquivBlockReadIsAProjection)
{
  // Projecting the projected block, with the same pixels around it, changes
  // nothing (and the pixels around it are the unprojected ones of the
  // framebuffer in both: the noise only ever rewrites low bits it does not
  // read).
  const eq::Image fb = eq::Make(eq::kNoiseNear12, 40, 30, 9);
  const eq::Request req = {3, 4, 20, 15};
  const StealthCanvasNoise noise{8, 4};
  eq::PageRead once = eq::ReadPage(fb, req, 0);
  int reads = 0;
  int hits = 0;
  eq::NewProjectReadPixels(fb, req, &once, eq::kModes[0], noise, &reads, &hits);
  eq::PageRead twice = once;
  eq::NewProjectReadPixels(fb, req, &twice, eq::kModes[0], noise, &reads, &hits);
  EXPECT_EQ(once.dest, twice.dest);
}

namespace eq {

double MinSeconds(int aRuns, const std::function<void()>& aFn) {
  double best = 1e30;
  for (int i = 0; i < aRuns; ++i) {
    const auto t0 = std::chrono::steady_clock::now();
    aFn();
    const std::chrono::duration<double> d = std::chrono::steady_clock::now() - t0;
    best = std::min(best, d.count());
  }
  return best;
}

}  // namespace eq

TEST(StealthCanvasProjection, EquivIsFasterThanTheReferenceOnAGradient)
{
  // The shortest of three runs of each, in this process, on the same pixels:
  // what a machine's load does to one it does to the other. A smooth gradient
  // (every neighbourhood a blend within the tolerance, the common case of a
  // WebGL scene) used to cost the full search over nine colours per pixel; the
  // bound is a factor of two, farColour under what the function gains.
  const int32_t w = 512;
  const int32_t h = 512;
  const eq::Image img = eq::Make(eq::kGradient2D, w, h, 1);
  const StealthCanvasNoise noise{8, 4};
  std::vector<uint8_t> ref = img.px;
  std::vector<uint8_t> now = img.px;
  const double refSeconds = eq::MinSeconds(3, [&] {
    ref = img.px;
    eq::RefProjectPixels(ref.data(), w * 4, IntSize(w, h), SurfaceFormat::R8G8B8A8,
                         IntRect(0, 0, w, h), ref.data(), w * 4, true, noise);
  });
  const double newSeconds = eq::MinSeconds(3, [&] {
    now = img.px;
    StealthProjectPixels(now.data(), w * 4, IntSize(w, h), SurfaceFormat::R8G8B8A8,
                         IntRect(0, 0, w, h), now.data(), w * 4, true, noise);
  });
  EXPECT_EQ(ref, now);
  EXPECT_LT(newSeconds * 2, refSeconds)
      << "new " << newSeconds * 1000 << " ms, reference " << refSeconds * 1000 << " ms";
}
