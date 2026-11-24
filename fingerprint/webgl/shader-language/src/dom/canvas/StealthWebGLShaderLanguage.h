/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// fingerprint/webgl/shader-language: which shader output language the page
// sees. Declarations only; the logic is in StealthWebGLShaderLanguage.cpp.

#ifndef DOM_CANVAS_STEALTHWEBGLSHADERLANGUAGE_H_
#define DOM_CANVAS_STEALTHWEBGLSHADERLANGUAGE_H_

#include <string>

#include "GLSLANG/ShaderLang.h"
#include "mozilla/Maybe.h"

namespace mozilla {

class WebGLShader;

namespace gl {
class GLContext;
}  // namespace gl

// The language the GL CONTEXT imposes, that is, the one used to compile for the
// driver; it is not our choice. It used to be `static ShaderOutput`: it became
// visible because it has a second reader, `WebGLShader::CompileShader`, which
// must know whether the declared language is the same as this one. Exposed
// instead of copied: two copies of this table would diverge the first time
// someone adds a case to only one of them.
// The definition stays in WebGLShaderValidator.cpp (it is Mozilla code).
ShShaderOutput ShaderOutputForDriver(gl::GLContext* gl);

namespace webgl {

// The language the PAGE must see, declared by the core with
// `zoom.stealth.webgl.shader_output_language`. `Nothing()` = no declaration,
// and then the driver's language applies. A finite domain with a single
// element: the LANGUAGE is declared, never the string.
Maybe<ShShaderOutput> StealthDeclaredShaderOutput();

}  // namespace webgl

// The language to compile with: the declared one only if `aForPage` is true and
// there is a declaration, otherwise the one of the GL context. It always reads
// the pref, even on the driver path, so that the warning for an unknown name
// fires at every construction of the validator. `aForPage` is the field
// `WebGLContext::mStealthPerPage`, true only while
// `WebGLShader::StealthPerPageObjectCode` builds the validator of the second
// translation.
ShShaderOutput StealthShaderOutputLanguage(gl::GLContext* gl,
                                           bool aForPage);

// What the PAGE reads as the translated code of a shader
// (`WebGLContext::GetCompileResult`): the rendering in the declared language if
// `aShader` has one, otherwise the driver's (`aDriverObjectCode`).
// Pure: no side effects, no pref read.
const std::string& StealthPageObjectCode(const WebGLShader& aShader,
                                         const std::string& aDriverObjectCode);

}  // namespace mozilla

#endif  // DOM_CANVAS_STEALTHWEBGLSHADERLANGUAGE_H_
