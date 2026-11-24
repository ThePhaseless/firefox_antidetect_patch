/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// No stack string a page can read names Juggler's code (feature
// fingerprint/js-surface/stack-frames). BuildStackString
// (js/src/vm/SavedStacks.cpp) drops the frames whose source is under
// resource://gre/modules/juggler/ from every stack string it builds.
//
// Two scripts are compiled: one under a filename of Juggler's, one under a
// filename of a page. The page's function reads `new Error().stack` and is
// called from the one of Juggler's, so Juggler's frame is in the middle of the
// walk. The page's frame must be in the string (the control: the stack is the
// real one and not an empty string) and Juggler's must not. Without the hook
// the stack names the Juggler script and the test is red.

#include <string>

#include "gtest/gtest.h"
#include "js/CharacterEncoding.h"
#include "js/CompilationAndEvaluation.h"
#include "js/CallAndConstruct.h"
#include "js/CompileOptions.h"
#include "js/Principals.h"
#include "js/PropertyAndElement.h"
#include "js/Realm.h"
#include "js/RootingAPI.h"
#include "js/SourceText.h"
#include "js/Stack.h"
#include "js/Value.h"
#include "jsapi.h"
#include "mozilla/dom/ScriptSettings.h"
#include "mozilla/glean/fog_ffi_generated.h"
#include "nsString.h"
#include "xpcpublic.h"

namespace {

constexpr char kJugglerFile[] = "resource://gre/modules/juggler/TestFrame.js";
constexpr char kPageFile[] = "https://example.test/page_script.js";
constexpr char kRunFile[] = "https://example.test/page_run.js";

bool Run(JSContext* cx, const char* aFile, const char16_t* aSource,
         JS::MutableHandle<JS::Value> aResult) {
  JS::CompileOptions options(cx);
  options.setFileAndLine(aFile, 1);
  JS::SourceText<char16_t> source;
  if (!source.init(cx, aSource, std::char_traits<char16_t>::length(aSource),
                   JS::SourceOwnership::Borrowed)) {
    return false;
  }
  return JS::Evaluate(cx, options, source, aResult);
}

// The stack that a page function reads when Juggler's function is its caller.
std::string StackReadThroughJugglerFrame() {
  mozilla::dom::AutoJSAPI jsapi;
  MOZ_ALWAYS_TRUE(jsapi.Init(xpc::PrivilegedJunkScope()));
  JSContext* cx = jsapi.cx();
  JS::Rooted<JS::Value> result(cx);

  EXPECT_TRUE(Run(cx, kJugglerFile, u"function viaJuggler(f) { return f(); }",
                  &result));
  EXPECT_TRUE(Run(cx, kPageFile,
                  u"function readStack() { return new Error().stack; }",
                  &result));
  EXPECT_TRUE(Run(cx, kRunFile, u"viaJuggler(readStack)", &result));
  if (!result.isString()) {
    ADD_FAILURE() << "the page's function did not return a string";
    return std::string();
  }
  JS::Rooted<JSString*> str(cx, result.toString());
  JS::UniqueChars utf8 = JS_EncodeStringToUTF8(cx, str);
  return utf8 ? std::string(utf8.get()) : std::string();
}

}  // namespace

TEST(StealthStackFrames, JugglersFrameIsNotInTheStackAPageReads)
{
  // The gtest process starts FOG (testing/gtest/mozilla/GTestRunner.cpp), whose
  // glean.init thread records the data-directory health metric after the
  // preinit queue is flushed, and this test ends the process within a
  // millisecond: Glean's shutdown can close the database before that record,
  // and the thread panics ("No database found" in storage()). Resetting FOG
  // first, as the gtests that touch FOG do (dom/quota/test/gtest/
  // TestTelemetry.cpp:13-14, toolkit/components/glean/tests/gtest/
  // FOGFixture.h:17-19), joins the init thread before the test body (glean
  // test_reset_glean: destroy_glean, then initialize_internal and
  // glean_core::join_init), so no init thread is left to race the shutdown.
  nsCString empty;
  ASSERT_EQ(NS_OK, mozilla::glean::impl::fog_test_reset(&empty, &empty));

  const std::string stack = StackReadThroughJugglerFrame();
  // The control: the page's own frame is there.
  EXPECT_NE(stack.find("page_script.js"), std::string::npos) << stack;
  // Juggler's frame, which called the page's function, is not.
  EXPECT_EQ(stack.find("juggler"), std::string::npos) << stack;
  EXPECT_EQ(stack.find("TestFrame.js"), std::string::npos) << stack;
}

