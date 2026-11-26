/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Included by nsUrlClassifierDBService.cpp right after the class nsUrlClassifierHashCompleterBase and its
// NS_IMPL_ISUPPORTS, which only that file sees: the definition of the getter that the interface
// nsIUrlClassifierHashCompleterCallback gained (userContextId), the context the completion was made in, handed on to the
// completer. Not a header of its own: it needs the class above it, and is included once.

NS_IMETHODIMP nsUrlClassifierHashCompleterBase::GetUserContextId(uint32_t* aId) {
  return mozilla::net::StealthLookupContextOut(mStealthUserContextId, aId);
}
