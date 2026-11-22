# fingerprint/webgl/shader-language

Category: spoof
Prefs: zoom.stealth.webgl.shader_output_language (declared by the core; read only in `dom/canvas/StealthWebGLShaderLanguage.cpp`)
Test: `wrapper:tests/test_webgl_shader_language_e2e.py::test_the_declared_shader_language_is_what_the_page_reads_and_the_driver_keeps_its_own` (to write); `tests/test_webgl_draws_on_the_engine_s_own_gl_e2e.py::test_every_declared_extension_answers_as_on_windows` (existing, reads `WEBGL_debug_shaders`)

## What it does

With `zoom.stealth.webgl.shader_output_language` declared (`essl`), `getTranslatedShaderSource` shows the page the ANGLE translation in the declared language, the one a Windows build gives (there the context goes through ANGLE and is already ESSL), while the driver keeps receiving the translation in the language of its own context: the pixels do not change. The second translation is made only when the declared language differs from the context's (Linux), once per compiled shader; on Windows nothing is translated twice. A failed second translation keeps the driver's string.

The page's string is kept in `WebGLShader::mObjectCodePerLaPagina` (empty when there is nothing to declare). Which language a validator is built for is chosen in `WebGLContext::CreateShaderValidator` by `StealthShaderOutputLanguage(gl, mStealthPerPage)`: `mStealthPerPage` is false everywhere, except while `WebGLShader::StealthPerPageObjectCode` builds the validator of the second translation (an RAII object of ours sets it and puts it back on every exit; one context lives on one thread). With it false the function returns `ShaderOutputPerIlDriver(gl)`, the body of Mozilla's former `ShaderOutput`. The pref is read at every construction of a validator, so an unknown name warns every time. The declaration is the LANGUAGE (a finite domain with one element), never the string.

All the logic is in `dom/canvas/StealthWebGLShaderLanguage.cpp/.h`: `StealthDeclaredShaderOutput`, `StealthShaderOutputLanguage`, `StealthPageObjectCode` (the choice `GetCompileResult` makes between the page's string and the driver's), `WebGLShader::ObjectCodePerLaPagina` and `WebGLShader::StealthPerPageObjectCode`. The string exposed is not the one compiled; no page can notice, the driver is not observable from a page.

## Hooks in Mozilla files

- `dom/canvas/WebGLContext.cpp`, `GetCompileResult`: wrap-expression, `ToCString(StealthPageObjectCode(shader, info->mObjectCode))` (one Mozilla line rewritten; Mozilla's expression is the second argument, evaluated once; the accessor is pure).
- `dom/canvas/WebGLContext.h`: member `bool mStealthPerPage = false;` after `mWebGLError` (G22: state in a field of the structure, not a thread-local); the signature of `CreateShaderValidator` is Mozilla's again (the defaulted parameter is gone).
- `dom/canvas/WebGLShader.cpp`, `CompileShader`: anchor, `mObjectCodePerLaPagina = StealthPerPageObjectCode(success);` right after the `kDumpShaders` block, before `if (!success) return;`. It needs `success`, the result Mozilla has just computed, and must run at the same moment as today (a function wrap would run the second translation after `fCompileShader`, G28); it writes a field Mozilla's later code never reads.
- `dom/canvas/WebGLShader.h`: three members, each after an existing member and none last in its block: the public accessor `ObjectCodePerLaPagina()` after `CompileLog()`, the private method `StealthPerPageObjectCode(bool)` after `BindAttribLocation`, the field `mObjectCodePerLaPagina` after `mCompilationSuccessful`.
- `dom/canvas/WebGLShaderValidator.cpp`: wrap-function (G1), `static ShShaderOutput ShaderOutput` becomes `ShaderOutputPerIlDriver` (body untouched; not static, so our file can call it; declared in our header, namespace `mozilla`; one Mozilla line rewritten); wrap-expression, the call `ShaderOutput(gl)` in `CreateShaderValidator` becomes `StealthShaderOutputLanguage(gl, mStealthPerPage)` (G9: our extra argument is a field, G14; one Mozilla line rewritten). Mozilla's signature of `CreateShaderValidator` is restored.
- `dom/canvas/WebGLShaderValidator.h`: registration, the include of `StealthWebGLShaderLanguage.h` in a block of ours after Mozilla's includes.

## Test

The e2e `test_the_declared_shader_language_is_what_the_page_reads_and_the_driver_keeps_its_own` launches the same seed with `essl` declared and without; the launch without the declaration is the negative control. The existing `test_every_declared_extension_answers_as_on_windows` reads `getTranslatedShaderSource` through `WEBGL_debug_shaders`.