namespace {

// Natives for the tests below: a stack captured where it is called (the async parent of what runs next), and a call made with
// that stack as its async parent.
bool CaptureStackNative(JSContext* cx, unsigned argc, JS::Value* vp) {
  JS::CallArgs args = JS::CallArgsFromVp(argc, vp);
  JS::Rooted<JSObject*> stack(cx);
  if (!JS::CaptureCurrentStack(cx, &stack)) {
    return false;
  }
  args.rval().setObjectOrNull(stack);
  return true;
}

bool CallWithAsyncParentNative(JSContext* cx, unsigned argc, JS::Value* vp) {
  JS::CallArgs args = JS::CallArgsFromVp(argc, vp);
  if (args.length() != 2 || !args[0].isObject()) {
    JS_ReportErrorASCII(cx, "callWithAsyncParent(stack, fn)");
    return false;
  }
  JS::Rooted<JSObject*> stack(cx, &args[0].toObject());
  JS::Rooted<JS::Value> fn(cx, args[1]);
  JS::AutoSetAsyncStackForNewCalls asyncParent(
      cx, stack, "TestAsync",
      JS::AutoSetAsyncStackForNewCalls::AsyncCallKind::EXPLICIT);
  return JS::Call(cx, JS::UndefinedHandleValue, fn,
                  JS::HandleValueArray::empty(), args.rval());
}

constexpr char kJugglerFile2[] = "resource://gre/modules/juggler/TestFrame2.js";
constexpr char kPageFile2[] = "https://example.test/page_two.js";
constexpr char kPageFile3[] = "https://example.test/page_three.js";

std::string StackString(JSContext* aCx, JS::Handle<JS::Value> aResult) {
  if (!aResult.isString()) {
    ADD_FAILURE() << "the page's function did not return a string";
    return std::string();
  }
  JS::Rooted<JSString*> str(aCx, aResult.toString());
  JS::UniqueChars utf8 = JS_EncodeStringToUTF8(aCx, str);
  return utf8 ? std::string(utf8.get()) : std::string();
}

// The stack string with the lines that name aNeedle left out.
std::string WithoutTheLinesNaming(const std::string& aStack, const char* aNeedle) {
  std::string out;
  size_t from = 0;
  while (from < aStack.size()) {
    size_t end = aStack.find('\n', from);
    end = end == std::string::npos ? aStack.size() : end + 1;
    const std::string line = aStack.substr(from, end - from);
    if (line.find(aNeedle) == std::string::npos) {
      out += line;
    }
    from = end;
  }
  return out;
}

struct StackFixture {
  mozilla::dom::AutoJSAPI mJsapi;
  JSContext* mCx = nullptr;

  StackFixture() {
    nsCString empty;
    EXPECT_EQ(NS_OK, mozilla::glean::impl::fog_test_reset(&empty, &empty));
    MOZ_ALWAYS_TRUE(mJsapi.Init(xpc::PrivilegedJunkScope()));
    mCx = mJsapi.cx();
    JS::Rooted<JSObject*> global(mCx, JS::CurrentGlobalOrNull(mCx));
    EXPECT_TRUE(JS_DefineFunction(mCx, global, "captureStack", CaptureStackNative, 0, 0));
    EXPECT_TRUE(JS_DefineFunction(mCx, global, "callWithAsyncParent", CallWithAsyncParentNative, 2, 0));
  }

  void Define(const char* aFile, const char16_t* aSource) {
    JS::Rooted<JS::Value> result(mCx);
    EXPECT_TRUE(Run(mCx, aFile, aSource, &result));
  }

  std::string Read(const char* aFile, const char16_t* aSource) {
    JS::Rooted<JS::Value> result(mCx);
    EXPECT_TRUE(Run(mCx, aFile, aSource, &result));
    return StackString(mCx, result);
  }
};

}  // namespace

