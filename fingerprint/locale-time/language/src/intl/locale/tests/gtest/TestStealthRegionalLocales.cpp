/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The regional settings of "the machine" are the language the session
// declares (juggler.locale.override), not the operating system's:
// LocaleService::GetRegionalPrefsLocales, which feeds the web-exposed locales
// and the date and time formats, answers from the declaration when one is
// made, and keeps upstream's rule (the regional language is used only when it
// matches the app locale). The tests go through LocaleService, the entry
// every caller uses. The language atom the layout reads on a worker thread
// (nsLanguageAtomService::GetLocaleLanguage) is tested through the service.

#include <thread>

#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "mozilla/gtest/MozAssertions.h"
#include "mozilla/intl/LocaleService.h"
#include "mozilla/intl/StealthSessionPrefs.h"
#include "nsAtom.h"
#include "nsLanguageAtomService.h"
#include "nsString.h"
#include "nsTArray.h"

using mozilla::Preferences;
using namespace mozilla::intl;

namespace {
// The session's declaration for the life of a test: an ASSERT that returns
// early still clears it.
struct DeclaredRegionalLanguage {
  explicit DeclaredRegionalLanguage(const char* aList) {
    Preferences::SetCString("juggler.locale.override", aList);
  }
  ~DeclaredRegionalLanguage() {
    Preferences::ClearUser("juggler.locale.override");
  }
};

struct UseOSLocales {
  UseOSLocales() {
    Preferences::SetBool("intl.regional_prefs.use_os_locales", true);
  }
  ~UseOSLocales() {
    Preferences::ClearUser("intl.regional_prefs.use_os_locales");
  }
};
}  // namespace

static nsTArray<nsCString> RegionalLocales() {
  nsTArray<nsCString> locales;
  // Mozilla's GetRegionalPrefsLocales wants an empty list (it caches what the
  // list holds): a list that is not empty would stay in the process's cache.
  EXPECT_TRUE(NS_SUCCEEDED(
      LocaleService::GetInstance()->GetRegionalPrefsLocales(locales)));
  return locales;
}

static bool IsOnly(const nsTArray<nsCString>& aLocales, const char* aTag) {
  return aLocales.Length() == 1 && aLocales[0].EqualsASCII(aTag);
}

// en-TT (Trinidad and Tobago) is a region no host of ours has: the answer can
// only come from the declaration.
TEST(Intl_Locale_StealthSystemLocales, TheDeclaredLanguageIsTheRegionalLanguage)
{
  nsAutoCString appLocale;
  LocaleService::GetInstance()->GetAppLocaleAsBCP47(appLocale);
  ASSERT_TRUE(LocaleService::LanguagesMatch(appLocale, "en-TT"_ns))
      << "the app locale of the test process is " << appLocale.get();

  {
    DeclaredRegionalLanguage session("en-TT, en, en-US");
    // Same language as the app locale: upstream's rule takes the regional one.
    EXPECT_TRUE(IsOnly(RegionalLocales(), "en-TT"));
  }
  // Nothing declared: the operating system answers, as upstream.
  EXPECT_FALSE(IsOnly(RegionalLocales(), "en-TT"));
}

TEST(Intl_Locale_StealthSystemLocales,
     ADeclaredLanguageOfAnotherLanguageKeepsTheAppLocales)
{
  nsTArray<nsCString> appLocales;
  ASSERT_TRUE(NS_SUCCEEDED(
      LocaleService::GetInstance()->GetAppLocalesAsBCP47(appLocales)));

  DeclaredRegionalLanguage session("ja-JP, ja, en-US, en");
  // Upstream's rule, unchanged: a regional language that is not the app's
  // does not replace it, whatever the machine says.
  EXPECT_TRUE(RegionalLocales() == appLocales);
}

TEST(Intl_Locale_StealthSystemLocales,
     WithTheOSLocalesPreferenceTheDeclaredLanguageIsTheOnlyOne)
{
  UseOSLocales useOS;
  {
    DeclaredRegionalLanguage session("ja-JP, ja, en-US, en");
    EXPECT_TRUE(IsOnly(RegionalLocales(), "ja-JP"));
  }
  // Nothing declared: what the operating system says (a host in Japanese is
  // not one of ours).
  EXPECT_FALSE(IsOnly(RegionalLocales(), "ja-JP"));
}

// The language the layout takes for text without a lang attribute, asked of
// the real service on a worker thread: a thread that declared a language
// answers it, a thread that declared nothing answers what the service answers
// on the main thread (Mozilla's value).
TEST(Intl_Locale_StealthSystemLocales,
     TheLanguageAtomServiceAnswersAWorkersDeclaredLanguage)
{
  nsLanguageAtomService* service = nsLanguageAtomService::GetService();
  nsAtom* mainThread = service->GetLocaleLanguage();  // fills the cache on the main thread
  ASSERT_TRUE(mainThread);

  nsAtom* declared = nullptr;
  nsAtom* undeclared = nullptr;
  std::thread withLanguage([&] {
    mozilla::intl::SetWorkerLocaleLanguage("ja-JP, ja, en-US, en"_ns);
    declared = service->GetLocaleLanguage();
  });
  withLanguage.join();
  // Negative control: a thread with no declaration gets Mozilla's answer.
  std::thread withoutLanguage([&] { undeclared = service->GetLocaleLanguage(); });
  withoutLanguage.join();

  ASSERT_TRUE(declared);
  nsAutoCString tag;
  declared->ToUTF8String(tag);
  EXPECT_TRUE(tag.EqualsLiteral("ja-jp")) << tag.get();
  EXPECT_NE(declared, mainThread);
  EXPECT_EQ(undeclared, mainThread);
  EXPECT_EQ(service->GetLocaleLanguage(), mainThread);  // the main thread is untouched
}
