/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef NETWERK_PROTOCOL_HTTP_STEALTHACCEPTLANGUAGE_H_
#define NETWERK_PROTOCOL_HTTP_STEALTHACCEPTLANGUAGE_H_

#include "mozilla/Assertions.h"
#include "mozilla/net/rust_helper.h"
#include "nsString.h"

namespace mozilla::net {

// The Accept-Language value of a request whose BrowsingContext has a
// languageOverride. The override is a language LIST here, not one tag:
// `juggler.locale.override` seeds the field with the same list the launcher
// writes to intl.accept_languages ("it-IT, it, en-US, en"), because
// navigator.languages is split from it. Sent as it is, that list went out raw
// (spaces, no q-values) on every request that has a BrowsingContext, while
// requests without one (worker fetches, service workers) took Mozilla's
// intl.accept_languages path and sent the prepared form: two different
// headers in one session, and only the second is what Firefox sends. The list
// is prepared here by the same Rust helper that prepares
// intl.accept_languages (Mozilla's static PrepareAcceptLanguages is those
// three lines: a null check, a string, the call), so a list sends exactly what
// Firefox sends for it. A single tag ("de-DE") prepares to itself.
//
// An override that prepares to an empty string gives an empty value, which
// nsHttpHeaderArray::SetHeader discards without adding a header.
inline nsAutoCString StealthPrepareAcceptLanguages(const char* aLanguages) {
  nsAutoCString prepared;
  if (!aLanguages) {
    return prepared;
  }
  const nsAutoCString languages(aLanguages);
  // Always NS_OK: rust_prepare_accept_languages has no failing path.
  nsresult rv = rust_prepare_accept_languages(&languages, &prepared);
  MOZ_ASSERT(NS_SUCCEEDED(rv));
  (void)rv;
  return prepared;
}

}  // namespace mozilla::net

#endif  // NETWERK_PROTOCOL_HTTP_STEALTHACCEPTLANGUAGE_H_
