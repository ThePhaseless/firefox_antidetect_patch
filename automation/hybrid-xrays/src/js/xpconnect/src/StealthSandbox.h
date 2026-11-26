/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef xpc_StealthSandbox_h
#define xpc_StealthSandbox_h

#include "ExpandedPrincipal.h"
#include "xpcprivate.h"
#include "StealthHybridXray.h"
#include "mozilla/BasePrincipal.h"
#include "mozilla/Maybe.h"
#include "nsIPrincipal.h"

#include "js/ErrorReport.h"  // JS_ReportErrorASCII
#include "js/PropertyDescriptor.h"
#include "js/RootingAPI.h"
#include "js/TypeDecls.h"

// The step of SandboxOptions::Parse that reads `hybridXrays`: a member of
// Mozilla's class, defined here by its qualified name (it needs ParseBoolean,
// which is protected in OptionsBase). Parse's chain wraps the `wantXrays` read
// in it, so it runs right after that read and only when that read worked, as
// the line it replaced did: aParsed is the result of the `wantXrays` read.
inline bool xpc::SandboxOptions::StealthParseHybridXrays(bool aParsed) {
  return aParsed && ParseBoolean("hybridXrays", &hybridXrays);
}

namespace mozilla {

/**
 * STEALTHFOX [B322]: what js/xpconnect/src/Sandbox.cpp needs for the caller's
 * world (the `hybridXrays` option of Cu.Sandbox, which only Juggler passes;
 * the compartment flag is CompartmentPrivate::hybridXrays in xpcprivate.h and
 * the wrapper rule is written above HybridXrayWrapper in StealthHybridXray.h).
 *
 * Sections, one per hook in Sandbox.cpp:
 *
 *   getPropertyDescriptorImpl (SandboxProxyHandler): StealthGetPropertyDescriptor.
 *
 *   CreateSandboxObject: StealthCheckHybridXrays (before the options are
 *   used). The compartment flag is checked (reused compartment) in place, next
 *   to wantXrays.
 *
 *   SandboxOptions::Parse: StealthParseHybridXrays (above), a member of the
 *   class that wraps the read of `wantXrays` and reads the option after it
 *   (hybridXrays, in xpcprivate.h, defaults to false).
 *
 *   CreateSandboxObject, new compartment: StealthSetHybridXrays stores the
 *   option in the compartment (the reused compartment is checked in place).
 *
 * Main thread.
 */

// The property descriptor of `id` on `obj`, as SandboxProxyHandler wants it,
// in place of Mozilla's JS_GetPropertyDescriptorById. In a caller's world the
// prototype is the page's window behind a hybrid Xray, and a bare name
// (`document`, the page's `myFunction`, its top-level `const config`)
// resolves by the hybrid rule, in the order the page's realm resolves it
// (HybridXrayGetBareName, StealthHybridXray.h). Walking the wrapper
// generically would join the two views level by level, so a property the page
// put on the window could hide a standard one, and the page's traps would
// run. For any other object it is Mozilla's call, unchanged (holder is not
// used afterwards for a hybrid Xray).
inline bool StealthGetPropertyDescriptor(
    JSContext* aCx, JS::HandleObject aObj, JS::HandleId aId,
    JS::MutableHandle<mozilla::Maybe<JS::PropertyDescriptor>> aDesc,
    JS::MutableHandleObject aHolder) {
  if (IsHybridXrayWrapper(aObj)) {
    return HybridXrayGetBareName(aCx, aObj, aId, aDesc);
  }
  return JS_GetPropertyDescriptorById(aCx, aObj, aId, aDesc, aHolder);
}

// Checks the `hybridXrays` option of a sandbox about to be created. A
// caller's world has the page's own principal, and `hybridXrays` replaces
// `wantXrays` instead of adding to it: `wantXrays` would impose Xrays on the
// page reading the caller's objects as well. So the option needs a content
// principal (not the system principal, not an expanded one) and
// `wantXrays: false`. On refusal this reports a JS error on aCx and returns
// false; the caller returns NS_ERROR_INVALID_ARG. Without the option it
// returns true and does nothing.
inline bool StealthCheckHybridXrays(JSContext* aCx, nsIPrincipal* aPrincipal,
                                    const xpc::SandboxOptions& aOptions) {
  if (aOptions.hybridXrays &&
      (aPrincipal->IsSystemPrincipal() ||
       mozilla::BasePrincipal::Cast(aPrincipal)
           ->Is<ExpandedPrincipal>() ||
       aOptions.wantXrays)) {
    JS_ReportErrorASCII(aCx,
                        "hybridXrays needs a content principal and "
                        "wantXrays: false");
    return false;
  }
  return true;
}

// Stores the option in the compartment of a sandbox just created, next to
// Mozilla's own flags (CreateSandboxObject, new compartment). A reused
// compartment keeps its flag: it is checked against the option in place.
inline void StealthSetHybridXrays(xpc::CompartmentPrivate* aPriv,
                                  const xpc::SandboxOptions& aOptions) {
  aPriv->hybridXrays = aOptions.hybridXrays;
}

}  // namespace mozilla

#endif  // xpc_StealthSandbox_h
