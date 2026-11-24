# fingerprint/locale-time/timezone

Category: spoof
Prefs: juggler.locale.override, juggler.timezone.override
Test: wrapper:tests/test_context_locale_e2e.py::test_a_context_locale_reaches_navigator_intl_and_the_header, wrapper:tests/test_a_launch_and_a_context_timezone_reach_the_page_e2e.py::test_a_launch_and_a_context_timezone_reach_the_page, wrapper:tests/test_bypass_csp_e2e.py::test_bypass_csp_lifts_the_page_policy_and_its_absence_keeps_it, gtest:StealthTimezone.LocalTimeIsTheDeclaredZonesWallClock, gtest:StealthTimezone.GMTParametersAreUTCWhateverIsDeclared, gtest:StealthTimezone.NothingDeclaredIsTheLocalTimeOfMozilla, gtest:StealthTimezone.AFieldWinsAndAnEmptyOneFallsToTheSession, gtest:StealthTimezone.NothingDeclaredAndAnEmptyFieldIsEmpty, gtest:StealthDocumentLanguage.WithNoContextTheSessionsLanguageIsTheDocumentsOne, node:juggler/tests/exslt_time_finds_the_source_document_as_the_file_does.test.mjs#ours finds the source document the way getSourceDocument does, and explodes in its zone

## What it does

Every realm, every worker, `document.lastModified` and EXSLT's `date:date-time()` read the time zone and the
language the session or the context declares, never the host's. The functions that read the declaration live
in `dom/base/StealthSessionDeclaration.{h,cpp}` (folder fingerprint/locale-time/session-declaration, the one
reader of the declaration, which also adds the functions these hooks call, G47); this folder only carries the hooks that call them, the EXSLT overload of `StealthExplodeTime` (`dom/xslt/xslt/StealthExsltTime.h`) and the tests of the calls.
The zone and the language of a top context are seeded in the parent from the session when the context
attaches, replaced per context when a client sets its own, and read by `BrowsingContext::DidSet` as the field
or, when the field is empty, the session's value (never the build's or the host's). Every realm takes its zone
at birth from its context and `DidSet` carries a change to the realms already alive; no block applies a zone
to every realm of a content process (one zone on every realm of a process would override a context's own).
When nothing is declared (the engine launched without the core) every caller keeps Firefox's own path.

## Hooks in Mozilla files

- `docshell/base/BrowsingContext.cpp`: `Attach` keeps Mozilla's body and signature; its last statement is the one-line hook `SeedDeclaredTimezoneAndLanguage(this);` (anchor at the end of the function, G30). `DidSet(LanguageOverride)` and `DidSet(TimezoneOverride)` wrap Mozilla's
  `GetLanguageOverride()` / `GetTimezoneOverride()` in `StealthLanguageOrSession` / `StealthTimezoneOrSession` (`IsTop()` holds, so
  the value is the field's or the session's). The realm's locale in `DidSet(LanguageOverride)` is Mozilla's call with the name changed and Mozilla's arguments in place:
  `StealthSetRealmLocaleOverride(realm, PromiseFlatCString(languageOverride).get())` in place of `JS::SetRealmLocaleOverride(`
  (`nullptr` for an empty override stays Mozilla's line). Ours is in namespace `mozilla::dom`; it takes the primary tag of the list (a realm's Intl
  locale is one BCP-47 tag, `navigator.languages` keeps the list), sets it with `JS::SetRealmLocaleOverride`, then refreshes the language of
  the realm's extant document: tag, Mozilla's set, refresh, in that order. Include in a block of ours.
- `dom/base/Document.cpp`, `Document.h`: `GetFormattedTimeString` (document.lastModified) takes the document as a parameter of ours
  (declared exception, G35) and calls `StealthExplodeTime(aDocument, aTime, <Mozilla's parameters>, &prtime)` in place of
  `PR_ExplodeTime`; its two callers pass `this` (G9). Mozilla's choice of `PR_GMTParameters` (resistFingerprinting asks UTC) or
  `PR_LocalTimeParameters` stays Mozilla's: with GMT it is `PR_ExplodeTime`, with local time it is the declared zone's wall clock
  (daylight saving included, computed with ICU; `tm_params` split into standard time and daylight saving as `PR_LocalTimeParameters`
  does, EXSLT prints their sum), or `PR_LocalTimeParameters` when nothing is declared. A zone ICU does not know is exploded as UTC,
  never as the host's. `SetContainer` has an anchor after `mInChromeDocShell = ...` (`StealthDocumentContainerSet`: when there is a
  container, the language of the document's text with no `lang` is computed again, because the context exists from then; a wrap
  of the function would run after `NotifyActivityChanged`). `RecomputeLanguageFromCharset` wraps Mozilla's initialiser of `language`:
  `nsAtom* language = StealthDocumentCharsetLanguage(this, mozilla::intl::EncodingToLang::Lookup(mCharacterSet));` (the language of text that declares none is its context's, not the process's). `Document.h` declares
  `friend class StealthDocumentAccess` (the one door to the private recompute). `InitCSP` keeps the early return
  `if (CSP_IsBypassedFor(*this)) return NS_OK;` (marker of automation/bypass-csp, function in dom/security): the CSP context set up
  before it stays even when the automation lifts the page's policies (history entries and a later `<meta>` expect one); what is
  skipped is every policy the page itself sends.
