/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The branding a page reads comes from the archive invisible_core declares
// (zoom.stealth.branding.archive), served as jar:, whichever way the page
// reaches the branding directory: chrome://branding/content/ (the chrome
// registry's ConvertChromeURL) or resource://usercontext-content/branding/
// (SubstitutingProtocolHandler::ResolveURI). Engine off, the build's own URI is
// served: that is the negative control of every test below.
//
// The engine is on with zoom.stealth.fpp.hw_seed > 0. A missing declaration
// with the engine on is not tested here: in the parent process it refuses the
// launch (StealthAssertDeclarationsComplete), which would end the test binary.

#include "gtest/gtest.h"

#include "mozilla/Preferences.h"
#include "mozilla/net/StealthBranding.h"
#include "mozilla/net/SubstitutingProtocolHandler.h"
#include "nsCOMPtr.h"
#include "nsIChromeRegistry.h"
#include "nsIURI.h"
#include "nsNetUtil.h"
#include "nsReadableUtils.h"
#include "nsServiceManagerUtils.h"
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
// test. The registration is process-wide and the last one wins, so the
// directory the registries had recorded (when they had recorded one) is put
// back after the test.
struct BrandingDirectory {
  explicit BrandingDirectory(const nsACString& aBase)
      : mHadOne(StealthBrandingRecordedDirectory(mPrevious)) {
    Register(aBase);
  }
  ~BrandingDirectory() {
    if (mHadOne) {
      Register(mPrevious);
    }
  }
  static void Register(const nsACString& aBase) {
    nsCOMPtr<nsIURI> base;
    MOZ_RELEASE_ASSERT(NS_SUCCEEDED(NS_NewURI(getter_AddRefs(base), aBase)));
    StealthBrandingRegisterPackage("branding"_ns, base);
  }
  nsAutoCString mPrevious;
  const bool mHadOne;
};

// A substituting handler of its own, so the test does not touch resource://.
// "special" resolves through ResolveSpecialCases to a file in the branding
// directory, the way resource://app/ does.
class TestHandler final : public SubstitutingProtocolHandler {
 public:
  TestHandler() : SubstitutingProtocolHandler("stealthtest") {}

 protected:
  bool ResolveSpecialCases(const nsACString& aHost, const nsACString& aPath,
                           const nsACString& aPathname,
                           nsACString& aResult) override {
    if (!aHost.EqualsLiteral("special")) {
      return false;
    }
    aResult.Assign(InBuild("special.png"));
    return true;
  }
};

nsresult ResolveWith(TestHandler* aHandler, const nsACString& aSpec,
                     nsACString& aResult) {
  nsCOMPtr<nsIURI> uri;
  nsresult rv = aHandler->NewURI(aSpec, nullptr, nullptr, getter_AddRefs(uri));
  NS_ENSURE_SUCCESS(rv, rv);
  return aHandler->ResolveURI(uri, aResult);
}

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

TEST(StealthBranding, AUriOutsideTheBrandingDirectoryIsUntouched)
{
  BrandingDirectory directory(kBuildBranding);
  EngineOn on;
  for (const char* other :
       {"file:///stealth-gtest/build/other/content/a.png",
        "file:///stealth-gtest/build/branding/a.png",
        "jar:file:///stealth-gtest/omni.ja!/chrome/a.png",
        "https://example.com/branding/content/a.png"}) {
    nsAutoCString spec(other);
    EXPECT_EQ(NS_OK, StealthBrandingRedirect(spec)) << other;
    EXPECT_TRUE(spec.EqualsASCII(other)) << spec.get();
  }
}

TEST(StealthBranding, AMalformedDeclarationIsNotADeclaration)
{
  EXPECT_TRUE(StealthBrandingIsDeclaredArchive(kDeclaredArchive));
  EXPECT_FALSE(StealthBrandingIsDeclaredArchive(""_ns));
  EXPECT_FALSE(
      StealthBrandingIsDeclaredArchive("file:///stealth-gtest/dir/"_ns));
  EXPECT_FALSE(
      StealthBrandingIsDeclaredArchive("https://example.com/a.zip"_ns));
  EXPECT_FALSE(StealthBrandingIsDeclaredArchive("file:///a\\b.zip"_ns));
  EXPECT_FALSE(StealthBrandingIsDeclaredArchive("file:///a!/b.zip"_ns));
}

