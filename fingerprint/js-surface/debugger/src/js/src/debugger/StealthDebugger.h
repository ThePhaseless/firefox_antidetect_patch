/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*-
 * vim: set ts=8 sts=2 et sw=2 tw=80:
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Invisible attach of a Debugger (feature debugger-invisible-attach).
//
// Stealth (invisible-attach): read stealthMode BEFORE the no-GC region
// (JS_GetProperty can GC). When the Debugger object has the property
// stealthMode set to true (Juggler sets it right after `new Debugger()`,
// juggler/content/Runtime.js:131, before any addDebuggee),
// Debugger::addDebuggeeGlobal keeps tracking the global (debuggees,
// debuggeeZones: steps 2-3) but DOESN'T register in Realm::debuggers_ (step 1)
// and DOESN'T enter debug mode (step 5). Result: global->getDebuggers() stays
// empty => hasDebuggers()==false, Ion stays enabled, there is no
// slowPathOnNativeCall overhead, and the page realm is web-indistinguishable
// from a never-debugged realm. executeInGlobal/page.evaluate and GC teardown
// use debuggees/debuggeeZones (not debuggers_), so Juggler keeps working.
//
// Debugger::invisibleDebuggee_ (Debugger.h) is set when this Debugger attached
// its debuggees OUT of Realm::debuggers_ (stealthMode), so the page realm
// reports no debuggers (hasDebuggers()==false). It is cached at addDebuggee
// time because removeDebuggeeGlobal can run during GC sweep where JS (the
// stealthMode property read) cannot run, and there we must not try to erase
// from debuggers_ (findDebuggerInVector asserts the entry exists). It must stay
// a plain bool, placed between allocationsLog and trackingAllocationSites.

#ifndef debugger_StealthDebugger_h
#define debugger_StealthDebugger_h

#include "mozilla/Assertions.h"  // for MOZ_ASSERT

#include "js/PropertyAndElement.h"  // for JS_GetProperty
#include "js/RootingAPI.h"          // for JS::Rooted
#include "js/TypeDecls.h"           // for JSContext, JSObject
#include "js/Value.h"               // for JS::Value

namespace mozilla {

// Reads the stealthMode property of the Debugger object. Call it BEFORE the
// no-GC region of addDebuggeeGlobal: JS_GetProperty can run JS and so can GC.
// The return value of JS_GetProperty is deliberately not propagated: on failure
// the result is false (not stealth) and the caller carries on.
inline bool StealthDebuggerReadMode(JSContext* cx, JSObject* debuggerObject) {
  MOZ_ASSERT(debuggerObject);
  JS::Rooted<JSObject*> dbgObj(cx, debuggerObject);
  JS::Rooted<JS::Value> stealthVal(cx);
  return JS_GetProperty(cx, dbgObj, "stealthMode", &stealthVal) &&
         stealthVal.isTrue();
}

// The hook of Debugger::addDebuggeeGlobal: reads stealthMode into the field
// Debugger::invisibleDebuggee_ (passed by the hook, G14: no friend), at the
// point where the property read has always been, before the no-GC region. The
// following hook lines of the function read the field: nothing else writes it
// between this call and the end of the function.
inline void StealthDebuggerReadMode(JSContext* cx, JSObject* debuggerObject,
                                    bool* aInvisibleDebuggee) {
  *aInvisibleDebuggee = StealthDebuggerReadMode(cx, debuggerObject);
}

// Releases the mozilla::ScopeExit rollback guards on the early successful
// return of an invisible attach, and returns true (the value of the return the
// hook line stands for). In that case step 4 (alloc-metadata builder,
// never attached for a stealth debuggee, so allocationMetadataBuilder_ stays
// null = vanilla even if tracking is ever enabled) and step 5 (setIsDebuggee,
// updateDebuggerObservesWasm/Coverage, ensureExecutionObservabilityOfRealm: the
// Realm does NOT enter debug mode) are skipped.
//
// The lines of Mozilla's addDebuggeeGlobal/removeDebuggeeGlobal that read
// invisibleDebuggee_ skip a Mozilla statement for a stealth debuggee; Mozilla's
// own lines stay as Mozilla wrote them.
//   step (1): an unbraced `if (!invisibleDebuggee_)` in front of Mozilla's
//             `if (!globalDebuggers.append(...)) {...}`: no entry is pushed in
//             Realm::debuggers_ for a stealth debuggee.
//   rollback guard of step (1): released as soon as it is made when the
//             debuggee is stealth (StealthDebuggerReleaseIfInvisible), so it
//             never pops an entry that was not pushed.
//   between (3) and (4): `if (invisibleDebuggee_) return
//             StealthDebuggerReleaseGuards(...)`: steps (4) and (5) are skipped.
//   removeDebuggeeGlobal: `if (!invisibleDebuggee_)` before the erase: a
//             stealth debuggee never kept an entry (findDebuggerInVector asserts
//             the entry exists; erase on end() is undefined).
// The rollback guard of step (1), for a stealth debuggee, which pushed nothing
// to roll back: released at once (release() is idempotent, the early return of
// StealthDebuggerReleaseGuards releases it again).
template <typename Guard>
inline void StealthDebuggerReleaseIfInvisible(bool aInvisibleDebuggee,
                                              Guard& aGuard) {
  if (aInvisibleDebuggee) {
    aGuard.release();
  }
}

template <typename... Guards>
inline bool StealthDebuggerReleaseGuards(Guards&... guards) {
  (guards.release(), ...);
  return true;
}

}  // namespace mozilla

#endif  // debugger_StealthDebugger_h
