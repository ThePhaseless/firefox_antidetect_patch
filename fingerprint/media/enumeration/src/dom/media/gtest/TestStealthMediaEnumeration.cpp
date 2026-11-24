/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The resolve callback of MediaManager::GetPhysicalDevices is Mozilla's own,
// handed to Then inside StealthDeclaredEnumeration (StealthMediaEnumeration.h).
// With zoom.stealth.media.enumeration_ms at 0 it runs in the Then callback,
// with the value Then gives it; above 0 it runs later, from a delayed runnable,
// with the same value. Two Thens on one promise run in order on the same
// target, so what the second one sees tells whether the first one's callback
// had run when it returned.

#include "StealthMediaEnumeration.h"

#include "gtest/gtest.h"
#include "mozilla/MozPromise.h"
#include "mozilla/Preferences.h"
#include "mozilla/SpinEventLoopUntil.h"
#include "nsThreadUtils.h"

using namespace mozilla;

namespace {

using StealthEnumerationIntPromise = MozPromise<int, bool, false>;

struct StealthEnumerationWait {
  explicit StealthEnumerationWait(uint32_t aMs) {
    Preferences::SetUint("zoom.stealth.media.enumeration_ms", aMs);
  }
  ~StealthEnumerationWait() { Preferences::ClearUser("zoom.stealth.media.enumeration_ms"); }
};

// Runs the callback through StealthDeclaredEnumeration; returns the value the
// callback got and what it had got when the next Then ran.
struct StealthEnumerationOutcome {
  int mSeen = 0;
  int mSeenByTheNextThen = 0;
};

StealthEnumerationOutcome StealthEnumerationRun(int aValue) {
  StealthEnumerationOutcome out;
  bool done = false;
  bool next = false;
  RefPtr<StealthEnumerationIntPromise> promise = StealthEnumerationIntPromise::CreateAndResolve(aValue, __func__);
  promise->Then(
      GetCurrentSerialEventTarget(), __func__,
      StealthDeclaredEnumeration([&out, &done](int aGot) mutable {
        out.mSeen = aGot;
        done = true;
      }),
      [](bool) { MOZ_CRASH("the promise does not reject"); });
  promise->Then(
      GetCurrentSerialEventTarget(), __func__,
      [&out, &next](int) { out.mSeenByTheNextThen = out.mSeen; next = true; },
      [](bool) { MOZ_CRASH("the promise does not reject"); });
  SpinEventLoopUntil("StealthMediaEnumeration: both callbacks ran"_ns,
                     [&] { return done && next; });
  return out;
}

}  // namespace

TEST(StealthMediaEnumeration, WithNoDeclarationTheCallbackRunsInTheThenCallback)
{
  StealthEnumerationOutcome out = StealthEnumerationRun(7);
  EXPECT_EQ(out.mSeen, 7);
  EXPECT_EQ(out.mSeenByTheNextThen, 7);
}

TEST(StealthMediaEnumeration, WithADeclarationTheCallbackRunsLaterWithTheSameValue)
{
  StealthEnumerationWait declared(1);
  StealthEnumerationOutcome out = StealthEnumerationRun(7);
  EXPECT_EQ(out.mSeen, 7);
  // Negative control: not run when the next Then ran, as the pref at 0 does.
  EXPECT_EQ(out.mSeenByTheNextThen, 0);
}
