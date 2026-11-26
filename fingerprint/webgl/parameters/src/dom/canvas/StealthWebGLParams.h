/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef DOM_CANVAS_STEALTHWEBGLPARAMS_H_
#define DOM_CANVAS_STEALTHWEBGLPARAMS_H_

// What a WebGL context says about the machine it runs on, replaced by the
// values the session declares: getParameter, the renderer and vendor strings,
// getShaderPrecisionFormat and the extension list. Called from hooks in
// ClientWebGLContext.cpp, WebGLContext*.cpp; every function reports "not
// overridden" (false or Nothing()) when its pref is empty, and the caller then
// runs Mozilla's code.
// The prefs are the contract with the core: zoom.stealth.webgl.* and
// zoom.stealth.webgl2.*.

#include <string>

#include "WebGLTypes.h"
#include "js/TypeDecls.h"
#include "mozilla/AlreadyAddRefed.h"
#include "mozilla/EnumeratedRange.h"
#include "mozilla/Maybe.h"
#include "nsTArray.h"
#include "nsString.h"

namespace mozilla {

class ClientWebGLContext;
class WebGLShaderPrecisionFormatJS;
class ErrorResult;
class WebGLContext;

// getParameter(pname) from one of three prefs, each a comma-separated list of
// "ENUM|VALUE" entries (ENUM in decimal):
//   zoom.stealth.webgl.int_params    VALUE an integer; the page reads a number;
//   zoom.stealth.webgl.float_params  VALUE "x" (a number) or "x:y" (a
//                                    Float32Array of two);
//   zoom.stealth.webgl.int2_params   VALUE "x:y" (an Int32Array of two).
// Checked in that order, so that the numerics of the host driver (Linux Mesa:
// MAX_TEXTURE_SIZE and the like) read as the Windows ANGLE values of the
// declared machine, and the hash of the whole parameter block is the one a
// Windows machine gives. True when it set aRetval. An entry that does not
// parse is skipped, as if absent.
bool StealthWebGLParameterOverride(ClientWebGLContext& aCtx, JSContext* aCx,
                                   GLenum aPname,
                                   JS::MutableHandle<JS::Value> aRetval,
                                   ErrorResult& aRv);

// Where the declared answer is applied: on the way OUT of
// ClientWebGLContext::GetParameter, constructed at its top. Firefox decides
// first whether the pname exists for this context (WebGL1 or 2) and its
// enabled extensions, and with what error; only when it answered with a value
// does a declared entry replace that value. It used to answer BEFORE Firefox,
// and measured 2026-10-31 against retail 159 a WebGL1 context returned 46 of
// the declared WebGL2-only pnames (MAX_ARRAY_TEXTURE_LAYERS 2048, MAX_SAMPLES
// 8, ...) where retail gives null and INVALID_ENUM. Firefox's own validity is
// kept; only the host's number is not.
class MOZ_RAII StealthWebGLParameterAnswer final {
 public:
  StealthWebGLParameterAnswer(ClientWebGLContext& aCtx, JSContext* aCx,
                              GLenum aPname,
                              JS::MutableHandle<JS::Value> aRetval,
                              ErrorResult& aRv)
      : mCtx(aCtx), mCx(aCx), mPname(aPname), mRetval(aRetval), mRv(aRv) {}
  ~StealthWebGLParameterAnswer();