TEST(StealthBranding, ThePackageRegistrationKeepsOnlyBrandingWithADirectory)
{
  BrandingDirectory directory(kBuildBranding);
  EngineOn on;
  nsCOMPtr<nsIURI> other;
  ASSERT_EQ(NS_OK, NS_NewURI(getter_AddRefs(other),
                             "file:///stealth-gtest/other/"_ns));
  // Another package, and a package with no content directory in this process
  // (a content process has none for some packages): both leave the branding
  // directory as it was.
  StealthBrandingRegisterPackage("global"_ns, other);
  StealthBrandingRegisterPackage("branding"_ns, nullptr);
  nsAutoCString spec(InBuild("icon.png"));
  EXPECT_EQ(NS_OK, StealthBrandingRedirect(spec));
  EXPECT_TRUE(spec.Equals(InJar("icon.png"))) << spec.get();
  nsAutoCString stays("file:///stealth-gtest/other/icon.png");
  EXPECT_EQ(NS_OK, StealthBrandingRedirect(stays));
  EXPECT_TRUE(stays.EqualsLiteral("file:///stealth-gtest/other/icon.png"));
}

TEST(StealthBranding, TheChromeRegistryWrapKeepsOrRebuildsTheResolvedUri)
{
  BrandingDirectory directory(kBuildBranding);
  nsCOMPtr<nsIURI> resolved;
  ASSERT_EQ(NS_OK,
            NS_NewURI(getter_AddRefs(resolved), InBuild("icon.png")));
  nsIURI* before = resolved;

  // Engine off: the very object the stock call resolved, with no second parse.
  nsIURI* out = resolved.forget().take();
  EXPECT_EQ(NS_OK, StealthBrandingChromeURL(NS_OK, &out));
  EXPECT_EQ(before, out);
  NS_RELEASE(out);

  {
    // Engine on: a URI built from the declared jar.
    EngineOn on;
    ASSERT_EQ(NS_OK,
              NS_NewURI(getter_AddRefs(resolved), InBuild("icon.png")));
    out = resolved.forget().take();
    EXPECT_EQ(NS_OK, StealthBrandingChromeURL(NS_OK, &out));
    ASSERT_TRUE(out);
    nsAutoCString spec;
    EXPECT_EQ(NS_OK, out->GetSpec(spec));
    EXPECT_TRUE(spec.Equals(InJar("icon.png"))) << spec.get();
    NS_RELEASE(out);

    // A failed resolution is returned as it is, and nothing is written.
    out = nullptr;
    EXPECT_EQ(NS_ERROR_FILE_NOT_FOUND,
              StealthBrandingChromeURL(NS_ERROR_FILE_NOT_FOUND, &out));
    EXPECT_FALSE(out);
  }
}

