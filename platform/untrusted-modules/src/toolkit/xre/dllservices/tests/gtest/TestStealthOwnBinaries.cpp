/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Which modules the untrusted-modules processor treats as this build's own,
// and so skips the signature lookup for (StealthIsInDirectoryOf): it
// hashed every unsigned DLL of the install for a catalog signature that
// cannot exist, 1.26 s of CPU per launch.

#include <iterator>
#include <wchar.h>
#include <windows.h>

#include "gtest/gtest.h"

#include "mozilla/RefPtr.h"
#include "mozilla/UntrustedModulesProcessor.h"
#include "mozilla/ipc/FileDescriptor.h"
#include "nsWindowsHelpers.h"

#include "mozilla/UntrustedModulesData.h"
#include "mozilla/ModuleVersionInfo.h"
#include "../../StealthOwnBinaries.h"
#include "nsString.h"

using mozilla::StealthIsInDirectoryOf;
using mozilla::StealthSkipsSignatureLookup;

TEST(StealthOwnBinaries, BesideTheExeAndBelowIt)
{
  const nsString exe(u"C:\\Program Files\\App\\firefox.exe"_ns);
  EXPECT_TRUE(StealthIsInDirectoryOf(u"C:\\Program Files\\App\\xul.dll"_ns, exe));
  EXPECT_TRUE(StealthIsInDirectoryOf(
      u"C:\\Program Files\\App\\gmp-clearkey\\0.1\\clearkey.dll"_ns, exe));
}

TEST(StealthOwnBinaries, CaseInsensitiveAsWindowsPathsAre)
{
  EXPECT_TRUE(StealthIsInDirectoryOf(
      u"c:\\program files\\app\\XUL.DLL"_ns, u"C:\\Program Files\\App\\firefox.exe"_ns));
}

TEST(StealthOwnBinaries, ElsewhereKeepsTheLookup)
{
  const nsString exe(u"C:\\Program Files\\App\\firefox.exe"_ns);
  EXPECT_FALSE(StealthIsInDirectoryOf(u"C:\\Windows\\System32\\ntdll.dll"_ns, exe));
  // A sibling directory whose name starts like ours is not ours.
  EXPECT_FALSE(StealthIsInDirectoryOf(u"C:\\Program Files\\App2\\evil.dll"_ns, exe));
  // No directory in the exe path: never treated as ours.
  EXPECT_FALSE(StealthIsInDirectoryOf(u"xul.dll"_ns, u"firefox.exe"_ns));
}

TEST(StealthOwnBinaries, StealthSkipsSignatureLookup)
{
  // Outside the directory of the running exe: the lookup is kept.
  EXPECT_FALSE(StealthSkipsSignatureLookup(u"C:\\Windows\\System32\\ntdll.dll"_ns,
                                           mozilla::ModuleVersionInfo(), true));
  // No version resource: the lookup is kept.
  EXPECT_FALSE(StealthSkipsSignatureLookup(u"C:\\Windows\\System32\\ntdll.dll"_ns,
                                           mozilla::ModuleVersionInfo(), false));
}

namespace {

// A stand-in for the DllServices of Mozilla: it counts the lookups made and answers each with an organisation.
struct CountingDllServices {
  int lookups = 0;
  mozilla::UniquePtr<wchar_t[]> GetBinaryOrgName(const wchar_t* aFilePath, bool* aHasNestedMicrosoftSignature, int aFlags) {
    ++lookups;
    auto org = mozilla::MakeUnique<wchar_t[]>(4);
    wcscpy_s(org.get(), 4, L"Org");
    return org;
  }
};

}  // namespace

// GetVersionAndVendorInfo makes Mozilla's call through the object StealthSignatureLookupUnlessOwn(aPath, dllSvc) stands in for
// dllSvc with: the lookup is made for a module that is not one of this build's own, with the answer of the services, and
// never made for one that is (the running exe's own file is one: its directory and its version), which has no signature. The
// count of the services is the observable; the control is the module of the system, for which it is made once.
TEST(StealthOwnBinaries, TheSignatureLookupIsMadeOnlyForAModuleThatIsNotOurOwn)
{
  CountingDllServices services;
  bool nested = false;

  // The control: a module of the system, the lookup is made, once, and its answer is the one returned.
  mozilla::UniquePtr<wchar_t[]> answer =
      mozilla::StealthSignatureLookupUnlessOwn(u"C:\Windows\System32\ntdll.dll"_ns, &services)
          ->GetBinaryOrgName(L"C:\Windows\System32\ntdll.dll", &nested, 0);
  EXPECT_EQ(services.lookups, 1);
  ASSERT_TRUE(answer);
  EXPECT_STREQ(answer.get(), L"Org");

  wchar_t exePath[MAX_PATH * 4];
  const DWORD exeLen = ::GetModuleFileNameW(nullptr, exePath, std::size(exePath));
  ASSERT_TRUE(exeLen > 0 && exeLen < std::size(exePath));
  const nsDependentString exe(exePath, exeLen);
  if (!mozilla::StealthSkipsSignatureLookupOf(exe)) {
    GTEST_SKIP() << "the test process has no version resource of its own";
  }
  services.lookups = 0;
  const uint32_t skips = mozilla::StealthOwnBinarySkips();
  answer = mozilla::StealthSignatureLookupUnlessOwn(exe, &services)->GetBinaryOrgName(exePath, &nested, 0);
  EXPECT_EQ(services.lookups, 0);
  EXPECT_FALSE(answer);
  EXPECT_FALSE(nested);
  EXPECT_EQ(mozilla::StealthOwnBinarySkips(), skips + 1);
}