 private:
  ClientWebGLContext& mCtx;
  JSContext* const mCx;
  const GLenum mPname;
  JS::MutableHandle<JS::Value> mRetval;
  ErrorResult& mRv;
};

// The first statement of ClientWebGLContext::GetParameter: RENDERER,
// UNMASKED_RENDERER_WEBGL and UNMASKED_VENDOR_WEBGL answered from the declared
// values, before Mozilla's code runs; true and aRetval set, or false and the
// call goes on as Mozilla wrote it. The answer is what Mozilla's own code gave
// once the pref was set: the string, in aRetval, and the entries of
// StealthWebGLParameterOverride applied after it (what the guard
// StealthWebGLParameterAnswer did on the way out). False, so Mozilla answers,
// when: aDebug is set (the debug-only parameters), the context is lost
// (Mozilla returns null), the pref for the pname is empty (the answer is then
// Mozilla's own, host or resist-fingerprinting), the pname is any other, or
// it is an UNMASKED_* one and WEBGL_debug_renderer_info is not enabled
// (Mozilla queues INVALID_ENUM). Reads no member of the context but through its
// public accessors.
bool StealthWebGLParameter(ClientWebGLContext& aCtx, JSContext* aCx,
                           GLenum aPname, JS::MutableHandle<JS::Value> aRetval,
                           ErrorResult& aRv, bool aDebug);

// What the guard above decides from the pname alone: true and aAnswer set when
// the pname is RENDERER, or UNMASKED_RENDERER_WEBGL / UNMASKED_VENDOR_WEBGL with
// WEBGL_debug_renderer_info enabled (aDebugRendererInfoEnabled), and the pref
// for it is set; false, and aAnswer left as it was, otherwise.
bool StealthWebGLParameterString(GLenum aPname, bool aDebugRendererInfoEnabled,
                                 Maybe<std::string>& aAnswer);

// gl.RENDERER when zoom.stealth.webgl.renderer is set: the pref, through
// SanitizeRenderer, as a retail browser does with the real renderer. True and
// aRet set when the pref is set.
//
// Measured on 2026-08-24 against a retail Firefox 151.0 signed by Mozilla
// Corporation, updater off, throwaway profile, on WebGL 1 and 2:
//
//     masked   ANGLE (Intel, ... ps_5_0), or similar
//     unmasked ANGLE (Intel, ... ps_5_0), or similar   <- identical
//
// The two are identical because webgl.sanitize-unmasked-renderer defaults to
// true, so both go through the same SanitizeRenderer. Making them differ is
// what would be the tell.
bool StealthWebGLRendererOverride(Maybe<std::string>& aRet);

// UNMASKED_RENDERER_WEBGL when zoom.stealth.webgl.renderer is set: sanitized
// like gl.RENDERER while webgl.sanitize-unmasked-renderer is true (the
// default), the pref as it is otherwise.
bool StealthWebGLUnmaskedRendererOverride(Maybe<std::string>& aRet);

// UNMASKED_VENDOR_WEBGL when zoom.stealth.webgl.vendor is set. The pref is
// read through StaticPrefs (a DataMutexString mirrored "always"): it reaches
// content processes and is thread-safe, so workers (OffscreenCanvas with
// WebGL) read the same declared value.
bool StealthWebGLUnmaskedVendorOverride(Maybe<std::string>& aRet);

// getShaderPrecisionFormat from zoom.stealth.webgl.shader_precisions, a
// comma-separated list of "SHADERTYPE*PRECISIONTYPE|rmin:rmax:p" entries in
// decimal; the three numbers are kept to 8 bits. A check can hash the twelve
// triples (two shader types times six precision types) into one signal; the
// host driver's triples are constant across sessions and give its platform
// away, so the declared machine's triples replace them. Nothing() when the
// pref has no usable entry for the pair.
Maybe<webgl::ShaderPrecisionFormat> StealthWebGLShaderPrecision(
    GLenum aShaderType, GLenum aPrecisionType);

// getShaderPrecisionFormat: a guard in ClientWebGLContext::
// GetShaderPrecisionFormat, right after Mozilla's lost-context check and BEFORE
// Mozilla reads the precisions the host reported: when the pref has a triple
// for the pair, aOut is the answer (an object built here) and the result is
// true, and the host's table is never looked at (and no INVALID_ENUM is raised
// for a pair the host lacks). The pref is read once.
bool StealthWebGLShaderPrecisionFormat(
    GLenum aShaderType, GLenum aPrecisionType,
    already_AddRefed<WebGLShaderPrecisionFormatJS>* aOut);

// The extension whitelist: zoom.stealth.webgl.extensions (WebGL 1) or
// zoom.stealth.webgl2.extensions (WebGL 2), comma-separated names, trimmed. An
// empty pref means no override. The pref is re-read and re-parsed on every
// call.
//
// With a whitelist set: Some(true) for a name in the list, Some(false) for any
// other, whatever the driver provides. Nothing() when there is no whitelist.
Maybe<bool> StealthWebGLExtensionVerdict(bool aIsWebGL2, WebGLExtensionID aExt);

// THE ONE DECISION on which extensions a page sees: the host's limits
// (MakeLimits) take the declared list when there is one, the GL's answer
// otherwise, and the content process reads only those limits - in Firefox's
// own order, as retail lists them. aServed is what the host's GL can do.
bool StealthDeclaredExtension(bool aIsWebGL2, WebGLExtensionID aExt,
                              bool aServed);

// Applied at the END of MakeLimits (the hook sits right before its
// `return limits;`), so every limit Mozilla derives from the extension bits
// inside it (draw buffers, ASTC HDR, multiview) is computed from what the GL
// serves; only the bits handed to the content process are the declared ones.
template <typename Bits>
void StealthDeclareExtensions(const bool aIsWebGL2, Bits& aBits) {
  for (const auto ext : MakeEnumeratedRange(WebGLExtensionID::Max)) {
    const bool served = static_cast<bool>(aBits[ext]);
    aBits[ext] = StealthDeclaredExtension(aIsWebGL2, ext, served);
  }
}

void StealthDeclareLimits(const WebGLContext& aWebGL, webgl::Limits* aLimits);

// IsExtensionSupported, in the case of WEBGL_provoking_vertex, after Mozilla's
// check that the GL has the feature: the host serves the extension when the
// persona declares it for this context, ahead of Mozilla's per-platform
// policy (ANGLE or macOS only). True when it is declared; otherwise Mozilla's
// policy answers, as it did. The page is told the persona's
// list on the client side; a declared extension the host refused tripped the
// assert in ProvokingVertex and took the main process down on Linux
// (2026-11-07).
bool StealthWebGLExtensionServed(const WebGLContext* aCtx,
                                 WebGLExtensionID aExt);

// RequestExtension, after Mozilla's check of the limits: a declared extension
// the host does not serve is harmless (nothing is created).
bool StealthWebGLExtensionUnserved(const WebGLContext* aCtx,
                                   WebGLExtensionID aExt);

// The entry points of extensions the persona declares and the host may not
// have enabled. They sit after Mozilla's IsContextLost() check (which has a
// side effect, HandlePendingContextLoss, that must run first) and, for the
// indexed variants, after Mozilla's validation of the enums: an entry point
// whose extension the host never enabled returns before Mozilla's
// MOZ_RELEASE_ASSERT, which stays. Until firefox-56 one call from the page
// aborted the host process (Linux: the main process). True when the call must
// return. Read with symbols 2026-11-07.
bool StealthWebGLDrawBuffersIndexedMissing(const WebGLContext* aCtx);
bool StealthWebGLPolygonOffsetClampMissing(const WebGLContext* aCtx);
bool StealthWebGLProvokingVertexMissing(const WebGLContext* aCtx);
bool StealthWebGLClipControlMissing(const WebGLContext* aCtx);

// InitAndValidateGL, after Mozilla's reads of the four stencil masks and their
// debug assertions: the masks start at all ones, ANGLE's value on Windows,
// instead of the driver's (Mesa trims to its stencil bits: 255). What a page
// sets is unchanged; the driver masks to its own bits either way. The four
// private fields of WebGLContext come as arguments.
void StealthInitStencilMasks(GLuint& aValueMaskFront, GLuint& aValueMaskBack,
                             GLuint& aWriteMaskFront, GLuint& aWriteMaskBack);

}  // namespace mozilla

#endif  // DOM_CANVAS_STEALTHWEBGLPARAMS_H_
