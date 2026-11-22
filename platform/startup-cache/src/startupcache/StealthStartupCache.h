/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Whether a StartupCache write may run with lowered I/O priority
// (nsAutoLowPriorityIO).
//
// It may not. The write holds mTableLock from its first entry to its last,
// and the main thread takes the same lock in GetBuffer() for every module it
// loads, so a starved writer is a starved main thread. On Windows the lowered
// priority is THREAD_MODE_BACKGROUND_BEGIN, which lowers the thread's CPU
// priority as well as its I/O, and the write compresses every entry with
// LZ4 HC. Upstream saw it at shutdown (bug 2037923) and exempted only that
// write; the first regular write, about 30 s after a launch, is the same
// inversion. Measured on 2026-10-28 with eleven browsers at once on Windows:
// the parent's main thread stood in GetBuffer() for 7-27 s with its CPU idle,
// behind a pool thread in WriteToDisk(), in 10 runs of 11, and nothing it
// owed the pages or the automation pipe went out meanwhile. With background
// mode refused from outside, the same runs never waited more than 4.5 s and
// the writes took 0.7-2 s. 151 had no lowered priority here.

#ifndef STEALTH_STARTUP_CACHE_H_
#define STEALTH_STARTUP_CACHE_H_

namespace mozilla {
namespace scache {

constexpr bool kStealthWritesMayLowerIOPriority = false;

// MaybeWriteOffMainThread's write: aWanted is what Mozilla asked for.
constexpr bool StealthWritesMayLowerIOPriority(bool aWanted) {
  return aWanted && kStealthWritesMayLowerIOPriority;
}

}  // namespace scache
}  // namespace mozilla

#endif  // STEALTH_STARTUP_CACHE_H_
