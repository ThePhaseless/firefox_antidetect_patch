/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// IsDebugger() in nsCertOverrideService.cpp answers true when a Juggler pipe
// is connected, so Browser.setIgnoreHTTPSErrors can flip the per-context
// switch of the certificate override service (a page cannot see this). The
// check is the first statement of IsDebugger, before the Marionette and Remote
// Agent lookups it is asked alongside. It is only built where Mozilla's own
// ENABLE_WEBDRIVER block is, so this header brings the gate in the same
// builds and nothing otherwise.

#ifndef STEALTH_IGNORE_HTTPS_ERRORS_H_
#define STEALTH_IGNORE_HTTPS_ERRORS_H_

#ifdef ENABLE_WEBDRIVER
#  include "StealthJugglerGate.h"
#endif

#endif  // STEALTH_IGNORE_HTTPS_ERRORS_H_