// Juggler's frame in the middle of an async chain: page frame, an async link, Juggler's frame, a page frame. The walk shows
// the page frames, the async cause of the one that has it included, and no frame of Juggler's. The control is the same chain
// with the middle function in a page file: its frame is shown, and every other line is the line the first stack has.
TEST(StealthStackFrames, JugglersFrameBetweenAsyncFramesIsLeftOutAndTheRestIsAsItWas)
{
  StackFixture f;
  f.Define(kPageFile, u"function readStackA() { return new Error().stack; }");
  f.Define(kJugglerFile2, u"function jugRelayA(fn) { return fn(); }");
  f.Define(kPageFile2,
           u"function innerA() { return callWithAsyncParent(captureStack(), readStackA); }"
           u"function outerA() { return jugRelayA(innerA); }");
  const std::string withJuggler = f.Read(kRunFile, u"outerA()");

  // The control: the same functions, the relay in a page file.
  f.Define(kPageFile3, u"function jugRelayB(fn) { return fn(); }");
  f.Define(kPageFile2,
           u"function innerB() { return callWithAsyncParent(captureStack(), readStackA); }"
           u"function outerB() { return jugRelayB(innerB); }");
  const std::string control = f.Read(kRunFile, u"outerB()");

  EXPECT_EQ(withJuggler.find("juggler"), std::string::npos) << withJuggler;
  EXPECT_EQ(withJuggler.find("jugRelayA"), std::string::npos) << withJuggler;
  EXPECT_NE(control.find("jugRelayB"), std::string::npos) << control;
  EXPECT_NE(withJuggler.find("TestAsync*innerA@"), std::string::npos) << withJuggler;
  EXPECT_NE(withJuggler.find("outerA@"), std::string::npos) << withJuggler;
  // Every line the control has, but the relay's, is a line of the first stack, in the same order, with the same flags
  // (the names differ by the letter of the case).
  std::string expected = WithoutTheLinesNaming(control, "jugRelayB");
  for (size_t at; (at = expected.find("innerB")) != std::string::npos;) expected.replace(at, 6, "innerA");
  for (size_t at; (at = expected.find("outerB")) != std::string::npos;) expected.replace(at, 6, "outerA");
  EXPECT_EQ(withJuggler, expected);
}

// Juggler's frame as the first frame of the stack, and as the last: neither is shown. The control is the same stack with the
// function in a page file, less its line.
TEST(StealthStackFrames, JugglersFirstAndLastFramesAreLeftOut)
{
  StackFixture f;
  // First: the error is made in Juggler's function, which a page function called.
  f.Define(kJugglerFile2, u"function jugMakeC() { return new Error().stack; }");
  f.Define(kPageFile2, u"function viaPageC() { return jugMakeC(); }");
  const std::string first = f.Read(kRunFile, u"viaPageC()");
  f.Define(kPageFile3, u"function jugMakeD() { return new Error().stack; }");
  f.Define(kPageFile2, u"function viaPageD() { return jugMakeD(); }");
  const std::string firstControl = f.Read(kRunFile, u"viaPageD()");
  EXPECT_EQ(first.find("jugMakeC"), std::string::npos) << first;
  EXPECT_NE(firstControl.find("jugMakeD"), std::string::npos) << firstControl;
  EXPECT_NE(first.find("viaPageC@"), std::string::npos) << first;
  std::string expectedFirst = WithoutTheLinesNaming(firstControl, "jugMakeD");
  for (size_t at; (at = expectedFirst.find("viaPageD")) != std::string::npos;) expectedFirst.replace(at, 8, "viaPageC");
  EXPECT_EQ(first, expectedFirst);

  // Last: the page's function is called from the top level of a script of Juggler's.
  f.Define(kPageFile, u"function readStackE() { return new Error().stack; }");
  const std::string last = f.Read(kJugglerFile2, u"readStackE()");
  const std::string lastControl = f.Read(kRunFile, u"readStackE()");
  EXPECT_EQ(last.find("juggler"), std::string::npos) << last;
  EXPECT_NE(lastControl.find("page_run.js"), std::string::npos) << lastControl;
  EXPECT_EQ(last, WithoutTheLinesNaming(lastControl, "page_run.js"));
}

