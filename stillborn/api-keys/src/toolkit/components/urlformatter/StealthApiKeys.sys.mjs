/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/**
 * STEALTHFOX: the three API keys are DECLARED by the core, not by the build.
 *
 * Upstream burned them in at compile time: configure read three keyfiles and
 * substituted @MOZ_..._API_KEY@ inside AppConstants.sys.mjs, which at runtime is
 * a frozen constant. That path is still there, as in the tag: the three entries
 * of AppConstants.sys.mjs and the three DEFINES of toolkit/modules/moz.build
 * exist, and the build fills them with the "no-...-api-key" placeholders. But
 * the engine never reads those constants: a copy compiled into the engine would
 * be a second source of truth, two numbers for the same thing, which diverge
 * silently the day one of them changes. StealthApplyApiKeys writes the
 * declaration OVER the three Mozilla getters, which are never called.
 *
 * Now the value lives in ONE place, the core, and arrives as a pref. The domain
 * is finite and known - three keys - so engine rule 2 is satisfied.
 *
 * AND THE ABSENCE IS REFUSED, not replaced. Without a declaration this function
 * returns the EMPTY string, which is exactly what the engine already knows how
 * to handle: SafeBrowsing.checkGoogleSafeBrowsingKey reads it as falsy and turns
 * the provider off, so the request does not go out at all. Returning the
 * PLACEHOLDER would have been worse than the defect: "%GOOGLE_SAFEBROWSING_API_KEY%"
 * is a non-empty string different from the sentinel, so that check would have
 * passed and Firefox would have sent a URL with the placeholder inside.
 *
 * The console error is deliberate: a missing declaration must be loud, because
 * the way this mechanism goes wrong is by staying silent.
 */
// THE NAMES ARE WHOLE LITERALS, AND IT IS NOT A STYLE: IT IS A GATE.
// The first version built the name (`"zoom.stealth.apikey." + name`) and the
// core's `test_every_stealth_pref_emitted_is_one_the_binary_reads` rejected it
// for the right reason: that gate looks for every `zoom.stealth.*` pref that the
// core EMITS inside the engine source, because a name that the binary never
// reads is a spoof that silently does nothing, and from Python the two cases are
// indistinguishable. Four had already shipped like that. A built name is
// invisible to that gate and to anyone who runs a grep. Each literal appears
// ONCE, here.
const PREF_APIKEY_MOZILLA = "zoom.stealth.apikey.mozilla";
const PREF_APIKEY_GOOGLE_LOCATION =
  "zoom.stealth.apikey.google_location_service";
const PREF_APIKEY_GOOGLE_SAFEBROWSING =
  "zoom.stealth.apikey.google_safebrowsing";

function readKeySilently(pref) {
  // The ONLY place in the engine that READS one of these prefs. The two callers
  // (the formatURL getters and the log redaction) go through here: if the
  // read were written twice, the day the redaction changes it would stop
  // cleaning with nothing to say so, and the key would end up in the logs in
  // clear.
  return Services.prefs.getStringPref(pref, "");
}

function stealthDeclaredApiKey(pref) {
  const value = readKeySilently(pref);
  if (!value) {
    console.error(
      "STEALTHFOX: no key declared in " +
        pref +
        " - the request that uses it will not go out."
    );
  }
  return value;
}

// STEALTHFOX: declared by the core, not burned into the build.
// The getters stay lazy: the pref is read at every formatURL, not at load time.
// StealthApplyApiKeys, at the bottom of URLFormatter.sys.mjs, writes them OVER
// the three Mozilla getters, which stay as Mozilla wrote them and read entries
// of AppConstants that the build fills with the "no-...-api-key" placeholders:
// they are never called.
function stealthApiKeyGetters() {
  return {
    MOZILLA_API_KEY: () => stealthDeclaredApiKey(PREF_APIKEY_MOZILLA),
    GOOGLE_LOCATION_SERVICE_API_KEY: () =>
      stealthDeclaredApiKey(PREF_APIKEY_GOOGLE_LOCATION),
    GOOGLE_SAFEBROWSING_API_KEY: () =>
      stealthDeclaredApiKey(PREF_APIKEY_GOOGLE_SAFEBROWSING),
  };
}

// STEALTHFOX: reads the same DECLARATIONS as the getters above, no longer the
// constants of AppConstants. Called at the top of trimSensitiveURLs: the Mozilla
// code that follows stays as it is and sees only the "no-...-api-key"
// placeholders, which never appear in a message, so it leaves the message
// intact. If it read a source different from the one that built the URL, this
// redaction would miss the target: it is exactly the defect of the two sources
// of truth, here in the form of a key that ends up in the logs in clear. It goes
// through readKeySilently, which does NOT log the error to the console: this is
// the log path, and a log that complains while it cleans another log is noise,
// not a signal.
export function StealthTrimApiKeys(aMsg) {
  const geoloc = readKeySilently(PREF_APIKEY_GOOGLE_LOCATION);
  const sb = readKeySilently(PREF_APIKEY_GOOGLE_SAFEBROWSING);
  aMsg = geoloc
    ? aMsg.replace(RegExp(geoloc, "g"), "[trimmed-google-api-key]")
    : aMsg;
  return sb
    ? aMsg.replace(RegExp(sb, "g"), "[trimmed-google-api-key]")
    : aMsg;
}

// Called at the bottom of URLFormatter.sys.mjs, after the definition of
// nsURLFormatterService.prototype: it writes the three getters over Mozilla's.
export function StealthApplyApiKeys(aFormatterPrototype) {
  Object.assign(aFormatterPrototype._defaults, stealthApiKeyGetters());
}

// STEALTHFOX: SafeBrowsing.init() runs at startup, but on the Playwright path
// the core's prefs arrive after the launch (Browser.enable applies them with
// the engine already running). Without this observer the late declaration of
// the Safe Browsing key would never be read again and the provider would stay
// off forever with the key present: silent and permanent. The observed name is
// a branch, not a single key: observe() falls on readPrefs(), which at the end
// redoes controlUpdateChecking() and therefore updateProviderURLs() ->
// checkGoogleSafeBrowsingKey(), and the key is read again from whatever channel
// it arrives by. The literal stays whole (it is a gate, see above).
export function StealthObserveApiKey(aSafeBrowsing) {
  Services.prefs.addObserver("zoom.stealth.apikey", aSafeBrowsing);
}
