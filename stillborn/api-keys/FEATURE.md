# stillborn/api-keys

Category: build, other
Prefs: zoom.stealth.apikey, zoom.stealth.apikey.google_location_service, zoom.stealth.apikey.google_safebrowsing, zoom.stealth.apikey.mozilla
Test: toolkit/components/urlformatter/tests/unit/test_stealth_apikeys.js, toolkit/components/urlformatter/tests/unit/test_stealth_apikeys_observer.js

## What it does

The three API keys (Safe Browsing, Google location service, Mozilla) are not engraved in the build: invisible_core declares them as the prefs `zoom.stealth.apikey.*`. `URLFormatter` reads them from the prefs for `%GOOGLE_SAFEBROWSING_API_KEY%`, `%GOOGLE_LOCATION_SERVICE_API_KEY%` and `%MOZILLA_API_KEY%` (a missing declaration gives an empty string and a console error, so the request that needs the key is never sent) and strips them from logs in `trimSensitiveURLs`. `SafeBrowsing` observes `zoom.stealth.apikey`, so a declaration that arrives after `SafeBrowsing.init()` (the normal case on the Playwright path: `Browser.enable` applies the core's prefs after launch) is re-read and the provider turns on.

Mozilla's `AppConstants.sys.mjs` and `toolkit/modules/moz.build` are exactly as in the tag. The build fills the three constants with the `no-...-api-key` placeholders of `keyfiles.configure` (the `.mozconfig` must not pass any `--with-*-api-keyfile`); no reader of the tree uses them except Mozilla's own getters and redaction in `URLFormatter.sys.mjs`, which our code overwrites (the getters) or runs before (the redaction), see below. The placeholders never appear in a message, so Mozilla's redaction after ours leaves the message as ours returned it.

## Hooks in Mozilla files

- `toolkit/components/url-classifier/SafeBrowsing.sys.mjs`: an import of `StealthObserveApiKey` (registration) and, in `SafeBrowsing.init()`, anchor `StealthObserveApiKey(this);` right after the `addObserver("urlclassifier", this)` statement, at the place where the literal observer sat before. `addObserver` of `zoom.stealth.apikey` runs before `readPrefs()`, as before. Why the observed name is a branch: `observe()` falls on `readPrefs()`, which ends with `controlUpdateChecking()` and so `updateProviderURLs()` -> `checkGoogleSafeBrowsingKey()`; the key is re-read and the provider turns on whenever the declaration arrives. Not moved to the head of `init()` (before the "Already initialized" return): not proven equal in every case (G28).
- `toolkit/components/urlformatter/URLFormatter.sys.mjs`: an import of `StealthApplyApiKeys` and `StealthTrimApiKeys` (registration); in `trimSensitiveURLs`, as the first line of the function, `aMsg = StealthTrimApiKeys(aMsg);` (a pure addition, as on the base: our redaction runs first, Mozilla's body then works on the result); and, as the last line of the module, the call `StealthApplyApiKeys(nsURLFormatterService.prototype);` (G33: it must run after the prototype is defined), which writes our three getters over Mozilla's in `_defaults`. The prototype's methods are not replaced.
- `toolkit/components/urlformatter/moz.build`: `EXTRA_JS_MODULES += ["StealthApiKeys.sys.mjs"]` and `XPCSHELL_TESTS_MANIFESTS += ["tests/unit/xpcshell-stealth.toml"]`, after Mozilla's lists.

The three pref names are whole literals in `StealthApiKeys.sys.mjs`, once each, on purpose: the core's gate greps the engine source for every `zoom.stealth.*` it emits. The test `test_stealth_apikeys.js` moved from Mozilla's `xpcshell.toml` into our manifest `tests/unit/xpcshell-stealth.toml`, with the same head and skip.

## Test

- `tests/unit/test_stealth_apikeys.js`: no declaration gives empty strings and a console error (and `trimSensitiveURLs` leaves the message intact and silent); declared keys are formatted, redacted from logs, and re-read at every call.
- `tests/unit/test_stealth_apikeys_observer.js`: `SafeBrowsing.init()` without a key leaves the `google` provider without `updateURL`; an unrelated re-read of the prefs leaves it off; declaring the key after `init()` turns it on (red without the observer); removing it turns it off. Both run only in a `firefox -xpcshell` leg of a round (none yet: G20).
