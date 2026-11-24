/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this file,
 * You can obtain one at http://mozilla.org/MPL/2.0/. */

// getShaderPrecisionFormat answers from the declaration
// (zoom.stealth.webgl.shader_precisions, StealthWebGLParams.cpp) with an object
// built there. WebGLShaderPrecisionFormatJS is RefCounted and is born with a
// count of 0: the object has to leave StealthWebGLShaderPrecisionFormat with
// its reference already taken (AsAddRefed, MakeAndAddRef), as it does from
// Mozilla's own path. Wrapped without one (already_AddRefed(new ...)), the
// first release of the binding freed it under the JS reflector, and a page read
// 229,229,229 (0xE5, freed memory) instead of the declared precision.

#include <utility>

#include "ClientWebGLContext.h"
#include "StealthWebGLParams.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "mozilla/RefPtr.h"
#include "mozilla/ScopeExit.h"

namespace mozilla {

namespace {

constexpr char kPrecisionsPref[] = "zoom.stealth.webgl.shader_precisions";

// FRAGMENT_SHADER * HIGH_FLOAT, and the triple declared for it.
constexpr GLenum kFragment = 0x8B30;
constexpr GLenum kHighFloat = 0x8DF2;
constexpr char kDeclared[] = "35632*36338|127:127:23";

}  // namespace

// The one reference the caller holds is the only reference there is, and the
// declared triple is still there once a second one has come and gone.
TEST(StealthWebGLParams, DeclaredShaderPrecisionObjectIsHeldByItsReferences)
{
  auto restore = MakeScopeExit([] { Preferences::ClearUser(kPrecisionsPref); });
  Preferences::SetCString(kPrecisionsPref, nsDependentCString(kDeclared));

  already_AddRefed<WebGLShaderPrecisionFormatJS> rv;
  ASSERT_TRUE(StealthWebGLShaderPrecisionFormat(kFragment, kHighFloat, &rv));
  RefPtr<WebGLShaderPrecisionFormatJS> first(std::move(rv));
  ASSERT_TRUE(first);
  // Born at 0 and never added to, this reads 0.
  ASSERT_EQ(first->refCount(), 1u);

  {
    RefPtr<WebGLShaderPrecisionFormatJS> second = first;
    EXPECT_EQ(first->refCount(), 2u);
  }

  EXPECT_EQ(first->refCount(), 1u);
  EXPECT_EQ(first->RangeMin(), 127);
  EXPECT_EQ(first->RangeMax(), 127);
  EXPECT_EQ(first->Precision(), 23);
}


namespace {

constexpr char kRendererPref[] = "zoom.stealth.webgl.renderer";
constexpr char kVendorPref[] = "zoom.stealth.webgl.vendor";
constexpr GLenum kRenderer = 0x1F01;
constexpr GLenum kUnmaskedVendor = 0x9245;
constexpr GLenum kUnmaskedRenderer = 0x9246;
constexpr GLenum kVersion = 0x1F02;

}  // namespace

// The entry guard of getParameter answers RENDERER, UNMASKED_RENDERER_WEBGL and UNMASKED_VENDOR_WEBGL from the declared values
// (StealthWebGLParameter asks StealthWebGLParameterString for the pname). The two controls: nothing declared, where Mozilla
// answers; and a declared value for a pname that is not one of the three, or for an UNMASKED_* one without the extension
// (Mozilla queues INVALID_ENUM there), where Mozilla answers as well.
TEST(StealthWebGLParams, TheDeclaredRendererAndVendorAnswerTheirPnames)
{
  auto restore = MakeScopeExit([] {
    Preferences::ClearUser(kRendererPref);
    Preferences::ClearUser(kVendorPref);
  });
  Preferences::SetCString(kRendererPref, "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)"_ns);
  Preferences::SetCString(kVendorPref, "Google Inc. (Intel)"_ns);

  Maybe<std::string> answer;
  EXPECT_TRUE(StealthWebGLParameterString(kRenderer, false, answer));
  EXPECT_TRUE(answer.isSome());

  answer.reset();
  EXPECT_TRUE(StealthWebGLParameterString(kUnmaskedRenderer, true, answer));
  EXPECT_TRUE(answer.isSome());

  answer.reset();
  ASSERT_TRUE(StealthWebGLParameterString(kUnmaskedVendor, true, answer));
  ASSERT_TRUE(answer.isSome());
  EXPECT_EQ(*answer, "Google Inc. (Intel)");

  // Declared, but not for Mozilla's answer to be replaced: nothing is taken from it.
  answer.reset();
  EXPECT_FALSE(StealthWebGLParameterString(kUnmaskedVendor, false, answer));
  EXPECT_FALSE(StealthWebGLParameterString(kUnmaskedRenderer, false, answer));
  EXPECT_FALSE(StealthWebGLParameterString(kVersion, true, answer));
  EXPECT_TRUE(answer.isNothing());
}

TEST(StealthWebGLParams, AnUndeclaredContextKeepsMozillasAnswer)
{
  Preferences::ClearUser(kRendererPref);
  Preferences::ClearUser(kVendorPref);

  Maybe<std::string> answer;
  EXPECT_FALSE(StealthWebGLParameterString(kRenderer, true, answer));
  EXPECT_FALSE(StealthWebGLParameterString(kUnmaskedRenderer, true, answer));
  EXPECT_FALSE(StealthWebGLParameterString(kUnmaskedVendor, true, answer));
  EXPECT_TRUE(answer.isNothing());
}

}  // namespace mozilla
