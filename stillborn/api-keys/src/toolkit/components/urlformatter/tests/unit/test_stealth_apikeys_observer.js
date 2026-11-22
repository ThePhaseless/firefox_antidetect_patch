/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// A Safe Browsing key declared AFTER SafeBrowsing.init() turns the provider on:
// init() observes zoom.stealth.apikey, so the declaration is re-read. Without
// a declaration the provider stays off (updateURL empty).

const { SafeBrowsing } = ChromeUtils.importESModule(
  "resource://gre/modules/SafeBrowsing.sys.mjs"
);

const PREF_SB = "zoom.stealth.apikey.google_safebrowsing";

add_task(async function test_declaration_after_init_enables_the_provider() {
  Services.prefs.clearUserPref(PREF_SB);
  Services.prefs.setBoolPref("browser.safebrowsing.update.enabled", false);
  registerCleanupFunction(() => {
    Services.prefs.clearUserPref(PREF_SB);
    Services.prefs.clearUserPref("browser.safebrowsing.update.enabled");
    Services.prefs.clearUserPref("browser.safebrowsing.phishing.enabled");
  });

  SafeBrowsing.init();
  Assert.ok(SafeBrowsing.initialized, "SafeBrowsing is initialized");
  Assert.equal(
    SafeBrowsing.providers.google.updateURL,
    "",
    "Without a declaration the provider has no updateURL"
  );

  // Negative control: a pref change that re-reads the prefs (the observer of
  // Mozilla's) but declares nothing leaves the provider off.
  Services.prefs.setBoolPref("browser.safebrowsing.phishing.enabled", false);
  Assert.equal(SafeBrowsing.providers.google.updateURL, "");

  Services.prefs.setStringPref(PREF_SB, "CCC333");
  Assert.ok(
    SafeBrowsing.providers.google.updateURL.includes("CCC333"),
    "A declaration arriving after init() turns the provider on"
  );

  Services.prefs.clearUserPref(PREF_SB);
  Assert.equal(
    SafeBrowsing.providers.google.updateURL,
    "",
    "Removing the declaration turns the provider off again"
  );
});
