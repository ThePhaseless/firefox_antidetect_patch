/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*-
 * vim: set ts=8 sts=2 et sw=2 tw=80:
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef vm_StealthStackFrames_h
#define vm_StealthStackFrames_h

#include <stddef.h>
#include <string.h>

#include "js/GCAPI.h"       // JS::AutoCheckCannotGC
#include "js/RootingAPI.h"  // JS::Handle, JS::MutableHandle
#include "js/TypeDecls.h"   // JS::Latin1Char
#include "vm/SavedFrame.h"  // js::SavedFrame
#include "vm/StringType.h"  // JSAtom, JSLinearString accessors

// Stealth: skip Juggler's frames from stack traces visible to web content.
// A commercial fingerprinting service detects automation by checking
// Error.stack for juggler/debugger-specific frame sources. Juggler loads from
// resource://gre/modules/juggler/ (juggler/moz.build says why it is not a
// chrome package).
//
// True if a stack frame whose source is |source| belongs to Juggler, i.e. the
// source starts with resource://gre/modules/juggler/. BuildStackString
// (js/src/vm/SavedStacks.cpp) drops such frames from every stack string.
// |source| may be null (returns false). Does not GC and does not allocate.
//
// Header-only on purpose: no line is added to js/src/vm/moz.build.
inline bool StealthIsJugglerFrameSource(JSAtom* source) {
  static constexpr char kJuggler[] = "resource://gre/modules/juggler/";
  static constexpr size_t kJugglerLength = sizeof(kJuggler) - 1;

  if (!source || source->length() < kJugglerLength) {
    return false;
  }

  JS::AutoCheckCannotGC nogc;
  if (source->hasLatin1Chars()) {
    const JS::Latin1Char* chars = source->latin1Chars(nogc);
    return memcmp(chars, kJuggler, kJugglerLength) == 0;
  }

  const char16_t* chars = source->twoByteChars(nogc);
  for (size_t i = 0; i < kJugglerLength; i++) {
    if (chars[i] != char16_t(kJuggler[i])) {
      return false;
    }
  }
  return true;
}

// BuildStackString, in its walk over the frames, right after it has found the
// next frame to show (|aNextFrame|): when the current frame |aFrame| is one of
// Juggler's, the walk moves on to the next frame, carrying the async flag of
// that step, and this answers true so that the hook's `continue` skips the
// frame in Mozilla's own loop. Otherwise it changes nothing and answers false.
// The three effects (|aFrame| = |aNextFrame|, |*aSkippedAsync| =
// |aSkippedNextAsync|, the loop's `continue`) are the three statements the hook
// used to carry inline.
inline bool StealthSkipJugglerFrame(JS::MutableHandle<js::SavedFrame*> aFrame,
                                    JS::Handle<js::SavedFrame*> aNextFrame,
                                    bool* aSkippedAsync,
                                    bool aSkippedNextAsync) {
  if (!StealthIsJugglerFrameSource(aFrame->getSource())) {
    return false;
  }
  aFrame.set(aNextFrame.get());
  *aSkippedAsync = aSkippedNextAsync;
  return true;
}

#endif  // vm_StealthStackFrames_h
