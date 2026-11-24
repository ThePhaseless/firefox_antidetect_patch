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
lookup is skipped for them: Mozilla's lookup statements stay as Mozilla wrote them, in a thunk that our function decides to call. The classification does not change: GetTrust
classifies them as before, FirefoxDirectory (+AndVersion), from their path and
version resource. The signed C++ runtime beside them keeps the lookup, because
it does not carry firefox.exe's version.

## Our files

- `toolkit/xre/dllservices/StealthOwnBinaries.h/.cpp`, namespace `mozilla`: `StealthIsInDirectoryOf(aModulePath, aExeFilePath)`
  (path-prefix test, case-insensitive, no state), `StealthSkipsSignatureLookup(aPath, aVerInfo, aHasVersion)`
  (the whole decision: a version resource, and `IsOwnUnsignedBinary`, which compares
  the file version of the module with that of the running exe), `StealthSkipsSignatureLookupOf(aPath)` (the same decision from
  the path alone: it reads the version resource of the module itself, a second read of the same file, invisible to a page) and
  `StealthSignatureLookupUnlessOwn(aPath, aSignatureLookup)` (a template: it calls the thunk, which is Mozilla's signature lookup,
  unless the module is one of this build's own unsigned binaries, and then answers null, as the lookup would have after its
  catalog search).
- `toolkit/xre/dllservices/tests/gtest/TestStealthOwnBinaries.cpp`: suite StealthOwnBinaries.

## Hooks in Mozilla files

- `toolkit/xre/dllservices/UntrustedModulesData.cpp`:
  - registration: `#include "StealthOwnBinaries.h"` in a block of ours after Mozilla's includes.
  - in ModuleRecord::GetVersionAndVendorInfo, a declared exception of kind `skip`: Mozilla's statement
    `UniquePtr<wchar_t[]> signedBy(dllSvc->GetBinaryOrgName(PromiseFlatString(aPath).get(), &hasNestedMicrosoftSignature,
    AuthenticodeFlags::SkipTrustVerification));` keeps its text, inside a lambda handed to our function:
    `UniquePtr<wchar_t[]> signedBy = StealthSignatureLookupUnlessOwn(aPath, [&]() {` opens the thunk, Mozilla's statement
    follows inside it (its three lines carry the marker), `return signedBy;` ends the thunk and `});` closes it. The skip has to avoid a call Mozilla
    makes unconditionally, and the statement is a declaration that the lines after it read, so no guard, prefix `if` or `if/else`
    can skip it without moving it out of scope; GetBinaryOrgName is shared with ExternalAgentBackend, so its callee is not
    guarded. The lambda passes no local of Mozilla's function (`aPath` is a parameter). Mozilla's version read
    (`ModuleVersionInfo verInfo; if (!verInfo.GetFromImage(aPath)) {`) stays where it is, after the lookup; our function reads the version
    resource itself.
- `toolkit/xre/dllservices/moz.build`: `UNIFIED_SOURCES += ["StealthOwnBinaries.cpp"]`, after the closing `]` of the list.
- `toolkit/xre/dllservices/tests/gtest/moz.build`: `UNIFIED_SOURCES += ["TestStealthOwnBinaries.cpp"]`, after the closing `]`.
