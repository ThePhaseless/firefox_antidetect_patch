/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthGeolocation_h
#define mozilla_StealthGeolocation_h

#include <stdint.h>

#include "nsCOMPtr.h"
#include "nsIGeolocationProvider.h"

namespace mozilla {

namespace dom {
enum class PermissionName : uint8_t;
}  // namespace dom

/**
 * The position a page reads comes only from the core's declaration (the
 * geolocation override of Browser.setGeolocationOverride). The engine never
 * asks the host for a location, so no provider that reads the host is ever
 * created. The Windows provider's files no longer exist (it started the
 * WINDOWS_UTILS utility process and loaded the WinRT geolocation modules), so on
 * Windows there is nothing to select away; this hook only keeps Portal, GeoClue,
 * CoreLocation and Android out, and the MLS provider that a pref could ask for.
 *
 * StealthGeolocationProviderContract is the contract of the provider every
 * process uses: the network provider (NetworkGeolocationProvider.sys.mjs).
 * With no network URL declared and no Wi-Fi scan it asks nobody and answers
 * POSITION_UNAVAILABLE.
 */
const char* StealthGeolocationProviderContract();

/**
 * GeolocationService::Init(), after the shutdown observer and before Mozilla
 * picks a provider: aProvider becomes the provider of the contract above and
 * the answer is true (Init() is done). Pure of prefs: no pref brings a host
 * provider back.
 */
bool StealthSelectGeolocationProvider(
    nsCOMPtr<nsIGeolocationProvider>& aProvider);

/**
 * The persona is a Windows machine whose system location is declared ON. The OS
 * privacy switch is read nowhere: GetGeolocationPermissionBehavior
 * (GeolocationSystemWin.cpp) answers "no prompt, permitted" from this
 * declaration instead of asking AppCapability("location") (which loads
 * capabilityaccessmanagerclient.dll and, with the switch off on the host,
 * cancelled the request with PERMISSION_DENIED).
 */
bool StealthSystemLocationDeclaredOn();

/**
 * First statement of the parent-side monitor entry of PermissionObserver: true
 * for the geolocation permission, whose OS state is the declared switch above
 * and never changes, so no OS monitor is started for it (the early return is the
 * caller's). Every other permission keeps its monitor.
 */
bool StealthSkipsPermissionMonitor(dom::PermissionName aName);

}  // namespace mozilla

#endif  // mozilla_StealthGeolocation_h
