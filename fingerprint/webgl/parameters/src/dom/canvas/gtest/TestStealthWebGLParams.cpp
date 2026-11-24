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

}  // namespace mozilla
