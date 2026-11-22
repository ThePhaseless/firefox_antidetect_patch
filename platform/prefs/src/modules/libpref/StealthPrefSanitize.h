/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef StealthPrefSanitize_h
#define StealthPrefSanitize_h

// True for the names of the prefs that Preferences.cpp must send to content
// processes even when they are dynamically named string prefs: the
// "zoom.stealth." family. Called from ShouldSanitizePreference.
bool StealthPrefAllowedInContent(const char* aPrefName);

#endif  // StealthPrefSanitize_h
