/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// platform/script-cache: after the startup script cache is written, adopt the
// cache file we just wrote in place of the heap copies of the same bytes.
//
// Included ONLY by ScriptPreloader.cpp, as the very last thing in the file,
// after "}  // namespace mozilla". It is not a header and cannot be compiled on
// its own: it needs three things that exist only inside that translation unit,
// namely the file-static MAGIC, the anonymous-namespace gLog and the
// using-directives of the file (mozilla::loader, JS), which it inherits by
// reopening namespace mozilla. LOG is already #undef'd at that point, so
// MOZ_LOG is used directly. It must not be listed in moz.build.
//
// Both functions are members of ScriptPreloader (declared in
// ScriptPreloader.h), so the private state (mScripts, mMonitor,
// mStealthWrittenCacheData and the nested type CachedStencil) is reached with no
// friend declaration and no accessor.
//
// Comment of the member `AutoMemMap mStealthWrittenCacheData` (declared in
// ScriptPreloader.h between mCacheData and mMonitor, a position that fixes the
// destruction order and must not change):
//
//   The mapping of the file we WROTE in this session, after
//   StealthAdoptWrittenCache adopted it. It lives as long as the instance,
//   because the mXDRRange of the entries point inside it: destroying it earlier
//   would leave them dangling.
//
//   It is a member by value and not a pointer to a static like mCacheData
//   because it must not outlive the instance - mCacheData does so only because
//   of how the singleton is built, not because of a lifetime requirement.

#ifndef StealthScriptCache_inl_h
#define StealthScriptCache_inl_h

#include <inttypes.h>
#include <string.h>

#include "mozilla/UniquePtr.h"

