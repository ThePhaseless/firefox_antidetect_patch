/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this file,
 * You can obtain one at http://mozilla.org/MPL/2.0/. */

// The content sandbox's policy grants READ access to exactly the archive
// invisible_core declares as the branding a page reads
// (zoom.stealth.branding.archive), and to nothing when the engine is off or the
// declaration is not usable. Engine off is the negative control: the same
// declaration, no rule.

#include <stdio.h>

#include "broker/SandboxBroker.h"
#include "broker/StealthLinuxSandboxBranding.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "nsCOMPtr.h"
#include "nsDirectoryServiceDefs.h"
#include "nsDirectoryServiceUtils.h"
#include "nsIFile.h"
#include "nsNetUtil.h"
#include "nsString.h"

namespace mozilla {

namespace {

// A zip archive with one stored file at its root, "a.txt" holding "x": what the
// declaration gate accepts.
const unsigned char kStealthBrandingZip[] = {
    0x50, 0x4b, 0x03, 0x04, 0x0a, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x83, 0x16, 0xdc, 0x8c, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x61, 0x2e, 0x74, 0x78, 0x74, 0x78,
    0x50, 0x4b, 0x01, 0x02, 0x14, 0x00, 0x0a, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x83, 0x16, 0xdc, 0x8c, 0x01, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x61, 0x2e,
    0x74, 0x78, 0x74, 0x50, 0x4b, 0x05, 0x06, 0x00, 0x00, 0x00, 0x00, 0x01,
    0x00, 0x01, 0x00, 0x33, 0x00, 0x00, 0x00, 0x24, 0x00, 0x00, 0x00, 0x00,
    0x00};

constexpr char kSeedPref[] = "zoom.stealth.fpp.hw_seed";
constexpr char kArchivePref[] = "zoom.stealth.branding.archive";

// A file in the temp directory holding the given bytes, declared as the
// branding archive, for the life of a test.
struct StealthDeclaredFile {
  StealthDeclaredFile(const char* aName, const void* aBytes, size_t aLength) {
    EXPECT_TRUE(NS_SUCCEEDED(NS_GetSpecialDirectory(NS_OS_TEMP_DIR,
                                                    getter_AddRefs(mFile))));
    EXPECT_TRUE(NS_SUCCEEDED(mFile->AppendNative(nsDependentCString(aName))));
    EXPECT_TRUE(NS_SUCCEEDED(mFile->GetNativePath(mPath)));
    if (aBytes) {
      FILE* f = fopen(mPath.get(), "wb");
      EXPECT_TRUE(f);
      if (f) {
        EXPECT_EQ(aLength, fwrite(aBytes, 1, aLength, f));
        fclose(f);
      }
    }
    nsAutoCString spec;
    EXPECT_TRUE(NS_SUCCEEDED(NS_GetURLSpecFromFile(mFile, spec)));
    Preferences::SetCString(kArchivePref, spec);
  }
  ~StealthDeclaredFile() {
    Preferences::ClearUser(kArchivePref);
    Preferences::ClearUser(kSeedPref);
    mFile->Remove(false);
  }
  nsCOMPtr<nsIFile> mFile;
  nsAutoCString mPath;
};

}  // namespace

TEST(StealthBranding, SandboxPolicyAllowsTheDeclaredArchive)
{
  StealthDeclaredFile declared("stealth-branding-gtest.zip",
                               kStealthBrandingZip, sizeof(kStealthBrandingZip));

  // Engine off: the same declaration grants nothing.
  {
    SandboxBroker::Policy policy;
    StealthBrandingAddReadRule(&policy);
    EXPECT_TRUE(policy.IsEmpty());
    EXPECT_EQ(0, policy.Lookup(declared.mPath));
  }

  // Engine on: one read-only rule on exactly that file.
  Preferences::SetInt(kSeedPref, 7);
  SandboxBroker::Policy policy;
  StealthBrandingAddReadRule(&policy);
  EXPECT_EQ(SandboxBroker::MAY_ACCESS | SandboxBroker::MAY_READ,
            policy.Lookup(declared.mPath));
}

TEST(StealthBranding, SandboxPolicyAddsNothingForAnUnusableDeclaration)
{
  Preferences::SetInt(kSeedPref, 7);
  {
    // Declared, but the file does not exist.
    StealthDeclaredFile missing("stealth-branding-gtest-missing.zip", nullptr,
                                0);
    SandboxBroker::Policy policy;
    StealthBrandingAddReadRule(&policy);
    EXPECT_TRUE(policy.IsEmpty());
  }
  Preferences::SetInt(kSeedPref, 7);
  {
    // Declared, but not a zip archive.
    const char notZip[] = "not a zip archive";
    StealthDeclaredFile text("stealth-branding-gtest-text.zip", notZip,
                             sizeof(notZip));
    SandboxBroker::Policy policy;
    StealthBrandingAddReadRule(&policy);
    EXPECT_TRUE(policy.IsEmpty());
  }
}

}  // namespace mozilla
