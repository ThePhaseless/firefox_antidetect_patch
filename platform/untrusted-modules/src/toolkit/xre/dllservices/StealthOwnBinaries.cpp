/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

#include "StealthOwnBinaries.h"

#include <iterator>
#include <windows.h>

#include "ModuleVersionInfo.h"
#include "mozilla/UntrustedModulesData.h"
#include "nsString.h"
#include "nsUnicharUtils.h"

namespace mozilla {

// STEALTH: whether aModulePath lies in the directory of aExeFilePath (or below),
// case-insensitively. The path test of StealthSkipsSignatureLookup (see its
// comment in StealthOwnBinaries.h).
bool StealthIsInDirectoryOf(const nsAString& aModulePath,
                            const nsAString& aExeFilePath) {
  const int32_t slash = aExeFilePath.RFindChar(u'\\');
  if (slash <= 0) {
    return false;
  }
  const nsDependentSubstring dir = Substring(aExeFilePath, 0, slash + 1);
  return StringBeginsWith(aModulePath, dir, nsCaseInsensitiveStringComparator);
}

namespace {

// STEALTH: one of this build's own binaries - beside firefox.exe and with its
// version - whose signature lookup can only fall through to the catalog
// search (see StealthIsInDirectoryOf). Anything else in the directory, such as
// the signed C++ runtime, keeps the lookup and its classification.
bool IsOwnUnsignedBinary(const nsAString& aPath,
                         const ModuleVersionInfo& aVerInfo) {
  wchar_t exePath[MAX_PATH * 4];
  const DWORD exeLen =
      ::GetModuleFileNameW(nullptr, exePath, std::size(exePath));
  if (exeLen == 0 || exeLen >= std::size(exePath)) {
    return false;
  }
  const nsDependentString exe(exePath, exeLen);
  if (!StealthIsInDirectoryOf(aPath, exe)) {
    return false;
  }
  ModuleVersionInfo exeVer;
  return exeVer.GetFromImage(exe) && aVerInfo.mFileVersion.Version64() &&
         exeVer.mFileVersion.Version64() == aVerInfo.mFileVersion.Version64();
}

}  // namespace

bool StealthSkipsSignatureLookup(const nsAString& aPath,
                                 const ModuleVersionInfo& aVerInfo,
                                 bool aHasVersion) {
  return aHasVersion && IsOwnUnsignedBinary(aPath, aVerInfo);
}

bool StealthSkipsSignatureLookupOf(const nsAString& aPath) {
  ModuleVersionInfo verInfo;
  const bool hasVersion = verInfo.GetFromImage(aPath);
  return StealthSkipsSignatureLookup(aPath, verInfo, hasVersion);
}

}  // namespace mozilla
