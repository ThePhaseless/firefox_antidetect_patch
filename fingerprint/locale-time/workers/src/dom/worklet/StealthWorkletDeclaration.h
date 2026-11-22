/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_worklet_StealthWorkletDeclaration_h
#define mozilla_dom_worklet_StealthWorkletDeclaration_h

#include <utility>

#include "js/RealmOptions.h"
#include "mozilla/dom/StealthSessionDeclaration.h"
#include "mozilla/dom/WorkletGlobalScope.h"
#include "mozilla/dom/WorkletImpl.h"
#include "nsPIDOMWindowInlines.h"
#include "nsRFPService.h"
#include "nsString.h"

class nsPIDOMWindowInner;

namespace mozilla {

/**
 * STEALTHFOX (firefox-50): the language and the zone a worklet declares.
 * Header only, so that the hooks in WorkletImpl.cpp and
 * WorkletGlobalScope.cpp cost no line in moz.build; the feature's history is
 * in fingerprint/locale-time/workers/FEATURE.md.
 *
 * Until firefox-50 a worklet's realm got only resistFingerprinting's values:
 * it took the process's zone, and a default locale nobody set (WorkletThread,
 * "FIXME: JS_SetDefaultLocale"), so Intl in an AudioWorklet answered en-US
 * whatever the session declared.
 *
 * The language and the zone the creating window's context declares are read
 * on the main thread when the worklet is created (WorkletLoadInfo's
 * constructor), for the realm the worklet thread creates later
 * (WorkletGlobalScope::CreateRealmOptions). Any thread: they are written once,
 * in the constructor, and never modified.
 *
 * WorkletLoadInfo names this struct a friend and holds the two values in one
 * member of ours, mStealthDeclared (language first, zone second): three lines
 * of ours in WorkletImpl.h, and no public accessor.
 */
struct StealthWorkletAccess {
  // Main thread, the last statement of the WorkletLoadInfo constructor, after
  // mOuterWindowID is set: the declared language and zone of the window's
  // context.
  //
  // GetBrowsingContext() is declared inline in nsPIDOMWindow.h and defined in
  // nsPIDOMWindowInlines.h, which this header includes: without it WorkletImpl.cpp
  // links only when the unified build happens to group it with a file that
  // includes it (151 did, 157 does not: an undefined symbol in libxul).
  static void Declare(WorkletLoadInfo* aInfo, nsPIDOMWindowInner* aWindow) {
    dom::GetDeclaredLanguage(aWindow->GetBrowsingContext(),
                             aInfo->mStealthDeclared.first);
    dom::GetDeclaredTimezone(aWindow->GetBrowsingContext(),
                             aInfo->mStealthDeclared.second);
  }

  static const nsCString& Language(const WorkletLoadInfo& aInfo) {
    return aInfo.mStealthDeclared.first;
  }
  static const nsString& Timezone(const WorkletLoadInfo& aInfo) {
    return aInfo.mStealthDeclared.second;
  }
};

// Worklet thread, in WorkletGlobalScope::CreateRealmOptions, right after
// Mozilla's two resistFingerprinting branches. The rule of the window's and
// the workers' realms (SetDeclaredRealmTimeAndLanguage), with the language and
// the zone of the context that created the worklet: the declared zone and the
// primary tag of the declared language, unless resistFingerprinting asked for
// its spoofed values. Writes only aOptions.behaviors().
inline void StealthDeclareWorkletRealm(const dom::WorkletGlobalScope* aScope,
                                       JS::RealmOptions& aOptions) {
  const WorkletLoadInfo& info = aScope->Impl()->LoadInfo();
  dom::SetDeclaredRealmTimeAndLanguage(
      aOptions, aScope->ShouldResistFingerprinting(RFPTarget::JSDateTimeUTC),
      aScope->ShouldResistFingerprinting(RFPTarget::JSLocale),
      StealthWorkletAccess::Language(info),
      StealthWorkletAccess::Timezone(info));
}

}  // namespace mozilla

#endif  // mozilla_dom_worklet_StealthWorkletDeclaration_h
