/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// A Debugger with stealthMode set (js/src/debugger/StealthDebugger.h) tracks
// its debuggee but registers nothing in the debuggee realm: the realm shows no
// debugger. The observable is the cycle check of Debugger::addDebuggeeGlobal: a
// Debugger living in the debuggee realm that tries to debug the debugger's
// global finds a cycle only when the debuggee realm has debuggers. The control
// of every case is the same Debugger without stealthMode.

#include "DevTools.h"

#include <cstring>
#include <string>

#include "js/CharacterEncoding.h"
#include "js/CompilationAndEvaluation.h"
#include "js/Debug.h"
#include "js/GCAPI.h"
#include "js/PropertyAndElement.h"
#include "js/Realm.h"
#include "js/SourceText.h"
#include "mozilla/Utf8.h"

namespace {

struct StealthDebugger : public DevTools {
  JS::PersistentRooted<JSObject*> mTarget;

  bool Eval(const char* aCode, JS::MutableHandle<JS::Value> aRv) {
    JS::CompileOptions options(cx);
    options.setFileAndLine("TestStealthDebugger", 1);
    JS::SourceText<mozilla::Utf8Unit> source;
    return source.init(cx, aCode, strlen(aCode),
                       JS::SourceOwnership::Borrowed) &&
           JS::Evaluate(cx, options, source, aRv);
  }

  bool EvalInt(const char* aCode, int32_t* aOut) {
    JS::Rooted<JS::Value> rv(cx);
    if (!Eval(aCode, &rv) || !rv.isInt32()) {
      return false;
    }
    *aOut = rv.toInt32();
    return true;
  }

  // The debugger realm (the fixture's global) gets Debugger. The debuggee is a
  // second global, in its own realm and compartment, with Debugger too, and a
  // wrapper of the debugger's global called debuggerGlobal.
  bool SetUpGlobals() {
    if (!JS::InitRealmStandardClasses(cx) ||
        !JS_DefineDebuggerObject(cx, global)) {
      return false;
    }
    JS::RealmOptions options;
    options.behaviors().setReduceTimerPrecisionCallerType(
        JS::RTPCallerTypeToken{0});
    mTarget.init(cx, JS_NewGlobalObject(cx, getGlobalClass(), nullptr,
                                        JS::FireOnNewGlobalHook, options));
    if (!mTarget) {
      return false;
    }
    {
      JSAutoRealm ar(cx, mTarget.get());
      JS::Rooted<JSObject*> debuggerGlobal(cx, global.get());
      if (!JS::InitRealmStandardClasses(cx) ||
          !JS_DefineDebuggerObject(cx, mTarget) ||
          !JS_WrapObject(cx, &debuggerGlobal)) {
        return false;
      }
      JS::Rooted<JS::Value> value(cx, JS::ObjectValue(*debuggerGlobal));
      if (!JS_SetProperty(cx, mTarget, "debuggerGlobal", value)) {
        return false;
      }
    }
    JS::Rooted<JSObject*> target(cx, mTarget.get());
    if (!JS_WrapObject(cx, &target)) {
      return false;
    }
    JS::Rooted<JS::Value> value(cx, JS::ObjectValue(*target));
    return JS_SetProperty(cx, global, "target", value);
  }

  // In the debugger realm: a Debugger, in stealth mode or not, with the target
  // as its debuggee.
  bool Attach(bool aStealth) {
    int32_t count = 0;
    return EvalInt(aStealth ? "var dbg = new Debugger(); dbg.stealthMode = true;"
                              "dbg.addDebuggee(target); dbg.getDebuggees().length;"
                            : "var dbg = new Debugger();"
                              "dbg.addDebuggee(target); dbg.getDebuggees().length;",
                   &count) &&
           count == 1;
  }

  // In the debuggee realm: what a Debugger of that realm finds when it tries to
  // debug the debugger's global. "no cycle" when the realm shows no debugger.
  std::string CycleProbe() {
    JSAutoRealm ar(cx, mTarget.get());
    JS::Rooted<JS::Value> rv(cx);
    if (!Eval("var probe = new Debugger(); var out = 'no cycle';"
              "try { probe.addDebuggee(debuggerGlobal); }"
              "catch (e) { out = String(e.message); } out;",
              &rv) ||
        !rv.isString()) {
      return "probe failed";
    }
    JS::Rooted<JSString*> str(cx, rv.toString());
    JS::UniqueChars chars = JS_EncodeStringToUTF8(cx, str);
    return chars ? std::string(chars.get()) : std::string("probe failed");
  }

  static bool IsCycle(const std::string& aMessage) {
    return aMessage.find("already debugging the debugger") !=
           std::string::npos;
  }

  void CollectAll() {
    JS::PrepareForFullGC(cx);
    JS::NonIncrementalGC(cx, JS::GCOptions::Normal, JS::GCReason::API);
  }
};

TEST_F(StealthDebugger, ARealmShowsNoDebuggerOnlyWhenTheDebuggerIsInStealthMode) {
  ASSERT_TRUE(_initialized);
  ASSERT_TRUE(SetUpGlobals());
  ASSERT_TRUE(Attach(true));
  EXPECT_EQ(CycleProbe(), "no cycle");
}

TEST_F(StealthDebugger, WithoutStealthModeTheRealmShowsTheDebugger) {
  ASSERT_TRUE(_initialized);
  ASSERT_TRUE(SetUpGlobals());
  ASSERT_TRUE(Attach(false));
  EXPECT_TRUE(IsCycle(CycleProbe()));
}

TEST_F(StealthDebugger, RemovingTheDebuggeeLeavesNothingInEitherMode) {
  ASSERT_TRUE(_initialized);
  ASSERT_TRUE(SetUpGlobals());
  for (bool stealth : {true, false}) {
    ASSERT_TRUE(Attach(stealth));
    int32_t count = -1;
    ASSERT_TRUE(EvalInt("dbg.removeDebuggee(target); dbg.getDebuggees().length;",
                        &count));
    EXPECT_EQ(count, 0);
    EXPECT_EQ(CycleProbe(), "no cycle");
  }
}

TEST_F(StealthDebugger, ACollectedDebuggerLeavesNothingInEitherMode) {
  ASSERT_TRUE(_initialized);
  ASSERT_TRUE(SetUpGlobals());
  for (bool stealth : {true, false}) {
    ASSERT_TRUE(Attach(stealth));
    int32_t zero = -1;
    ASSERT_TRUE(EvalInt("dbg = null; 0;", &zero));
    // The Debugger dies in the sweep of this GC while its debuggee lives:
    // Debugger::removeDebuggeeGlobal runs from the sweep.
    CollectAll();
    EXPECT_EQ(CycleProbe(), "no cycle");
  }
}

}  // namespace
