# fingerprint/locale-time/session-declaration

Category: build
Prefs: juggler.locale.override (read by our functions, not by a hook line)
Test: gtest:Intl_Locale_StealthSystemLocales.* (intl/locale/tests/gtest/TestStealthSystemLocales.cpp; the negative controls are NothingDeclaredIsMozillasPath, WithoutADeclarationTheSystemAnswers and TheFirstOfTheDeclaredListAsOneTag: with nothing declared Mozilla's path answers) and gtest:StealthDocumentLanguage.* (dom/base/test/gtest/TestStealthDocumentLanguage.cpp). The suite Intl_Locale_StealthSystemLocales and StealthDocumentLanguage must be in the gtest_filter of release.yml (G20, G42).

## What it does

The languages of "the machine" (`OSPreferences::GetSystemLocales`, `GetSystemLocale`) are the session's declaration (`juggler.locale.override`), not the operating system's; they are empty only when the engine starts without the core, and then Mozilla's own path answers. The declared list is the list of the machine: tags in order, without a bare language that a regional tag of the same language already stands for, without q-values, without repeats. The same declaration gives the realm's language and time zone and the document language (dom/base/StealthSessionDeclaration.*, hooked from fingerprint/screen-window/geometry's files, which carry this folder's marker).

## Hooks in Mozilla files

- `dom/base/moz.build`: registration, after the closing `]` of EXPORTS.mozilla.dom (StealthSessionDeclaration.h) and after the closing `]` of UNIFIED_SOURCES (StealthSessionDeclaration.cpp). StealthDeclarationGate.h/.cpp are registered in gfx/thebes/moz.build, so nothing is missing here.
- `intl/locale/OSPreferences.cpp`: registration, `#include "mozilla/intl/StealthSessionPrefs.h"` in a block of ours after Mozilla's includes; guard, first statement of `OSPreferences::GetSystemLocales`: `if (SessionSystemLocales(aRetVal)) return NS_OK;`; guard, first statement of `OSPreferences::GetSystemLocale`: `if (SessionSystemLocale(aRetVal)) return NS_OK;`. The two functions keep their names (G41: the existing gtest calls them). SessionSystemLocales / SessionSystemLocale answer true with the declared list (or its first tag) and false when nothing is declared; on true the host's list and the cache of mSystemLocales are never read.
- `intl/locale/tests/gtest/moz.build`: registration, `UNIFIED_SOURCES += ["TestStealthSystemLocales.cpp"]` after the closing `]`.

Why the guards are here and the declaration is read when the locales are asked, not where the host is read: the full explanation is in intl/locale/StealthSessionPrefs.h (user preferences, which carry juggler.locale.override, are applied after the first requests XPCOM startup can make, and OSPreferences caches what it reads for good; the one caller that can ask earlier is LocaleService::ReadRequestedLocales, whose result is the language of the browser's own interface, which a page cannot read; everything a page can reach asks later, and asks here). The comment lines that sat above the two guards ("why here" and "the same") are that text.

## Our own files

- `dom/base/StealthSessionDeclaration.cpp`
- `dom/base/StealthSessionDeclaration.h`
- `dom/base/test/gtest/TestStealthDocumentLanguage.cpp`
- `intl/locale/StealthSessionPrefs.cpp`
- `intl/locale/StealthSessionPrefs.h`
- `intl/locale/tests/gtest/TestStealthSystemLocales.cpp`
