/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The three API keys are declared through zoom.stealth.apikey.* prefs.

const { AppConstants } = ChromeUtils.importESModule(
  "resource://gre/modules/AppConstants.sys.mjs"
);

const PREF_MOZILLA = "zoom.stealth.apikey.mozilla";
const PREF_GEOLOC = "zoom.stealth.apikey.google_location_service";
const PREF_SB = "zoom.stealth.apikey.google_safebrowsing";

const MISSING_SB =
  "STEALTHFOX: no key declared in zoom.stealth.apikey.google_safebrowsing";

// What Mozilla's build writes into AppConstants when no key file is given. The
// declared key must replace it, so none of these may reach a formatted URL.
const BUILD_PLACEHOLDERS = [
  "no-mozilla-api-key",
  "no-google-location-service-api-key",
  "no-google-safebrowsing-api-key",
];

const ConsoleAPIStorage = Cc["@mozilla.org/consoleAPI-storage;1"].getService(
  Ci.nsIConsoleAPIStorage
);

// A module's console.error does not go to nsIConsoleService: Console.cpp
// records it (id "jsm") in nsIConsoleAPIStorage, which hands it to the log
// event listeners (ConsoleAPIStorage.sys.mjs, recordEvent). The first
// argument of the call is the message.
function listenToConsoleAPI(messages) {
  let listener = subject => {
    let event = subject.wrappedJSObject || subject;
    // never throw here: a listener that throws is reported with console.error, which comes back to this listener
    messages.push(String((event.arguments || [])[0]));
  };
  ConsoleAPIStorage.addLogEventListener(
    listener,
    Cc["@mozilla.org/systemprincipal;1"].createInstance(Ci.nsIPrincipal)
  );
  return () => ConsoleAPIStorage.removeLogEventListener(listener);
}

function formatKey(name) {
  return Services.urlFormatter.formatURL("http://x/?k=%" + name + "%");
}

function assertNoBuildPlaceholder(url) {
  for (let placeholder of BUILD_PLACEHOLDERS) {
    Assert.ok(!url.includes(placeholder), `${placeholder} is not in ${url}`);
  }
  for (let name of [
    "MOZ_MOZILLA_API_KEY",
    "MOZ_GOOGLE_LOCATION_SERVICE_API_KEY",
    "MOZ_GOOGLE_SAFEBROWSING_API_KEY",
  ]) {
    let built = AppConstants[name];
    if (built) {
      Assert.ok(!url.includes(built), `the build's ${name} is not in ${url}`);
    }
  }
}

function clearPrefs() {
  for (let pref of [PREF_MOZILLA, PREF_GEOLOC, PREF_SB]) {
    Services.prefs.clearUserPref(pref);
  }
}

add_task(async function test_no_declaration() {
  clearPrefs();
  let messages = [];
  let stop = listenToConsoleAPI(messages);
  try {
    Assert.equal(formatKey("GOOGLE_SAFEBROWSING_API_KEY"), "http://x/?k=");
    Assert.equal(formatKey("MOZILLA_API_KEY"), "http://x/?k=");
    Assert.equal(formatKey("GOOGLE_LOCATION_SERVICE_API_KEY"), "http://x/?k=");
  } finally {
    stop();
  }
  Assert.ok(
    messages.some(m => m.includes(MISSING_SB)),
    "A missing declaration is reported in the console (ConsoleAPIStorage)"
  );

  messages = [];
  stop = listenToConsoleAPI(messages);
  try {
    Assert.equal(Services.urlFormatter.trimSensitiveURLs("abc"), "abc");
  } finally {
    stop();
  }
  Assert.ok(
    !messages.some(m => m.includes("STEALTHFOX")),
    "trimSensitiveURLs does not log a missing declaration"
  );
});

add_task(async function test_declared_keys() {
  Services.prefs.setStringPref(PREF_MOZILLA, "AAA111");
  Services.prefs.setStringPref(PREF_GEOLOC, "BBB222");
  Services.prefs.setStringPref(PREF_SB, "CCC333");

  let messages = [];
  let stop = listenToConsoleAPI(messages);
  let urls;
  try {
    urls = [
      formatKey("MOZILLA_API_KEY"),
      formatKey("GOOGLE_LOCATION_SERVICE_API_KEY"),
      formatKey("GOOGLE_SAFEBROWSING_API_KEY"),
    ];
  } finally {
    stop();
  }
  Assert.deepEqual(
    urls,
    ["http://x/?k=AAA111", "http://x/?k=BBB222", "http://x/?k=CCC333"],
    "each URL carries the declared key"
  );
  for (let url of urls) {
    assertNoBuildPlaceholder(url);
  }
  Assert.ok(
    !messages.some(m => m.includes("STEALTHFOX")),
    "a declared key is not reported as missing"
  );

  Assert.equal(
    Services.urlFormatter.trimSensitiveURLs("u/BBB222/CCC333/BBB222"),
    "u/[trimmed-google-api-key]/[trimmed-google-api-key]/[trimmed-google-api-key]"
  );

  // The getters are lazy: a changed pref is seen by the next call.
  Services.prefs.setStringPref(PREF_SB, "DDD444");
  let changed = formatKey("GOOGLE_SAFEBROWSING_API_KEY");
  Assert.equal(changed, "http://x/?k=DDD444");
  assertNoBuildPlaceholder(changed);

  clearPrefs();
});
