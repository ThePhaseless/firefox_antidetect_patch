/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// fingerprint/webgl/shader-language: the rendering of a shader meant for the
// PAGE (getTranslatedShaderSource), in the language declared by
// `zoom.stealth.webgl.shader_output_language`. Hook in
// WebGLShader::CompileShader (WebGLShader.cpp); reader in
// WebGLContext::GetCompileResult (WebGLContext.cpp, StealthPageObjectCode).
// Also the reader of the declaration itself (StealthDeclaredShaderOutput) and
// the choice of the language to compile with (StealthShaderOutputLanguage),
// called from WebGLContext::CreateShaderValidator (WebGLShaderValidator.cpp),
// which takes the one bit it needs from WebGLContext::mStealthPerPage.

#include <string>

#include "GLContext.h"
#include "StealthWebGLShaderLanguage.h"
#include "WebGLContext.h"
#include "WebGLShader.h"
#include "WebGLShaderValidator.h"
#include "mozilla/Assertions.h"
#include "mozilla/Maybe.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "nsDebug.h"
#include "nsString.h"

namespace mozilla {

namespace webgl {

// The ONLY place that reads the declared language, and the only one that knows
// how to translate the name into an ANGLE constant. If this knowledge lived in
// two places, the two could answer differently and nobody would notice: it is
// the same shape as the mouse-geometry defect, where the same arithmetic was
// copied in three places.
//
// `Nothing()` means "no declaration", and then the language stays the one the
// GL context imposes. A declared name we do not know is also `Nothing()` AND a
// warning: inventing a default would be the fallback that the rules forbid, and
// crashing here would switch WebGL off for a user because of a typo in a pref.
Maybe<ShShaderOutput> StealthDeclaredShaderOutput() {
  auto lock = StaticPrefs::zoom_stealth_webgl_shader_output_language();
  const nsCString declared(*lock);
  if (declared.IsEmpty()) {
    return Nothing();
  }
  if (declared.EqualsLiteral("essl")) {
    return Some(SH_ESSL_OUTPUT);
  }
  NS_WARNING(
      "zoom.stealth.webgl.shader_output_language declares a language that this "
      "build does not know; the translation stays the one of the GL context");
  return Nothing();
}

}  // namespace webgl

ShShaderOutput StealthShaderOutputLanguage(gl::GLContext* gl,
                                           bool aForPage) {
  // Always read, even for the driver: the warning for an unknown name fires at
  // every construction of the validator.
  const auto declared = webgl::StealthDeclaredShaderOutput();
  if (aForPage && declared) {
    return *declared;
  }
  return ShaderOutputForDriver(gl);
}

// What the PAGE reads (WebGLContext::GetCompileResult), when the language is
// declared and differs from the one of the GL context. The driver has already
// received `mObjectCode` in `WebGLShader::CompileShader` and it is not touched:
// the pixels do not change. Empty means "nothing to declare", which is the case
// of every Windows build, where the context goes through ANGLE and is already
// in the right language.
//
// The rendering meant for the PAGE, in the declared language. Empty when there
// is nothing to declare or when the declared language is already the one the
// context uses - that is, on Windows, where the context goes through ANGLE and
// is already GLES: there this field stays empty and nothing is paid.
//
// It is not a second source of truth for the same thing: they are two different
// consumers of the same validated tree, the driver and the page. What is
// declared is the LANGUAGE, which has a finite domain with a single element;
// the string stays computed by the translator, because its domain is infinite
// and a table would be forbidden.
const std::string& WebGLShader::ObjectCodeForPage() const {
  return mObjectCodeForPage;
}

// What `WebGLContext::GetCompileResult` puts in `translatedSource`: the
// rendering for the PAGE when the shader has one (non-empty), otherwise the
// translation the validator made for the driver. It is the choice the hook used
// to make inline; Mozilla's expression (`info->mObjectCode`) arrives as the
// second argument, evaluated once.
const std::string& StealthPageObjectCode(const WebGLShader& aShader,
                                         const std::string& aDriverObjectCode) {
  const auto& forPage = aShader.ObjectCodeForPage();
  return forPage.empty() ? aDriverObjectCode : forPage;
}

// Called by WebGLShader::CompileShader once the validation for the driver is
// final (mCompileResults), before Mozilla's `if (!success) return;`: sets
// `mObjectCodeForPage`, the value the page reads. It is cleared first, so a
// compilation with nothing to declare, or one that failed, leaves no string of
// a previous compilation.
//
// A member of WebGLShader and not a free function because
// `WebGLContext::CreateShaderValidator` is protected and WebGLContext declares
// only `WebGLShader` as a friend (WebGLContext.h `friend class WebGLShader`).
void WebGLShader::StealthSetObjectCodeForPage() {
  mObjectCodeForPage.clear();
  if (!mCompileResults->mValid) {
    return;
  }

  // The rendering for the PAGE, when the declared language is not the one the
  // GL context imposes.
  //
  // The translation made in CompileShader is compiled for the driver, so the
  // rendering does not change by a pixel, and a second rendering is produced in
  // the declared language for whoever reads `getTranslatedShaderSource`. Both
  // come out of the same ANGLE translator shipped with the same declared
  // resources, so the second is identical to that of a Windows build by
  // CONSTRUCTION, not by a measured coincidence.
  //
  // On Windows the context goes through ANGLE, which presents itself as GLES,
  // so the declared language is the same as the context's, the comparison below
  // is false and nothing is translated twice. Only the platform that has the
  // defect pays the cost, and only for shaders that are actually compiled.
  //
  // WARNING: the exposed string is not the compiled one. No page can notice -
  // the driver is not observable from there - but it must be written down,
  // because it is true.
  gl::GLContext* const gl = mContext->gl;
  const auto declared = webgl::StealthDeclaredShaderOutput();
  if (!declared || *declared == ShaderOutputForDriver(gl)) {
    return;
  }

  // The bit "this is the translation for the page" travels in a field of the
  // context (WebGLContext::mStealthPerPage), true only around this synchronous
  // call, on the context's thread: every other validator (the driver's, in
  // CompileShader) sees it false and is built as before. The guard sets it back
  // to false on every exit.
  struct PerPageScope {
    bool& mFlag;
    explicit PerPageScope(bool& aFlag) : mFlag(aFlag) { mFlag = true; }
    ~PerPageScope() { mFlag = false; }
  };
  std::unique_ptr<webgl::ShaderValidator> forPage;
  {
    bool& flag = mContext->mStealthPerPage;
    PerPageScope scope(flag);
    forPage = mContext->CreateShaderValidator(mType);
  }
  if (!forPage) {
    return;
  }

  const auto translation = forPage->ValidateAndTranslate(mSource.c_str());
  // If the second translation fails, the driver's is kept: an answer in the
  // wrong language is a realness defect, an empty answer is a broken page.
  if (translation && translation->mValid) {
    mObjectCodeForPage = translation->mObjectCode;
    return;
  }

  NS_WARNING(
      "the rendering in the declared language did not validate; "
      "getTranslatedShaderSource will return the driver's one");
}

}  // namespace mozilla
