/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthSpeechVoice.h"

#include <cstdint>

#include "nsDependentSubstring.h"
#include "nsReadableUtils.h"
#include "nsString.h"

namespace mozilla::dom {

namespace {

constexpr auto kStealthVoicePrefix = u"stealth-voice:"_ns;

bool IsStealthVoiceURI(const nsAString& aUri) {
  return StringBeginsWith(aUri, kStealthVoicePrefix);
}

// Extract field `idx` from the URI's trailing "NAME|LANG|D|L" section.
// idx 0=name, 1=lang, 2=default("0"/"1"), 3=local("0"/"1"). Missing = "".
void GetStealthVoiceField(const nsAString& aUri, uint32_t idx,
                          nsAString& aOut) {
  aOut.Truncate();
  const uint32_t prefixLen = kStealthVoicePrefix.Length();
  if (aUri.Length() <= prefixLen) return;
  nsDependentSubstring body(aUri, prefixLen);
  uint32_t cur = 0;
  int32_t start = 0;
  while (start <= static_cast<int32_t>(body.Length())) {
    int32_t bar = body.FindChar(u'|', start);
    if (bar < 0) bar = body.Length();
    if (cur == idx) {
      aOut = Substring(body, start, bar - start);
      return;
    }
    start = bar + 1;
    cur++;
  }
}

}  // namespace

void StealthVoiceMakeURI(const nsACString& aEntry, nsAString& aUri) {
  aUri.Assign(kStealthVoicePrefix);
  AppendUTF8toUTF16(aEntry, aUri);
}

// HERE OUR INTERNAL FORMAT USED TO LEAK, ALL THE WAY TO THE PAGE.
//
// `mUri` is our service encoding, "stealth-voice:NAME|LANG|D|L", and every
// other accessor of this file knows how to interpret it. This one did not: it
// returned `mUri` verbatim, so a page that calls
// `speechSynthesis.getVoices()[0].voiceURI` read a string that begins with the
// word "stealth". Measured on 2026-08-23 on the product:
//   by hand  -> urn:moz-tts:sapi:Microsoft David - English (United States)?en-US
//   product  -> stealth-voice:Microsoft David - English (United States)|en-US|1|1
// It is not an imperfect disguise: it is a signature that gives itself away,
// and it was the only surface in the whole measuring session that named us.
//
// The retail format was not deduced: it is copied from
// `dom/media/webspeech/synth/windows/SapiService.cpp`, which builds
// `"urn:moz-tts:sapi:" + description + "?" + locale`.
//
// AND THE SCHEME IS ALWAYS `sapi:`, EVEN ON LINUX. A real Linux Firefox would
// say `speechd:` (`SpeechDispatcherService.cpp`) and a macOS one `osx:`
// (`OSXSpeechSynthesizerService.mm`), but we declare Windows always and
// everywhere: it is engine rule 4, and it has the side effect of making the two
// builds identical here too.
bool StealthVoiceRetailURI(const nsAString& aUri, nsAString& aOut) {
  if (!IsStealthVoiceURI(aUri)) return false;
  nsAutoString name, lang;
  GetStealthVoiceField(aUri, 0, name);
  GetStealthVoiceField(aUri, 1, lang);
  aOut.AssignLiteral(u"urn:moz-tts:sapi:");
  aOut.Append(name);
  aOut.AppendLiteral(u"?");
  aOut.Append(lang);
  return true;
}

bool StealthVoiceName(const nsAString& aUri, nsAString& aOut) {
  if (!IsStealthVoiceURI(aUri)) return false;
  GetStealthVoiceField(aUri, 0, aOut);
  return true;
}

bool StealthVoiceLang(const nsAString& aUri, nsAString& aOut) {
  if (!IsStealthVoiceURI(aUri)) return false;
  GetStealthVoiceField(aUri, 1, aOut);
  return true;
}

bool StealthVoiceLocal(const nsAString& aUri, bool* aOut) {
  if (!IsStealthVoiceURI(aUri)) return false;
  nsAutoString field;
  GetStealthVoiceField(aUri, 3, field);
  *aOut = field.EqualsLiteral("1");
  return true;
}

bool StealthVoiceDefault(const nsAString& aUri, bool* aOut) {
  if (!IsStealthVoiceURI(aUri)) return false;
  nsAutoString field;
  GetStealthVoiceField(aUri, 2, field);
  *aOut = field.EqualsLiteral("1");
  return true;
}

}  // namespace mozilla::dom