namespace mozilla {

void ScriptPreloader::StealthReportWrittenCache(
    nsIHandleReportCallback* aHandleReport, nsISupports* aData) {
  // The mapping of the file written in THIS session, adopted in place of the
  // heap copies (StealthAdoptWrittenCache). It must be reported, otherwise the
  // megabytes vanish from the heap and show up nowhere else, and a total that
  // does not add up is indistinguishable from a real saving.
  MOZ_COLLECT_REPORT(
      "explicit/script-preloader/non-heap/memmapped-written-cache",
      KIND_NONHEAP, UNITS_BYTES,
      mStealthWrittenCacheData.nonHeapSizeOfExcludingThis(),
      "The cache file this session wrote, mapped read-only and adopted in "
      "place of the heap copies of the same bytes.");
}

// After writing the cache file, adopt the bytes of the FILE in place of the
// heap copies: map the file just written and repoint every entry inside the
// mapping, freeing the buffers and stencils that become redundant.
//
// Why it exists. With a WARM profile this cache is a file mapping and costs no
// heap: mXDRRange points inside mCacheData, IsMemMapped() is true and
// FreeData() has nothing to free. With a FRESH profile the same bytes are
// anonymous heap, because they were built in memory for the write, and they
// stay there for the whole session: measured 16.52 MB in the parent process,
// unchanged between 40 s and 180 s, with the 13,343,940-byte file already on
// disk. This brings the first session to the same state as the second.
//
// The bytes are on disk: from here on keeping a copy on the heap means having
// the same thing twice. MoveTo updates `cacheFile` to the new location, so it
// is the file to map (the caller, WriteCache, passes it right after MoveTo).
//
// It returns nothing: the only caller (WriteCache) used to log the error and
// carry on, so the logging lives here and the hook is a single line. The text
// of the two log messages is the same as before.
void ScriptPreloader::StealthAdoptWrittenCache(nsIFile* aCacheFile) {
  auto adopt = [&]() -> Result<Ok, nsresult> {
    // Adopt ONLY ONCE, and this is not a theoretical precaution.
    // AutoMemMap::init opens with MOZ_ASSERT(!fd): in debug it fires, in
    // RELEASE the assert is not there and the second init would overwrite fd
    // and addr, leaving the mXDRRange of the entries already adopted DANGLING -
    // that is, pointers inside an unmapped region, which is a crash and not a
    // degradation.
    //
    // A second write can happen: the comment in Run() says that the cache
    // invalidation "can trigger a new write during shutdown". In that case the
    // entries of that moment keep their heap copies, which is the previous
    // behaviour, and the old mapping stays alive as long as the instance
    // lives.
    if (mStealthWrittenCacheData.initialized()) {
      return Ok();
    }

    MOZ_TRY(mStealthWrittenCacheData.init(aCacheFile));

    mMonitor.AssertNotCurrentThreadOwns();
    MonitorAutoLock mal(mMonitor);

    size_t adopted = 0;
    size_t borrowed = 0;

    // Reading the header of the mapped file: the same arithmetic and the same
    // checks as InitCacheInternal, READER side. The WRITER computes the start
    // of the data section as MAGIC + headerSize + header, without the 4 bytes
    // of the crc that it does write, while the READER counts them. The two
    // formulas give the same result only because the alignment is a divisor of
    // 4. This is a copy of InitCacheInternal (which stays as it is in Mozilla):
    // if that one changes, this one must change too.
    auto size = mStealthWrittenCacheData.size();

    uint32_t headerSize;
    uint32_t crc;
    if (size < sizeof(MAGIC) + sizeof(headerSize) + sizeof(crc)) {
      return Err(NS_ERROR_UNEXPECTED);
    }

    auto data = mStealthWrittenCacheData.get<uint8_t>();
    MOZ_RELEASE_ASSERT(JS::IsTranscodingBytecodeAligned(data.get()));

    auto end = data + size;

    if (memcmp(MAGIC, data.get(), sizeof(MAGIC))) {
      return Err(NS_ERROR_UNEXPECTED);
    }
    data += sizeof(MAGIC);

    headerSize = LittleEndian::readUint32(data.get());
    data += sizeof(headerSize);

    crc = LittleEndian::readUint32(data.get());
    data += sizeof(crc);

    if (data + headerSize > end) {
      return Err(NS_ERROR_UNEXPECTED);
    }

    if (crc != ComputeCrc32c(~0, data.get(), headerSize)) {
      return Err(NS_ERROR_UNEXPECTED);
    }

    Range<const uint8_t> header(data, data + headerSize);
    data += headerSize;

    // Reconstruct alignment padding if required.
    size_t currentOffset = data - mStealthWrittenCacheData.get<uint8_t>();
    data += JS::AlignTranscodingBytecodeOffset(currentOffset) - currentOffset;

    InputBuffer buf(header);

    size_t offset = 0;
    while (!buf.finished()) {
      auto script = MakeUnique<CachedStencil>(*this, buf);
      MOZ_RELEASE_ASSERT(script);

      auto scriptData = data + script->mOffset;
      if (!JS::IsTranscodingBytecodeAligned(scriptData.get())) {
        return Err(NS_ERROR_UNEXPECTED);
      }

      if (scriptData + script->mSize > end) {
        return Err(NS_ERROR_UNEXPECTED);
      }

      // Make sure offsets match what we'd expect based on script ordering and
      // size, as a basic sanity check.
      if (script->mOffset != offset) {
        return Err(NS_ERROR_UNEXPECTED);
      }
      offset += script->mSize;

      script->mXDRRange.emplace(scriptData, scriptData + script->mSize);

      auto* live = mScripts.Get(script->mCachePath);
      if (!live) {
        continue;
      }

      // A stencil that BORROWS the buffer cannot be left behind: destroying
      // the buffer under it would give dangling pointers, and releasing our
      // reference is not enough, because someone else may hold one. This entry
      // stays as it is.
      if (live->mStencil && JS::StencilIsBorrowed(live->mStencil)) {
        borrowed++;
        continue;
      }

      // The bytes must be the same, not only the key.
      if (live->mSize != script->mSize) {
        continue;
      }

      // Replace the heap copy with the same bytes taken from the mapped cache
      // file. After this step IsMemMapped() is true, so FreeData() is again
      // the correct no-op and there is nothing left to free: the only copy of
      // the bytes is the file.
      //
      // It has already been verified (above) that no stencil is BORROWING the
      // buffer (JS::StencilIsBorrowed), otherwise destroying it here would
      // leave the stencil with dangling pointers.
      live->mXDRRange.reset();
      if (!live->mXDRData.empty()) {
        live->mXDRData.destroy();
      }
      live->mXDRRange.emplace(script->Range());

      // And the stencil goes away with them. It is not a cache loss: it is
      // exactly the state this entry is in at the NEXT startup, where mStencil
      // is null and GetStencil decodes from the mapped range. The first session
      // stops being the special case that pays twice.
      live->mStencil = nullptr;
      adopted++;
    }

    if (buf.error()) {
      return Err(NS_ERROR_UNEXPECTED);
    }

    MOZ_LOG(gLog, LogLevel::Info,
            ("Adopted the written cache: %zu scripts, %zu left borrowed\n",
             adopted, borrowed));
    return Ok();
  };

  // If the adoption fails it is not an error of the WRITE: the file is valid
  // and the session carries on with the previous behaviour, that is, the heap
  // copies. It is logged and we go on, because failing the write for a missed
  // optimization would be worse than the problem it solves.
  if (auto result = adopt(); result.isErr()) {
    MOZ_LOG(gLog, LogLevel::Info,
            ("Could not adopt the written cache (0x%" PRIx32 "), keeping the "
             "heap copies\n",
             static_cast<uint32_t>(result.unwrapErr())));
  }
}

}  // namespace mozilla

#endif  // StealthScriptCache_inl_h
