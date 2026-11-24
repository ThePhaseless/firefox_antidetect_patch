/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthIcePrefs_h
#define mozilla_StealthIcePrefs_h

namespace mozilla {

/**
 * The two prefs that decide WHERE a PeerConnection's ICE runs are locked to the value Mozilla gives them, once, at startup: the
 * SOCKS5 UDP layer lives in the socket process (NrSocket::create), so no caller may move the ICE out of it. A locked pref reads its
 * default whatever user.js, prefs.js or a caller wrote. Called by XREMain::XRE_mainRun right after the user prefs are loaded.
 *
 *   network.process.enabled                    false would be no socket process
 *   media.peerconnection.mtransport_process    false would be the ICE in the content process
 */
void StealthLockIcePrefs();

}  // namespace mozilla

#endif  // mozilla_StealthIcePrefs_h
