/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Which modules the untrusted-modules processor treats as this build's own,
// and so skips the signature lookup for (StealthIsInDirectoryOf): it
// hashed every unsigned DLL of the install for a catalog signature that
// cannot exist, 1.26 s of CPU per launch.

#include <iterator>
#include <windows.h>
#include <psapi.h>

#include "gtest/gtest.h"

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

// GetVersionAndVendorInfo hands the signature lookup of Mozilla to our function as a thunk: it is made for a module that
// is not one of this build's own, and never made for one that is (the running exe's own file is one: its directory and its
// version). The count of the thunk is the observable; the control is the module of the system, for which it is made once.
TEST(StealthOwnBinaries, TheSignatureLookupIsMadeOnlyForAModuleThatIsNotOurOwn)
{
  int lookups = 0;
  auto lookup = [&]() {
    ++lookups;
    return mozilla::UniquePtr<wchar_t[]>();
  };

  // The control: a module of the system, the lookup is made, once, and its answer is the one returned.
  mozilla::StealthSignatureLookupUnlessOwn(u"C:\\Windows\\System32\\ntdll.dll"_ns, lookup);
  EXPECT_EQ(lookups, 1);

  wchar_t exePath[MAX_PATH * 4];
  const DWORD exeLen = ::GetModuleFileNameW(nullptr, exePath, std::size(exePath));
  ASSERT_TRUE(exeLen > 0 && exeLen < std::size(exePath));
  const nsDependentString exe(exePath, exeLen);
  if (!mozilla::StealthSkipsSignatureLookupOf(exe)) {
    GTEST_SKIP() << "the test process has no version resource of its own";
  }
  lookups = 0;
  mozilla::StealthSignatureLookupUnlessOwn(exe, lookup);
  EXPECT_EQ(lookups, 0);
}

namespace {

// The path of a module of this process as the loader records it (the name of its mapped section, \Device\...): the form
// ModuleRecord takes.
nsString NtPathOfModule(HMODULE aModule) {
  wchar_t mapped[MAX_PATH + 1] = {};
  if (!::GetMappedFileNameW(::GetCurrentProcess(), aModule, mapped, std::size(mapped))) {
    return nsString();
  }
  return nsString(mapped);
}

}  // namespace

// hook-04 for the line in Mozilla's file: the test goes through Mozilla's own ModuleRecord, whose constructor runs
// GetVersionAndVendorInfo, and so the hook line of untrusted-modules there (the signature lookup handed to
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
    mozilla::ModuleRecord control(ntdllNt);
    EXPECT_NE(control.mResolvedDosName.get(), nullptr);
  }
  EXPECT_EQ(mozilla::StealthOwnBinarySkips(), beforeControl);

  // The running executable: the lookup is skipped, once.
  const uint32_t before = mozilla::StealthOwnBinarySkips();
  mozilla::ModuleRecord own(exeNt);
  ASSERT_NE(own.mResolvedDosName.get(), nullptr);
  EXPECT_EQ(mozilla::StealthOwnBinarySkips(), before + 1);
  if (own.mVendorInfo.isSome()) {
    EXPECT_TRUE(own.mVendorInfo->mSource == mozilla::VendorInfo::Source::VersionInfo)
        << "the vendor of a module whose signature was not looked up came from a signature";
  }
}
