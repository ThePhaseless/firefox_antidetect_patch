/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* STEALTH-HOOK(fingerprint/webrtc/declared-network)
 *
 * The interfaces WebRTC gathers on are declared, never read from the host (nr_stealth_network.h). The mtransport unit
 * tests (ice_unittest, transport_unittests, turn_unittest, ...) gather on a declared adapter, as the browser does:
 * MtransportTest::SetUp (gtest_utils.h) calls this first, and STEALTHFOX_WEBRTC_NETWORK is set to a one-adapter
 * declaration when the environment has none. The variable is read when the interfaces are enumerated (nr_stun_get_addrs),
 * long after SetUp, and nothing that SetUp does before the declaration reads it. Without a declaration there is no
 * interface and the tests gather nothing. */

#ifndef nr_stealth_test_network_h__
#define nr_stealth_test_network_h__

#include <stdlib.h>

inline void StealthDeclareTestNetwork() {
  const char* declared = getenv("STEALTHFOX_WEBRTC_NETWORK");
  if (!declared || !*declared) {
    setenv("STEALTHFOX_WEBRTC_NETWORK", "v4=192.168.10.20;v6=0;p6=", 1);
  }
}

#endif  // nr_stealth_test_network_h__
