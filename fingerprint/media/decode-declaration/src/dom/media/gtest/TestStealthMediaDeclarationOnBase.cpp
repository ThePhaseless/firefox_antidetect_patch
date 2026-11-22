/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The promise of mediaCapabilities.decodingInfo({type: "file"}) is resolved
// with the declared answer (zoom.stealth.media.decoding_info), whatever the
// engine found: it is asked through MediaCapabilities::DecodingInfo itself, the
// road a page takes. The declared answer is read from the promise.

#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "nsString.h"

#ifdef MOZ_WEBRTC
#  include "MediaCapabilities.h"
#  include "js/Promise.h"
#  include "js/PropertyAndElement.h"
#  include "mozilla/ErrorResult.h"
#  include "mozilla/SpinEventLoopUntil.h"
#  include "mozilla/dom/MediaCapabilitiesBinding.h"
#  include "mozilla/dom/Promise.h"
#  include "mozilla/dom/ScriptSettings.h"
#  include "xpcpublic.h"
#endif

using namespace mozilla;

#if defined(MOZ_WEBRTC) && !defined(MOZ_WIDGET_ANDROID)

namespace {

constexpr char kDeclarationPref[] = "zoom.stealth.media.decode_support";
constexpr char kDecodingInfoPref[] = "zoom.stealth.media.decoding_info";

// Sets a string pref, puts it back at the end of the test.
class DeclarationPref {
 public:
  DeclarationPref(const char* aName, const char* aSpec) : mName(aName) {
    Preferences::GetCString(mName, mOld);
    Preferences::SetCString(mName, nsDependentCString(aSpec));
  }
  ~DeclarationPref() { Preferences::SetCString(mName, mOld); }

 private:
  const char* mName;
  nsAutoCString mOld;
};

class DecodeSupportPref : public DeclarationPref {
 public:
  explicit DecodeSupportPref(const char* aSpec)
      : DeclarationPref(kDeclarationPref, aSpec) {}
};

// The types Gecko's own gate (CanHandleContainerType) lets through on any host
// when the track mime types are declared: the table below declares them.
constexpr char kTrackTypes[] =
    "video/avc|sw\n"
    "video/hevc|sw\n"
    "video/vp8|sw\n"
    "video/vp9|sw\n"
    "video/av1|sw";

struct DecodingAnswer {
  bool mSupported = false;
  bool mSmooth = false;
  bool mPowerEfficient = false;
};

// navigator.mediaCapabilities.decodingInfo({type: "file", video}) through
// MediaCapabilities::DecodingInfo itself, on a sandbox global: the same road a
// page takes, down to the promise of CreateNonWebRTCDecodingInfo, whose two
// delivery points carry the hook of the declared decodingInfo answer.
DecodingAnswer FileDecodingInfo(const nsAString& aContentType, uint32_t aWidth,
                                uint32_t aHeight) {
  DecodingAnswer answer;
  nsCOMPtr<nsIGlobalObject> global =
      xpc::NativeGlobal(xpc::PrivilegedJunkScope());
  RefPtr<dom::MediaCapabilities> caps = new dom::MediaCapabilities(global);

  dom::MediaDecodingConfiguration config;
  config.mType = dom::MediaDecodingType::File;
  dom::VideoConfiguration& video = config.mVideo.Construct();
  video.mContentType = aContentType;
  video.mWidth = aWidth;
  video.mHeight = aHeight;
  video.mBitrate = 2'000'000;
  video.mFramerate = 30.0;

  IgnoredErrorResult rv;
  RefPtr<dom::Promise> promise = caps->DecodingInfo(config, rv);
  EXPECT_FALSE(rv.Failed());
  if (rv.Failed() || !promise) {
    return answer;
  }
  MOZ_ALWAYS_TRUE(SpinEventLoopUntil(
      "TestStealthMediaDeclaration::FileDecodingInfo"_ns, [&] {
        return promise->State() != dom::Promise::PromiseState::Pending;
      }));
  EXPECT_EQ(promise->State(), dom::Promise::PromiseState::Resolved);
  if (promise->State() != dom::Promise::PromiseState::Resolved) {
    return answer;
  }

  dom::AutoJSAPI jsapi;
  MOZ_ALWAYS_TRUE(jsapi.Init(xpc::PrivilegedJunkScope()));
  JSContext* cx = jsapi.cx();
  JS::Rooted<JSObject*> promiseObj(cx, promise->PromiseObj());
  JS::Rooted<JS::Value> result(cx, JS::GetPromiseResult(promiseObj));
  EXPECT_TRUE(result.isObject());
  if (!result.isObject()) {
    return answer;
  }
  JS::Rooted<JSObject*> info(cx, &result.toObject());
  JS::Rooted<JS::Value> field(cx);
  MOZ_ALWAYS_TRUE(JS_GetProperty(cx, info, "supported", &field));
  answer.mSupported = field.isTrue();
  MOZ_ALWAYS_TRUE(JS_GetProperty(cx, info, "smooth", &field));
  answer.mSmooth = field.isTrue();
  MOZ_ALWAYS_TRUE(JS_GetProperty(cx, info, "powerEfficient", &field));
  answer.mPowerEfficient = field.isTrue();
  return answer;
}

}  // namespace

// The promise of decodingInfo is resolved with the declared answer, whatever
// the engine found: a vp8 file at 720p declared "no, no, no" reads so, and the
// same file declared "yes, yes, yes" reads so. No host answers both, so without
// the declared answer in the promise one of the two cases fails on every machine
// (a host with a vp8 decoder reads the first as supported, one without reads
// the second as unsupported).
TEST(StealthMediaDeclaration, DecodingInfoOfAFileAnswersFromTheDeclaration)
{
  DecodeSupportPref tracks(kTrackTypes);
  {
    DeclarationPref table(kDecodingInfoPref, "video/webm|vp8|000");
    const DecodingAnswer answer =
        FileDecodingInfo(u"video/webm; codecs=\"vp8\""_ns, 1280, 720);
    EXPECT_FALSE(answer.mSupported);
    EXPECT_FALSE(answer.mSmooth);
    EXPECT_FALSE(answer.mPowerEfficient);
  }
  {
    DeclarationPref table(kDecodingInfoPref, "video/webm|vp8|111");
    const DecodingAnswer answer =
        FileDecodingInfo(u"video/webm; codecs=\"vp8\""_ns, 1280, 720);
    EXPECT_TRUE(answer.mSupported);
    EXPECT_TRUE(answer.mSmooth);
    EXPECT_TRUE(answer.mPowerEfficient);
  }
}

#endif  // MOZ_WEBRTC && !MOZ_WIDGET_ANDROID