TEST(StealthBranding, TheChromeRegistryServesTheDeclaredJarWhenItHasBranding)
{
  nsCOMPtr<nsIChromeRegistry> registry =
      do_GetService("@mozilla.org/chrome/chrome-registry;1");
  ASSERT_TRUE(registry);
  nsCOMPtr<nsIURI> chrome;
  ASSERT_EQ(NS_OK, NS_NewURI(getter_AddRefs(chrome),
                             "chrome://branding/content/icon.png"_ns));
  // Engine off: the build's own URI, if this binary registers a branding
  // package at all.
  nsCOMPtr<nsIURI> resolved;
  if (NS_FAILED(registry->ConvertChromeURL(chrome, getter_AddRefs(resolved)))) {
    GTEST_SKIP() << "this test binary has no branding package";
  }
  nsAutoCString stock;
  ASSERT_EQ(NS_OK, resolved->GetSpec(stock));

  // The registries recorded the package's directory when they read its
  // manifest (nsChromeRegistryChrome::ManifestContent): what is served with the
  // engine on is the declared jar, with no help from the test.
  nsAutoCString recorded;
  ASSERT_TRUE(StealthBrandingRecordedDirectory(recorded))
      << "the chrome registry recorded no branding directory";
  EXPECT_TRUE(StringBeginsWith(stock, recorded)) << stock.get();

  EngineOn on;
  nsCOMPtr<nsIURI> declared;
  ASSERT_EQ(NS_OK,
            registry->ConvertChromeURL(chrome, getter_AddRefs(declared)));
  nsAutoCString spec;
  ASSERT_EQ(NS_OK, declared->GetSpec(spec));
  EXPECT_TRUE(spec.Equals(InJar("icon.png"))) << spec.get();
  EXPECT_FALSE(spec.Equals(stock)) << "the engine on must differ from the build";
}

TEST(StealthBranding, TheResourceWayAndTheChromeWayGiveTheSameJar)
{
  BrandingDirectory directory(kBuildBranding);
  RefPtr<TestHandler> handler = new TestHandler();
  nsCOMPtr<nsIURI> base;
  ASSERT_EQ(NS_OK, NS_NewURI(getter_AddRefs(base), kBuildBranding));
  ASSERT_EQ(NS_OK, handler->SetSubstitution("branding"_ns, base));

  // Engine off: the build's own directory.
  nsAutoCString stock;
  ASSERT_EQ(NS_OK,
            ResolveWith(handler, "stealthtest://branding/icon.png"_ns, stock));
  EXPECT_TRUE(stock.Equals(InBuild("icon.png"))) << stock.get();

  EngineOn on;
  nsAutoCString viaResource;
  ASSERT_EQ(NS_OK, ResolveWith(handler, "stealthtest://branding/icon.png"_ns,
                               viaResource));
  EXPECT_TRUE(viaResource.Equals(InJar("icon.png"))) << viaResource.get();

  // The chrome way ends in the same place by construction.
  nsCOMPtr<nsIURI> resolved;
  ASSERT_EQ(NS_OK, NS_NewURI(getter_AddRefs(resolved), stock));
  nsIURI* out = resolved.forget().take();
  ASSERT_EQ(NS_OK, StealthBrandingChromeURL(NS_OK, &out));
  nsAutoCString viaChrome;
  ASSERT_EQ(NS_OK, out->GetSpec(viaChrome));
  NS_RELEASE(out);
  EXPECT_TRUE(viaChrome.Equals(viaResource)) << viaChrome.get();
}

TEST(StealthBranding, TheSpecialCasesRoadIsRedirectedToo)
{
  BrandingDirectory directory(kBuildBranding);
  RefPtr<TestHandler> handler = new TestHandler();

  nsAutoCString stock;
  ASSERT_EQ(NS_OK,
            ResolveWith(handler, "stealthtest://special/anything"_ns, stock));
  EXPECT_TRUE(stock.Equals(InBuild("special.png"))) << stock.get();

  EngineOn on;
  nsAutoCString declared;
  ASSERT_EQ(NS_OK,
            ResolveWith(handler, "stealthtest://special/anything"_ns, declared));
  EXPECT_TRUE(declared.Equals(InJar("special.png"))) << declared.get();
}

TEST(StealthBranding, AFailedResolutionIsReturnedAsItIs)
{
  BrandingDirectory directory(kBuildBranding);
  RefPtr<TestHandler> handler = new TestHandler();
  EngineOn on;
  nsAutoCString result;
  // No such root: Mozilla's own failure, not the redirect's.
  const nsresult rv =
      ResolveWith(handler, "stealthtest://nosuchroot/a.png"_ns, result);
  EXPECT_TRUE(NS_FAILED(rv));
  EXPECT_NE(NS_ERROR_FILE_NOT_FOUND, rv);
}

}  // namespace mozilla::net
