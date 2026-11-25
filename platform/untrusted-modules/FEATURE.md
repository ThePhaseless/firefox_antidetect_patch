# platform/untrusted-modules

Category: other
Prefs: none read directly
Test: toolkit/xre/dllservices/tests/gtest/TestStealthOwnBinaries.cpp (gtest:StealthOwnBinaries.BesideTheExeAndBelowIt, StealthOwnBinaries.CaseInsensitiveAsWindowsPathsAre, StealthOwnBinaries.ElsewhereKeepsTheLookup, StealthOwnBinaries.StealthSkipsSignatureLookup, StealthOwnBinaries.TheSignatureLookupIsMadeOnlyForAModuleThatIsNotOurOwn; Windows)

## What it does

A performance fix, not a value a page reads. The "Untrusted Modules" thread
looked up the Authenticode signature of every module, including this build's
own binaries (beside firefox.exe and carrying its file version). Those carry no
Authenticode signature, so the lookup always fell through to the catalog
search, which hashes the whole file and walks every system catalog: 1.26 s of
CPU per launch (profile of 2026-10-27), for an answer that cannot exist. The
lookup is skipped for them: Mozilla's call stays as Mozilla wrote it, on a receiver that our function decides. The classification does not change: GetTrust
classifies them as before, FirefoxDirectory (+AndVersion), from their path and
version resource. The signed C++ runtime beside them keeps the lookup, because
it does not carry firefox.exe's version.

## Our files

- `toolkit/xre/dllservices/StealthOwnBinaries.h/.cpp`, namespace `mozilla`: `StealthIsInDirectoryOf(aModulePath, aExeFilePath)`
  (path-prefix test, case-insensitive, no state), `StealthSkipsSignatureLookup(aPath, aVerInfo, aHasVersion)`
  (the whole decision: a version resource, and `IsOwnUnsignedBinary`, which compares
  the file version of the module with that of the running exe), `StealthSkipsSignatureLookupOf(aPath)` (the same decision from
  the path alone: it reads the version resource of the module itself, a second read of the same file, invisible to a page) and
  `StealthSignatureLookupUnlessOwn(aPath, aServices)` (it gives back the object that Mozilla's call is made on: an object that
  forwards `GetBinaryOrgName` to the services with the arguments it is given, except for one of this build's own unsigned binaries,
  for which no lookup is made, the answer is null, as the lookup would have answered after its catalog search, and the skip is counted;
  the decision is made before the arguments are evaluated, which read nothing).
- `toolkit/xre/dllservices/tests/gtest/TestStealthOwnBinaries.cpp`: suite StealthOwnBinaries.

## Hooks in Mozilla files

- `toolkit/xre/dllservices/UntrustedModulesData.cpp`:
  - registration: `#include "StealthOwnBinaries.h"` in a block of ours after Mozilla's includes.
  - in ModuleRecord::GetVersionAndVendorInfo, one wrapped line (wrap-expression): the receiver of Mozilla's call, `dllSvc`, becomes
    `StealthSignatureLookupUnlessOwn(aPath, dllSvc)`, so the statement reads
    `UniquePtr<wchar_t[]> signedBy(StealthSignatureLookupUnlessOwn(aPath, dllSvc)->GetBinaryOrgName(` and its next two lines,
    `PromiseFlatString(aPath).get(), &hasNestedMicrosoftSignature,` and `AuthenticodeFlags::SkipTrustVerification));`, are Mozilla's
    unchanged. The skip avoids a call that Mozilla makes unconditionally, in a declaration that the lines after it read, so it is
    decided by the receiver; GetBinaryOrgName is shared with ExternalAgentBackend, so its callee is not guarded. `aPath` is a
    parameter and `dllSvc` is the services object Mozilla's function already holds. Mozilla's version read
    (`ModuleVersionInfo verInfo; if (!verInfo.GetFromImage(aPath)) {`) stays where it is, after the lookup; our function reads the version
    resource itself.
- `toolkit/xre/dllservices/moz.build`: `UNIFIED_SOURCES += ["StealthOwnBinaries.cpp"]`, after the closing `]` of the list.
- `toolkit/xre/dllservices/tests/gtest/moz.build`: `UNIFIED_SOURCES += ["TestStealthOwnBinaries.cpp"]`, after the closing `]`.
