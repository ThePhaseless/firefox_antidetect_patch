/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The branding a page reads comes from the archive invisible_core declares
// (zoom.stealth.branding.archive), served as jar:, whichever way the page
// reaches the branding directory. Engine off, the build's own URI is served:
// that is the negative control of the first test below.
//
// The engine is on with zoom.stealth.fpp.hw_seed > 0.

#include "gtest/gtest.h"

#include "mozilla/Preferences.h"
#include "mozilla/net/StealthBranding.h"
#include "nsCOMPtr.h"
#include "nsIURI.h"
#include "nsNetUtil.h"
#include "nsString.h"

namespace mozilla::net {

namespace {

constexpr char kSeedPref[] = "zoom.stealth.fpp.hw_seed";
constexpr char kArchivePref[] = "zoom.stealth.branding.archive";

// Made-up locations: nothing is read from them, the redirect only rewrites
// specs.
constexpr auto kBuildBranding =
    "file:///stealth-gtest/build/branding/content/"_ns;
constexpr auto kDeclaredArchive = "file:///stealth-gtest/declared/brand.zip"_ns;
constexpr auto kDeclaredJar =
    "jar:file:///stealth-gtest/declared/brand.zip!/"_ns;

// A file of the branding directory of the build, and the same file as the
// declared archive serves it.
nsCString InBuild(const char* aName) {
  return nsCString(kBuildBranding + nsDependentCString(aName));
}
nsCString InJar(const char* aName) {
  return nsCString(kDeclaredJar + nsDependentCString(aName));
}

// The engine on with the archive declared, for the life of a test; back to
// stock Firefox after it, whatever the test did.
struct EngineOn {
  EngineOn() {
    Preferences::SetInt(kSeedPref, 7);
    Preferences::SetCString(kArchivePref, kDeclaredArchive);
  }
  ~EngineOn() {
    Preferences::ClearUser(kSeedPref);
    Preferences::ClearUser(kArchivePref);
  }
};

// The branding package's directory as the test needs it, for the life of a
// test. The registration is process-wide and the last one wins.
struct BrandingDirectory {
  explicit BrandingDirectory(const nsACString& aBase) {
    nsCOMPtr<nsIURI> base;
    MOZ_RELEASE_ASSERT(NS_SUCCEEDED(NS_NewURI(getter_AddRefs(base), aBase)));
    StealthBrandingRegisterPackage("branding"_ns, base);
  }
};

}  // namespace

TEST(StealthBranding, TheDeclaredArchiveReplacesTheBrandingDirectoryAsJar)
{
  BrandingDirectory directory(kBuildBranding);
  const nsCString spec = InBuild("about-wordmark.svg");

  // Engine off: the build's own URI.
  nsAutoCString off(spec);
  EXPECT_EQ(NS_OK, StealthBrandingRedirect(off));
  EXPECT_TRUE(off.Equals(spec)) << off.get();

  // Engine on: the declared archive, as jar:, whatever the build has.
  EngineOn on;
  nsAutoCString declared(spec);
  EXPECT_EQ(NS_OK, StealthBrandingRedirect(declared));
  EXPECT_TRUE(declared.Equals(InJar("about-wordmark.svg"))) << declared.get();
}

TEST(StealthBranding, ThePackageRegistrationKeepsOnlyBrandingWithADirectory)
{
  BrandingDirectory directory(kBuildBranding);
  EngineOn on;
  nsCOMPtr<nsIURI> other;
  ASSERT_EQ(NS_OK, NS_NewURI(getter_AddRefs(other),
                             "file:///stealth-gtest/other/"_ns));
  // Another package leaves the branding directory as it was. On the baseline
  // the null check of a package with no content directory sits at the call
  // site (nsChromeRegistryContent.cpp), not in this function.
  StealthBrandingRegisterPackage("global"_ns, other);
  nsAutoCString spec(InBuild("icon.png"));
  EXPECT_EQ(NS_OK, StealthBrandingRedirect(spec));
  EXPECT_TRUE(spec.Equals(InJar("icon.png"))) << spec.get();
  nsAutoCString stays("file:///stealth-gtest/other/icon.png");
  EXPECT_EQ(NS_OK, StealthBrandingRedirect(stays));
  EXPECT_TRUE(stays.EqualsLiteral("file:///stealth-gtest/other/icon.png"));
}

}  // namespace mozilla::net
