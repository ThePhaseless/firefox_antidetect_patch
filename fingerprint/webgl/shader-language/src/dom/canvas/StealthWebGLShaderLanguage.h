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

// La lingua che il CONTESTO GL impone, cioe' quella con cui si compila per il
// driver, e non e' una nostra scelta. Era `static ShaderOutput`: e' diventata
// visibile perche' ha un secondo lettore, `WebGLShader::CompileShader`, che
// deve sapere se la lingua dichiarata coincide con questa. Esposta invece che
// ricopiata: due copie di questa tabella divergerebbero al primo caso che
// qualcuno aggiunge a una sola.
// La definizione resta in WebGLShaderValidator.cpp (e' codice di Mozilla).
ShShaderOutput ShaderOutputPerIlDriver(gl::GLContext* gl);

namespace webgl {

// La lingua che la PAGINA deve vedere, dichiarata da invisible_core con
// `zoom.stealth.webgl.shader_output_language`. `Nothing()` = nessuna
// dichiarazione, e allora vale quella del driver. Dominio finito con un
// elemento solo: si dichiara la LINGUA, mai la stringa.
Maybe<ShShaderOutput> StealthDeclaredShaderOutput();

}  // namespace webgl

// La lingua con cui compilare: quella dichiarata solo se `aPerLaPagina` e se
// c'e' una dichiarazione, altrimenti quella del contesto GL. Legge sempre la
// pref, anche sul percorso del driver, cosi' l'avviso per un nome sconosciuto
// parte a ogni costruzione del validatore. `aPerLaPagina` e' il campo
// `WebGLContext::mStealthPerPage`, vero solo mentre
// `WebGLShader::StealthPerPageObjectCode` costruisce il validatore della
// seconda traduzione.
ShShaderOutput StealthShaderOutputLanguage(gl::GLContext* gl,
                                           bool aPerLaPagina);

// Quello che la PAGINA legge come codice tradotto di uno shader
// (`WebGLContext::GetCompileResult`): la resa nella lingua dichiarata se
// `aShader` ne ha una, altrimenti quella del driver (`aDriverObjectCode`).
// Pura: nessun effetto, nessuna lettura di pref.
const std::string& StealthPageObjectCode(const WebGLShader& aShader,
                                         const std::string& aDriverObjectCode);

}  // namespace mozilla

#endif  // DOM_CANVAS_STEALTHWEBGLSHADERLANGUAGE_H_
