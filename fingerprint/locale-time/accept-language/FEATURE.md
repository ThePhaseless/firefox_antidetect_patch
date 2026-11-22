# fingerprint/locale-time/accept-language

Category: other, spoof
Prefs: intl.accept_languages
Test: wrapper:tests/test_accept_language_on_the_wire_e2e.py::test_every_request_of_a_session_carries_the_retail_accept_language (raw Accept-Language header on a local socket, every request kind; also wrapper:tests/test_context_locale_e2e.py for the context locale)

## What it does

The `Accept-Language` a request carries when its BrowsingContext has a `languageOverride`. The override is a language LIST, not one tag: `juggler.locale.override` seeds the field with the same list the core writes to `intl.accept_languages` ("it-IT, it, en-US, en"), because `navigator.languages` is split from it. Copied as it was, the list went out raw (spaces, no q-values) on every request that has a BrowsingContext, while requests without one (worker fetches, service workers) took Mozilla's `intl.accept_languages` path and sent the prepared form: two different headers in one session, and only the second is what Firefox sends. The override is now prepared by the same Rust helper that prepares `intl.accept_languages`, so a list sends exactly what Firefox sends for it; a single tag ("de-DE") prepares to itself. An override that prepares to an empty string sets no header (`nsHttpHeaderArray::SetHeader` discards an empty value).

## Hooks in Mozilla files

All in `netwerk/protocol/http/nsHttpHandler.cpp`; own code in `netwerk/protocol/http/StealthAcceptLanguage.h` (header only, `mozilla::net::StealthPrepareAcceptLanguages(const char*)`, returns an `nsAutoCString`; it is the three lines of Mozilla's file-static `PrepareAcceptLanguages`: a null check, a string, the call to `rust_prepare_accept_languages` of `mozilla/net/rust_helper.h`; the e2e catches a drift).

- registration: `#include "StealthAcceptLanguage.h"` in our block after Mozilla's includes.
- wrap-expression, `nsHttpHandler::AddStandardRequestHeaders`: `acceptLanguage.Assign(StealthPrepareAcceptLanguages(aLanguageOverride.get()));` in Mozilla's `if (!aLanguageOverride.IsEmpty())` branch. Mozilla's `SetHeader(nsHttp::Accept_Language, ...)` and `if (NS_FAILED(rv)) return rv;` are as in the tag, so the header keeps its position on the wire (after Accept, before Prefer). The static `PrepareAcceptLanguages` of Mozilla is no longer declared in front of the function.

There is no mochitest: the one that used to live in `netwerk/test/browser/` (and its line in `browser.toml`) left the series, because no round runs mochitests; the wrapper e2e proves the same on the wire.