- `dom/xslt/xslt/txEXSLTFunctions.cpp`: Mozilla's `timezone` (UTC when `JSDateTimeUTC` is resisted, else local) is restored as in the tag;
  the call `StealthExplodeTime(aContext, time, timezone, &prtime)` replaces `PR_ExplodeTime`, and `aContext` is the parameter of Mozilla's `evaluate`, not a local.
  The overload for `txIEvalContext*` (`dom/xslt/xslt/StealthExsltTime.h`, included by one line of ours after the include of `StealthSessionDeclaration.h`) finds the source document of the
  transformation's execution state exactly as the file's `getSourceDocument` does and explodes in its zone, or as Mozilla's own call does when there is none.
  The page's local time is the declared zone's, not the C runtime's ([B339]).
- `js/xpconnect/src/nsXPConnect.cpp`: `xpc::InitGlobalObjectOptions` keeps Mozilla's body and signature; its last line is the one-line hook
  `mozilla::dom::SetDeclaredRealmTimeAndLanguage(...)` (anchor at the end of the function, G30): Mozilla's code (resistFingerprinting's spoofed values, else the
  override values) runs first, then the declared zone and the PRIMARY TAG of the language override (which may be an Accept-Language list) are set. With
  `aForceUTC` or `aLocaleEnUS` it does nothing. Every caller reaches the same symbol.
- `dom/base/test/gtest/moz.build`: one line registering `TestStealthTimezone.cpp`.

## Tests

- `TestStealthTimezone.cpp` (gtest, suite `StealthTimezone`): `StealthExplodeTime` with a declared Pacific/Chatham (21:13, offsets 12:45 + 1h) and
  Asia/Kolkata (12:58), with `PR_GMTParameters` (UTC whatever is declared), with nothing declared (Mozilla's local time); the field or the session in
  `StealthLanguageOrSession` / `StealthTimezoneOrSession`. Negative control: the declared-zone values differ from
  UTC and from the host's (no runner is in Chatham).
- wrapper e2e `test_a_launch_and_a_context_timezone_reach_the_page_e2e.py` (to write): browser launched with `timezone='Pacific/Chatham'`, a second
  context `new_context(timezone_id='Asia/Kolkata')`; in each page `Intl.DateTimeFormat().resolvedOptions().timeZone`, `new Date(2026, 9, 21)
  .getTimezoneOffset()`, `document.lastModified` of a page served with `Last-Modified: Wed, 21 Oct 2026 07:28:00 GMT` (10/21/2026 21:13:00 and
  12:58:00) and of a page with no header (the hour of the declared zone), EXSLT `date:date-time()` through `XSLTProcessor` (suffix +13:45 / +05:30)
  and a Worker's time zone. Negative control: a browser launched with no timezone gives the host's values, which differ from these on every runner.
- node test `juggler/tests/exslt_time_finds_the_source_document_as_the_file_does.test.mjs`: the hook line in `txEXSLTFunctions.cpp` passes `aContext` and nothing local; the lookup in `StealthExsltTime.h` has the steps of the file's `getSourceDocument` and explodes in the zone of that document (control: a lookup that goes elsewhere differs); the case of `date:date-time()` has already refused a context with no source document.
- wrapper e2e `test_context_locale_e2e.py` (exists): launch locale on the default context, `new_context(locale=...)`, workers.
- wrapper e2e `test_bypass_csp_e2e.py` (exists): CSP lifted and kept.
- gtest `StealthDocumentLanguage.*` (folder session-declaration): the function level of `StealthDocumentCharsetLanguage` and `ChooseCharsetLanguage`.
