/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthOwnBinaries_h
#define mozilla_StealthOwnBinaries_h

#include <type_traits>
#include <utility>

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

// How many times the signature lookup was skipped for one of this build's own
// binaries, since the process started. It only counts: the gtest that goes
// through Mozilla's ModuleRecord reads it to know that the hook line of
// ModuleRecord::GetVersionAndVendorInfo reached our function and decided.
uint32_t StealthOwnBinarySkips();
void StealthNoteOwnBinarySkip();

// GetVersionAndVendorInfo: the signature lookup of Mozilla, which stays as Mozilla wrote it
// (`dllSvc->GetBinaryOrgName(path, &hasNested, flags)`), is made through the object that
// StealthSignatureLookupUnlessOwn(aPath, dllSvc) stands in for dllSvc: unless the module is one
// of this build's own unsigned binaries, its GetBinaryOrgName is dllSvc's with the arguments it
// is given; for an own binary it is not made, and there is no signature (null), as the lookup
// would have answered after its catalog search, and the skip is counted. The decision (and the
// count) is made when the object is made, before the arguments of the call are evaluated, which
// read nothing and have no effect.
template <typename DllServicesT>
class StealthSignatureLookup final {
 public:
  StealthSignatureLookup(DllServicesT* aDllServices, bool aSkip)
      : mDllServices(aDllServices), mSkip(aSkip) {}

  // So that the call reads as Mozilla's own: `Stealth...(aPath, dllSvc)->GetBinaryOrgName(...)`; the
  // object lives to the end of the full expression it is made in.
  const StealthSignatureLookup* operator->() const { return this; }

  template <typename... Args>
  UniquePtr<wchar_t[]> GetBinaryOrgName(Args&&... aArgs) const {
    if (mSkip) {
      return nullptr;
    }
    return mDllServices->GetBinaryOrgName(std::forward<Args>(aArgs)...);
  }

 private:
  DllServicesT* mDllServices;
  bool mSkip;
};

// aDllServices is a RefPtr to the services (or a pointer to them); the object keeps the pointer.
template <typename DllServicesPtrT>
auto StealthSignatureLookupUnlessOwn(const nsAString& aPath,
                                     DllServicesPtrT&& aDllServices) {
  const bool skip = StealthSkipsSignatureLookupOf(aPath);
  if (skip) {
    StealthNoteOwnBinarySkip();
  }
  auto* services = &*aDllServices;
  return StealthSignatureLookup<std::remove_pointer_t<decltype(services)>>(
      services, skip);
}

}  // namespace mozilla

#endif  // mozilla_StealthOwnBinaries_h
