/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthPrefSanitize.h"

#include <string.h>

// A pref named "zoom.stealth.*" is never sanitized. Mozilla's list of
// dynamically named string prefs that may reach web content processes
// (sDynamicPrefOverrideList) held this prefix as an unconditional entry, and
// no other branch of ShouldSanitizePreference() can return true for such a
// name: it is not a "$$$" pref, no entry of sRestrictFromWebContentProcesses
// is a prefix of it, and the dynamic-string branch answers false through the
// override entry. So answering false here is the same answer for every pref.
// The prefix is matched with the length of the entry, as the list does.
bool StealthPrefAllowedInContent(const char* aPrefName) {
  static const char kPrefix[] = "zoom.stealth.";
  return strncmp(aPrefName, kPrefix, sizeof(kPrefix) - 1) == 0;
}
