# platform/script-cache

Category: other
Prefs: none read directly
Test: end to end in the wrapper (tests/test_script_cache_written_is_adopted_e2e.py: test_a_fresh_profile_reports_its_written_cache_as_mapped)

## What it does

Not a value a page reads: a memory optimisation of the startup script cache.
With a warm profile the cache is a file mapping and costs no heap (mXDRRange
points into mCacheData, IsMemMapped() is true, FreeData() has nothing to free).
With a fresh profile the same bytes were built in memory for the write and stay
anonymous heap for the whole session (16.52 MB measured in the parent process,
unchanged between 40 s and 180 s, with the 13,343,940-byte file already on
disk). After ScriptPreloader::WriteCache has written and moved the file, the
file is mapped and every entry is re-pointed into the mapping; the heap buffers
and stencils that became redundant are released. The first session ends in the
state the second one starts in.

- The adoption happens once: AutoMemMap::init asserts `!fd` in debug and, in
  release, a second init would overwrite fd and addr and leave the mXDRRange of
  the entries already adopted dangling. A second write (the cache invalidation
  can trigger one during shutdown) keeps the heap copies of its entries, as
  before, and the first mapping stays alive as long as the instance.
- An entry whose stencil borrows the buffer (JS::StencilIsBorrowed) or whose
  size differs from the file's is left as it is.
- A failed adoption is not an error of the write: the file is valid, the
  session goes on with the heap copies, and the failure is logged.
- The mapping is reported as `explicit/script-preloader/non-heap/memmapped-written-cache`,
  so the bytes that left the heap reappear somewhere in the memory report.
- The header reading in StealthAdoptWrittenCache is a copy of InitCacheInternal's
  arithmetic and checks, reader side; if InitCacheInternal changes, it must change.
- `mStealthWrittenCacheData` is a member by value, declared between mCacheData
  and mMonitor: that position fixes the destruction order. The mapping lives as
  long as the instance because the entries' mXDRRange point into it, so
  destroying it earlier would leave them dangling; it is a member by value
  because it must not outlive the instance (mCacheData, a pointer to a static,
  does so only because of how the singleton is built). The position must not change.

## Our files

- `js/xpconnect/loader/StealthScriptCache-inl.h`: the definitions of the two
  members `ScriptPreloader::StealthAdoptWrittenCache` and
  `ScriptPreloader::StealthReportWrittenCache`. Not a header: it is included
  only by ScriptPreloader.cpp, as the last thing in the file, because it uses
  the file-static MAGIC and the anonymous-namespace gLog (copying MAGIC would
  go stale silently). Not listed in moz.build.

## Hooks in Mozilla files

- `js/xpconnect/loader/ScriptPreloader.cpp`:
  - registration: `#include "StealthScriptCache-inl.h"` at the end of the file, in a block of ours after `}  // namespace mozilla`.
  - anchor in ScriptPreloader::WriteCache: `StealthAdoptWrittenCache(cacheFile);` right after `MOZ_TRY(cacheFile->MoveTo(nullptr, mBaseName + u".bin"_ns));`: it needs the local `cacheFile`, updated by MoveTo to the final path, and only on the path that wrote a file (a wrap of WriteCache cannot tell whether a file was written; a guard at the head cannot see a file that does not exist yet).
  - anchor in ScriptPreloader::CollectReports: `StealthReportWrittenCache(aHandleReport, aData);` after the last MOZ_COLLECT_REPORT block, before `return NS_OK;`. Kept where it is: at the head it would change the order of the report callbacks.
- `js/xpconnect/loader/ScriptPreloader.h`: members `StealthAdoptWrittenCache` (after GetCacheFile), `StealthReportWrittenCache` (after FinishContentStartup) and the field `mStealthWrittenCacheData` (after mCacheData, before mMonitor).
