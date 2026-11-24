/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthOwnBinaries_h
#define mozilla_StealthOwnBinaries_h

#include "mozilla/UniquePtr.h"
#include "nsStringFwd.h"

namespace mozilla {

class ModuleVersionInfo;

// STEALTH: whether aModulePath lies in the directory of aExeFilePath (or below),
// case-insensitively (see StealthSkipsSignatureLookup).
bool StealthIsInDirectoryOf(const nsAString& aModulePath,
                            const nsAString& aExeFilePath);

// STEALTH: GetVersionAndVendorInfo skips the signature lookup for the modules
// of the directory of the running exe that also carry firefox.exe's version
// (this build's own; the signed C++ runtime beside them keeps it): they carry no Authenticode
// signature, so the lookup always fell through to the catalog search, which
// hashes the whole file and walks every system catalog - 1.26 s of CPU per
// launch in the "Untrusted Modules" thread, on a 2026-10-27 profile, for an
// answer that cannot exist. GetTrust then classifies them as it already did:
// FirefoxDirectory (+AndVersion), from their path and version resource.
//
// StealthIsInDirectoryOf is the path test; StealthSkipsSignatureLookup is the
// whole decision.
//
// True when the signature lookup of the module at aPath must be skipped: it
// has a version resource (aHasVersion, the result of aVerInfo.GetFromImage)
// and is one of this build's own binaries.
bool StealthSkipsSignatureLookup(const nsAString& aPath,
                                 const ModuleVersionInfo& aVerInfo,
                                 bool aHasVersion);

// The same decision from the path alone: reads the version resource of the
// module itself (ModuleVersionInfo::GetFromImage, the read Mozilla makes a few
// lines later; a second read of the same file is invisible to a page).
bool StealthSkipsSignatureLookupOf(const nsAString& aPath);

// GetVersionAndVendorInfo: the signature lookup of Mozilla, handed over as a
// thunk (its text stays in the hook), is made unless the module is one of this
// build's own unsigned binaries; then there is no signature (null), as the
// lookup would have answered after its catalog search.
template <typename SignatureLookupT>
UniquePtr<wchar_t[]> StealthSignatureLookupUnlessOwn(
    const nsAString& aPath, SignatureLookupT&& aSignatureLookup) {
  if (StealthSkipsSignatureLookupOf(aPath)) {
    return nullptr;
  }
  return aSignatureLookup();
}

}  // namespace mozilla

#endif  // mozilla_StealthOwnBinaries_h
