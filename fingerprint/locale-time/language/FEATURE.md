# fingerprint/locale-time/language

Category: build, other, spoof
Prefs: none read directly (the language comes from `juggler.locale.override` through `intl::SessionLanguageTag`, in `fingerprint/locale-time/session-declaration`)
Test: `Intl_Locale_StealthSystemLocales.TheDeclaredLanguageIsTheRegionalLanguage`, `.ADeclaredLanguageOfAnotherLanguageKeepsTheAppLocales`, `.WithTheOSLocalesPreferenceTheDeclaredLanguageIsTheOnlyOne` (gtest, `intl/locale/tests/gtest/TestStealthRegionalLocales.cpp`); `Intl_Locale_StealthSystemLocales.AWorkerThreadKeepsItsOwnDeclaredLanguage` (gtest of session-declaration); wrapper e2e `tests/test_context_locale_e2e.py::test_an_offscreen_canvas_of_a_worker_draws_with_the_language_group_of_its_context` and `::test_text_without_lang_takes_the_language_group_of_the_session_language` (to write)

## What it does

The language the session declares is the language of "the machine" for the two process-wide questions that have no context to ask: the regional locales (`LocaleService::GetRegionalPrefsLocales`, which feed the web-exposed locales, the date and time inputs and `AppDateTimeFormat`) and the language of text that declares none (`nsLanguageAtomService::GetLocaleLanguage`, which picks the font language group of a canvas without `lang`, of `nsFontCache` and of `EncodingToLang`). Both asked the host's `OSPreferences`, so a page measured the machine.

Only the input changes. The rule of `GetRegionalPrefsLocales` stays Mozilla's: the regional language is used only when it matches the app locale (a real en-US build on a de-DE machine formats as en-US), so a declared `ja-JP` in an en-US build leaves the app locales. When nothing is declared (the engine launched without the core) every caller keeps Firefox's own path.

The atom is one per process, cached under `mLock` at the first call; a worker thread asks first for the language its realm carries (`WorkerLocaleLanguage`, a thread-local set at the birth of the realm), so an OffscreenCanvas in a worker of a context with its own language draws with that context's language group. A second context with its own language keeps the session's language for the main thread's layout and canvas.

The logic is in `intl/locale/StealthSessionPrefs.cpp` (folder `fingerprint/locale-time/session-declaration`): `MachineRegionalPrefsLocales` (the declared tag as the only entry, else the OS), `SessionLocaleLanguage` (the declared tag as a lowercase atom, else null), `WorkerLocaleLanguage`.

## Hooks in Mozilla files

- `intl/locale/nsLanguageAtomService.cpp`: registration, an include of `StealthSessionPrefs.h` in a block of ours after Mozilla's includes; guard, first statement of `GetLocaleLanguage`: `if (nsAtom* worker = intl::WorkerLocaleLanguage()) return worker;` (the name has no `Stealth` prefix because the gtests of session-declaration call it, G41; the guard has an initializer because the result is the return value); anchor, inside `if (!mLocaleLanguage) {` before the OS lookup: `if ((mLocaleLanguage = intl::SessionLocaleLanguage())) return mLocaleLanguage;` (row `moved`, left as today; target: restore, the guard in `OSPreferences` below covers it).
- `intl/locale/LocaleService.cpp`: the include of `StealthSessionPrefs.h` and the two calls of `GetRegionalPrefsLocales` rewritten to `MachineRegionalPrefsLocales` (rows `moved`, left as today; target: the four Mozilla lines restored and a guard `if (StealthRegionalPrefsLocales(aRetVal)) return NS_OK;` at the top of `OSPreferences::GetRegionalPrefsLocales`, only with the list of all callers of G31).
- `intl/locale/moz.build`: registration of `StealthSessionPrefs.h` and `StealthSessionPrefs.cpp` (marker of session-declaration, which owns the files).
- `intl/locale/tests/gtest/moz.build`: registration of `TestStealthRegionalLocales.cpp`.

## Tests

`TestStealthRegionalLocales.cpp` goes through `LocaleService::GetRegionalPrefsLocales`, the entry every caller uses: a declared `en-TT, en, en-US` is the only regional locale (the control with nothing declared is not `en-TT`); a declared `ja-JP` leaves the app locales (Mozilla's rule); with `intl.regional_prefs.use_os_locales` the declared `ja-JP` is the only locale (control: not `ja-JP` with nothing declared). The atom of the first call is not tested in-process: the service caches it for the life of the process.

The gtest passes an empty list to `GetRegionalPrefsLocales` (Mozilla's function wants one) and leaves no state in the process: nothing it declares or caches outlives a test.
