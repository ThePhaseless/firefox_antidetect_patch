/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The branding a page reads comes from the archive invisible_core declares,
// zoom.stealth.branding.archive (a file: URI of a zip), and the chrome registry
// serves it as jar:<archive>!/<file> whenever a chrome://branding/content/ URL is
// resolved (nsChromeRegistry::ConvertChromeURL ends in StealthBrandingChromeURL,
// netwerk/protocol/res/StealthBranding.cpp). The registry knows where the
// branding directory is from the package the build registers
// (nsChromeRegistryChrome::ManifestContent -> StealthBrandingRegisterPackage), so
// this test needs the packaged binary: the branding package must be registered by
// the package's own omni.ja, which `firefox -xpcshell -a <gre>/browser` loads
// (firefox-appdir in the manifest). A binary that registers no branding package
// fails here, it is not skipped.
//
// No case opens a chrome URL that does not exist: in automation that is a crash by
// design (nsNetUtil.cpp, the check under xpc::IsInAutomation() that does
// MOZ_CRASH_UNSAFE_PRINTF("Missing chrome or resource URLs") kills the process), so
// the declared file shadows one the build ships and the engine-off read finds it.
//
// The engine is on with zoom.stealth.fpp.hw_seed > 0. Only a complete declaration
// is tried with it on: an incomplete one with the engine on refuses the launch
// (StealthAssertDeclarationsComplete), which would end the shell.

"use strict";

const { NetUtil } = ChromeUtils.importESModule(
  "resource://gre/modules/NetUtil.sys.mjs"
);

const SEED_PREF = "zoom.stealth.fpp.hw_seed";
const ARCHIVE_PREF = "zoom.stealth.branding.archive";

// The declared archive holds a file with the SAME NAME as one the build's branding
// ships under chrome://branding/content/: aboutDialog.css, listed in
// browser/branding/unofficial/content/jar.mn (the branding the CI build uses: its
// .mozconfig names no --with-branding, so browser/confvars.sh's
// MOZ_BRANDING_DIRECTORY=browser/branding/unofficial applies; official/ has the
// same file). Its bytes are a text marker, never the real stylesheet's.
const BRANDING_FILE = "aboutDialog.css";
const BRANDING_TEXT = "/* the branding this test declared */";
const BRANDING_URL = "chrome://branding/content/" + BRANDING_FILE;
// A package no build registers: the undeclared variant of the branding package.
const UNDECLARED_URL =
  "chrome://branding-undeclared/content/" + BRANDING_FILE;
// A package the redirect must leave alone.
const OTHER_PACKAGE_URL = "chrome://global/content/mozilla.xhtml";

const PR_RDWR = 0x04;
const PR_CREATE_FILE = 0x08;
const PR_TRUNCATE = 0x20;

let gArchiveSpec = null;

const registry = Cc["@mozilla.org/chrome/chrome-registry;1"].getService(
  Ci.nsIChromeRegistry
);

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

function resolve(url) {
  return registry.convertChromeURL(Services.io.newURI(url)).spec;
}

function resolveFails(url) {
  try {
    registry.convertChromeURL(Services.io.newURI(url));
  } catch (e) {
    return e.result;
  }
  return null;
}

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

add_setup(function () {
  do_get_profile();
  registerCleanupFunction(engineOff);
});

add_task(async function test_chrome_registry_serves_the_declared_branding_jar() {
  const expected = Services.io.newURI(
    "jar:" + declaredArchive() + "!/" + BRANDING_FILE
  ).spec;

  // Engine off is stock Firefox: the build's own branding, which is not the
  // declared jar. This also proves that the package registers a branding
  // package at all (a binary that does not fails on the throw, it does not skip).
  const stock = resolve(BRANDING_URL);
  Assert.notEqual(stock, expected, "engine off: the build's own branding");
  Assert.ok(
    !stock.startsWith("jar:" + declaredArchive()),
    "engine off: nothing is served from the declared archive"
  );

  const served = withEngine(() => resolve(BRANDING_URL));
  Assert.equal(
    served,
    expected,
    "engine on: chrome://branding/content/ is served from the declared jar"
  );
  Assert.notEqual(served, stock, "engine on differs from the build");

  // And back to the build's own once the engine is off again.
  Assert.equal(resolve(BRANDING_URL), stock, "engine off again: the build's");
});

add_task(async function test_declared_jar_is_what_a_chrome_load_reads() {
  // The same URL, loaded: engine on, the declared file's bytes.
  const text = withEngine(() => readChrome(BRANDING_URL));
  Assert.equal(text, BRANDING_TEXT, "the bytes come from the declared archive");

  // Engine off: the same URL opens the build's own file, whose bytes are not the
  // declared ones (nothing is asserted on them beyond that).
  const stock = readChrome(BRANDING_URL);
  Assert.greater(
    stock.length,
    0,
    "engine off: the build's own file is not empty"
  );
  Assert.notEqual(stock, BRANDING_TEXT, "engine off: not the declared bytes");
});

add_task(async function test_an_undeclared_package_is_not_resolved() {
  // The negative case: a branding variant that was never declared nor
  // registered must not resolve, with the engine off and with it on and the
  // archive declared (the declaration is for the package named "branding" only).
  Assert.equal(
    resolveFails(UNDECLARED_URL),
    Cr.NS_ERROR_FILE_NOT_FOUND,
    "engine off: no such package"
  );
  withEngine(() => {
    Assert.equal(
      resolveFails(UNDECLARED_URL),
      Cr.NS_ERROR_FILE_NOT_FOUND,
      "engine on, archive declared: an undeclared package is not served from it"
    );
  });

  // Nor does the declared archive reach another package: its URL resolves as it
  // does with the engine off.
  const stock = resolve(OTHER_PACKAGE_URL);
  const other = withEngine(() => resolve(OTHER_PACKAGE_URL));
  Assert.equal(other, stock, "another package is not redirected");
  Assert.ok(
    !other.startsWith("jar:" + declaredArchive()),
    "another package is not served from the declared archive"
  );
});
