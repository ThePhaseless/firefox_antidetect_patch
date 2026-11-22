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
#include "js/CompileOptions.h"
#include "js/RootingAPI.h"
#include "js/SourceText.h"
#include "js/Value.h"
#include "jsapi.h"
#include "mozilla/dom/ScriptSettings.h"
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
  const std::string stack = StackReadThroughJugglerFrame();
  // The control: the page's own frame is there.
  EXPECT_NE(stack.find("page_script.js"), std::string::npos) << stack;
  // Juggler's frame, which called the page's function, is not.
  EXPECT_EQ(stack.find("juggler"), std::string::npos) << stack;
  EXPECT_EQ(stack.find("TestFrame.js"), std::string::npos) << stack;
}
