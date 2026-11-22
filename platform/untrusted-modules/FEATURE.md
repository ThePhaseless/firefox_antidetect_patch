# platform/untrusted-modules

Category: other
Prefs: none read directly
Test: toolkit/xre/dllservices/tests/gtest/TestStealthOwnBinaries.cpp (gtest:StealthOwnBinaries.BesideTheExeAndBelowIt, StealthOwnBinaries.CaseInsensitiveAsWindowsPathsAre, StealthOwnBinaries.ElsewhereKeepsTheLookup, StealthOwnBinaries.StealthSkipsSignatureLookup; Windows)

## What it does

A performance fix, not a value a page reads. The "Untrusted Modules" thread
looked up the Authenticode signature of every module, including this build's
own binaries (beside firefox.exe and carrying its file version). Those carry no
Authenticode signature, so the lookup always fell through to the catalog
search, which hashes the whole file and walks every system catalog: 1.26 s of
CPU per launch (profile of 2026-10-27), for an answer that cannot exist. The
lookup is skipped for them. The classification does not change: GetTrust
classifies them as before, FirefoxDirectory (+AndVersion), from their path and
version resource. The signed C++ runtime beside them keeps the lookup, because
it does not carry firefox.exe's version.

## Our files

- `toolkit/xre/dllservices/StealthOwnBinaries.h/.cpp`: `StealthIsInDirectoryOf(aModulePath, aExeFilePath)`
  (path-prefix test, case-insensitive, no state) and `StealthSkipsSignatureLookup(aPath, aVerInfo, aHasVersion)`
  (the whole decision: a version resource, and `IsOwnUnsignedBinary`, which compares
  the file version of the module with that of the running exe).
- `toolkit/xre/dllservices/tests/gtest/TestStealthOwnBinaries.cpp`: suite StealthOwnBinaries.

## Hooks in Mozilla files

- `toolkit/xre/dllservices/UntrustedModulesData.cpp`:
  - registration: `#include "StealthOwnBinaries.h"` in a block of ours after Mozilla's includes.
  - rewrite in ModuleRecord::GetVersionAndVendorInfo (open, a decision of the pm): the version read (`verInfo`/`GetFromImage`) moves above the signature lookup, and the lookup is replaced by `StealthSkipsSignatureLookup(aPath, verInfo, hasVersion) ? nullptr : dllSvc->GetBinaryOrgName(...)`. The decision needs the file's version, which Mozilla reads after the lookup, and has to skip a call Mozilla makes unconditionally: no guard (GetBinaryOrgName is shared with ExternalAgentBackend), no wrap-function and no wrap-expression of a computed value fit.
- `toolkit/xre/dllservices/moz.build`: `UNIFIED_SOURCES += ["StealthOwnBinaries.cpp"]`, after the closing `]` of the list.
- `toolkit/xre/dllservices/tests/gtest/moz.build`: `UNIFIED_SOURCES += ["TestStealthOwnBinaries.cpp"]`, after the closing `]`.