namespace {

// The NT path of the file of a module of this process, the way Mozilla's untrusted-modules code produces the
// aResolvedNtPath a ModuleRecord takes: the file is opened with the access and sharing the loader uses and handed to
// ValidateAndResolveModuleFile (UntrustedModulesProcessor.cpp:165, called at :1224 to get the path ModuleRecord is made from), which
// gives the \Device\HarddiskVolumeN\... form. An empty result is a failure of the test, not a reason to skip it.
nsString NtPathOfModule(HMODULE aModule) {
  wchar_t dosPath[MAX_PATH * 4] = {};
  const DWORD len = ::GetModuleFileNameW(aModule, dosPath, std::size(dosPath));
  if (len == 0 || len >= std::size(dosPath)) {
    return nsString();
  }
  nsAutoHandle file(::CreateFileW(dosPath, SYNCHRONIZE | FILE_EXECUTE | FILE_READ_DATA,
                                  FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                                  FILE_ATTRIBUTE_NORMAL, nullptr));
  if (file.get() == INVALID_HANDLE_VALUE) {
    return nsString();
  }
  mozilla::ipc::FileDescriptor fd(file.get());
  nsAutoString resolved;
  if (!fd.IsValid() || !mozilla::ValidateAndResolveModuleFile(fd, resolved)) {
    return nsString();
  }
  return nsString(resolved);
}

}  // namespace

// hook-04 for the line in Mozilla's file: the test goes through Mozilla's own ModuleRecord, whose constructor runs
// GetVersionAndVendorInfo, and so the hook line of untrusted-modules there (the signature lookup made through
// StealthSignatureLookupUnlessOwn). For the running executable's own file the lookup is skipped: the counter of our file goes
// up by exactly one and the vendor, when there is one, comes from the version resource and not from a signature. For a module
// of the system (the control) the lookup is made and the counter does not move. Without the hook line Mozilla's statement does
// not call our function, the counter stays at 0 and the test fails.
TEST(StealthOwnBinaries, ModuleRecordSkipsTheSignatureLookupOfTheRunningExecutableOnly)
{
  const nsString exeNt = NtPathOfModule(nullptr);
  ASSERT_FALSE(exeNt.IsEmpty());
  wchar_t exePath[MAX_PATH * 4];
  const DWORD exeLen = ::GetModuleFileNameW(nullptr, exePath, std::size(exePath));
  ASSERT_TRUE(exeLen > 0 && exeLen < std::size(exePath));
  if (!mozilla::StealthSkipsSignatureLookupOf(nsDependentString(exePath, exeLen))) {
    GTEST_SKIP() << "the test process has no version resource of its own";
  }

  // The control: a module of the system. Its signature is looked up, so our counter does not move.
  const nsString ntdllNt = NtPathOfModule(::GetModuleHandleW(L"ntdll.dll"));
  ASSERT_FALSE(ntdllNt.IsEmpty());
  const uint32_t beforeControl = mozilla::StealthOwnBinarySkips();
  {
    RefPtr<mozilla::ModuleRecord> control = new mozilla::ModuleRecord(ntdllNt);
    EXPECT_NE(control->mResolvedDosName.get(), nullptr);
  }
  EXPECT_EQ(mozilla::StealthOwnBinarySkips(), beforeControl);

  // The running executable: the lookup is skipped, once.
  const uint32_t before = mozilla::StealthOwnBinarySkips();
  RefPtr<mozilla::ModuleRecord> own = new mozilla::ModuleRecord(exeNt);
  ASSERT_NE(own->mResolvedDosName.get(), nullptr);
  EXPECT_EQ(mozilla::StealthOwnBinarySkips(), before + 1);
  if (own->mVendorInfo.isSome()) {
    EXPECT_TRUE(own->mVendorInfo->mSource == mozilla::VendorInfo::Source::VersionInfo)
        << "the vendor of a module whose signature was not looked up came from a signature";
  }
}
