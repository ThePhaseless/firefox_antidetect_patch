/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// TEMPORARY probe for the crash of test_stealth_branding_chrome_registry.js (xpcshell leg, candidate 45060573559): delete when the cause is found.
//
// Probe A: engine never on; a missing file of chrome://global/.

"use strict";

const { NetUtil } = ChromeUtils.importESModule(
  "resource://gre/modules/NetUtil.sys.mjs"
);

function readChrome(url) {
  const channel = NetUtil.newChannel({
    uri: url,
    loadUsingSystemPrincipal: true,
  });
  const stream = channel.open();
  try {
    return NetUtil.readInputStreamToString(stream, stream.available());
  } finally {
    stream.close();
  }
}

const MISSING_URL = "chrome://global/content/non-esiste.txt";

add_task(async function test_probe_a_global_missing_open_throws() {
  // A profile, as the branding test has (its add_setup): the probes differ from it only where they mean to.
  do_get_profile();
  // The engine is never on in this process (zoom.stealth.fpp.hw_seed is not
  // touched). The synchronous open of a file the package does not have must throw.
  let failed = false;
  try {
    readChrome(MISSING_URL);
  } catch (e) {
    failed = true;
  }
  Assert.ok(failed, MISSING_URL + " does not exist: the synchronous open throws");
});
