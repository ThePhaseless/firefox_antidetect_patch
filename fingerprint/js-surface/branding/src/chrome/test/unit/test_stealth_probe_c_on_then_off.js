/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// TEMPORARY probe for the crash of test_stealth_branding_chrome_registry.js (xpcshell leg, candidate 45060573559): delete when the cause is found.
//
// Probe C: the branding test's second task alone: engine on with the declared
// archive and the bytes read, then the engine off and the synchronous open of a
// file the build's branding does not have (it must throw).

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

const SEED_PREF = "zoom.stealth.fpp.hw_seed";
const ARCHIVE_PREF = "zoom.stealth.branding.archive";

const BRANDING_FILE = "stealth-declared-brand.txt";
const BRANDING_TEXT = "the branding this test declared";
const BRANDING_URL = "chrome://branding/content/" + BRANDING_FILE;
const MISSING_URL = "chrome://branding/content/non-esiste.txt";

const PR_RDWR = 0x04;
const PR_CREATE_FILE = 0x08;
const PR_TRUNCATE = 0x20;

let gArchiveSpec = null;

// The declared archive: a zip with one file at its root, in the profile of the
// test (the declaration is a file: URI of a regular file).
function declaredArchive() {
  if (gArchiveSpec) {
    return gArchiveSpec;
  }
  const file = do_get_profile();
  file.append("stealth-declared-brand.zip");
  const writer = Cc["@mozilla.org/zipwriter;1"].createInstance(
    Ci.nsIZipWriter
  );
  writer.open(file, PR_RDWR | PR_CREATE_FILE | PR_TRUNCATE);
  const stream = Cc["@mozilla.org/io/string-input-stream;1"].createInstance(
    Ci.nsIStringInputStream
  );
  stream.setUTF8Data(BRANDING_TEXT);
  writer.addEntryStream(
    BRANDING_FILE,
    Date.now() * 1000,
    Ci.nsIZipWriter.COMPRESSION_NONE,
    stream,
    false
  );
  writer.close();
  gArchiveSpec = Services.io.newFileURI(file).spec;
  return gArchiveSpec;
}

function engineOff() {
  Services.prefs.clearUserPref(SEED_PREF);
  Services.prefs.clearUserPref(ARCHIVE_PREF);
}

// The engine on with the archive declared, for the time of `body`; stock
// Firefox again after it, whatever `body` did.
function withEngine(body) {
  Services.prefs.setIntPref(SEED_PREF, 7);
  Services.prefs.setStringPref(ARCHIVE_PREF, declaredArchive());
  try {
    return body();
  } finally {
    engineOff();
  }
}

registerCleanupFunction(engineOff);

add_task(async function test_probe_c_on_then_off_missing_open_throws() {
  do_get_profile();

  const text = withEngine(() => readChrome(BRANDING_URL));
  Assert.equal(text, BRANDING_TEXT, "the bytes come from the declared archive");

  // Engine off again, then a file the build's branding does not have.
  let failed = false;
  try {
    readChrome(MISSING_URL);
  } catch (e) {
    failed = true;
  }
  Assert.ok(failed, MISSING_URL + " does not exist: the synchronous open throws");
});