// The control of the others: a stack with no frame of Juggler's is the stack Mozilla's walk gives, every frame and in order.
TEST(StealthStackFrames, AStackWithoutJugglersFramesIsMozillasOwn)
{
  StackFixture f;
  f.Define(kPageFile, u"function readStackF() { return new Error().stack; }");
  f.Define(kPageFile2, u"function middleF() { return readStackF(); } function topF() { return middleF(); }");
  const std::string stack = f.Read(kRunFile, u"topF()");
  const size_t read = stack.find("readStackF@");
  const size_t middle = stack.find("middleF@");
  const size_t top = stack.find("topF@");
  const size_t run = stack.find("page_run.js");
  ASSERT_NE(read, std::string::npos) << stack;
  ASSERT_NE(middle, std::string::npos) << stack;
  ASSERT_NE(top, std::string::npos) << stack;
  ASSERT_NE(run, std::string::npos) << stack;
  EXPECT_LT(read, middle);
  EXPECT_LT(middle, top);
  EXPECT_LT(top, run);
  EXPECT_EQ(stack.find("Async*"), std::string::npos) << stack;
}

namespace {

// A stack captured by running aSource (a script of aFile), written in the V8 format as the reader a page is would get it.
std::string CapturedStackInV8Format(StackFixture& aFixture, const char* aFile, const char16_t* aSource) {
  JSContext* cx = aFixture.mCx;
  JS::Rooted<JS::Value> result(cx);
  EXPECT_TRUE(Run(cx, aFile, aSource, &result));
  if (!result.isObject()) {
    ADD_FAILURE() << "captureStack did not give a stack";
    return std::string();
  }
  JS::Rooted<JSObject*> stack(cx, &result.toObject());
  JS::Rooted<JSString*> str(cx);
  JSPrincipals* principals = JS::GetRealmPrincipals(JS::GetCurrentRealmOrNull(cx));
  EXPECT_TRUE(JS::BuildStackString(cx, principals, stack, &str, 0, js::StackFormat::V8));
  JS::UniqueChars utf8 = str ? JS_EncodeStringToUTF8(cx, str) : JS::UniqueChars();
  return utf8 ? std::string(utf8.get()) : std::string();
}

}  // namespace

// V8 format marks the last frame by the absence of a next one, and the frames before it end with a newline. When the frames of
// Juggler end the stack, the walk that skipped them itself met the first of them as the next frame of the last frame shown, so
// that frame kept its newline: the string ends with one. The control is the same stack with the top level in a page file: the
// last frame is the page's top level, and the string has no newline at its end. The stack with Juggler's tail is the control
// less the last frame, as the walk gave it, newline included.
TEST(StealthStackFrames, TheV8FormatKeepsTheNewlineOfTheLastShownFrameWhenJugglersFramesEndTheStack)
{
  StackFixture f;
  f.Define(kPageFile, u"function captureV() { return captureStack(); }");
  const std::string withJugglersTail = CapturedStackInV8Format(f, kJugglerFile2, u"captureV()");
  const std::string control = CapturedStackInV8Format(f, kRunFile, u"captureV()");

  ASSERT_FALSE(control.empty());
  EXPECT_NE(control.back(), '\n') << control;
  EXPECT_NE(control.find("captureV"), std::string::npos) << control;
  EXPECT_NE(control.find("page_run.js"), std::string::npos) << control;
  const size_t firstLineEnd = control.find('\n');
  ASSERT_NE(firstLineEnd, std::string::npos) << control;
  EXPECT_EQ(withJugglersTail, control.substr(0, firstLineEnd + 1));
  EXPECT_EQ(withJugglersTail.find("juggler"), std::string::npos) << withJugglersTail;
}

// With a page frame after Juggler's, the last frame is the page's and has no newline, as with no Juggler frame at all.
TEST(StealthStackFrames, TheV8FormatEndsWithoutANewlineWhenAPageFrameFollowsJugglersFrames)
{
  StackFixture f;
  f.Define(kJugglerFile2, u"function jugRelayV(fn) { return fn(); }");
  f.Define(kPageFile, u"function captureW() { return captureStack(); }");
  const std::string through = CapturedStackInV8Format(f, kRunFile, u"jugRelayV(captureW)");
  f.Define(kPageFile3, u"function pageRelayW(fn) { return fn(); }");
  const std::string control = CapturedStackInV8Format(f, kRunFile, u"pageRelayW(captureW)");
  ASSERT_FALSE(through.empty());
  EXPECT_NE(through.back(), '\n') << through;
  EXPECT_EQ(through.find("jugRelayV"), std::string::npos) << through;
  EXPECT_NE(control.find("pageRelayW"), std::string::npos) << control;
}
