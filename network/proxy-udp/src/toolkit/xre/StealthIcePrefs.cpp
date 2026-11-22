/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthIcePrefs.h"

#include "mozilla/Preferences.h"

namespace mozilla {

void StealthLockIcePrefs() {
  (void)Preferences::Lock("network.process.enabled");
  (void)Preferences::Lock("media.peerconnection.mtransport_process");
}

}  // namespace mozilla
