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
#include "vm/SavedStacks.h"  // js::UnwrapSavedFrame
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

// BuildStackString walks the frames of a stack and shows every one the reader
// may see. Juggler's frames are not shown, and the walk never meets one: the
// two places where it takes a frame to show are replaced by these functions,
// which give back the first frame that is not Juggler's.
//
// The async flag is the one of the step that found the frame that is given back:
// the step from the last of Juggler's frames to it, or the step Mozilla's own
// call made when none was skipped. The flag of a step over a frame of
// Juggler's is not carried, as when the walk skipped such a frame itself: the
// frame was shown to nobody, and what it stood for (an async link above it, its
// own asyncCause) is not told by the frame that follows.
//
// Mozilla's own call that the hook replaces is js::UnwrapSavedFrame for the
// first frame (public, declared in vm/SavedStacks.h), and for the next frame
// js::GetFirstSubsumedFrame, which is private to SavedStacks.cpp: the next frame
// after a frame of Juggler's is found with js::UnwrapSavedFrame of its parent,
// which is the same search (it unwraps the frame it is given, which is a plain
// SavedFrame here, and then calls GetFirstSubsumedFrame) with the same flag.
//
// The first frame of the stack: js::UnwrapSavedFrame, as Mozilla's call, then,
// while the frame is Juggler's, the first subsumed frame of its parent.
//
// V8 format marks the last frame by the absence of a next one. When Juggler's
// frames end the stack, Mozilla's loop met the first of them as the next frame
// of the last one shown, so that frame was not the last and kept its newline.
// StealthFirstVisibleFrame notes, for the frame it is asked about, that it
// dropped such a tail, and StealthIsLastFrame answers the loop's `!nextFrame`
// with that in mind: the same output as the loop that skipped the frames itself.
inline bool& StealthJugglerTailDropped() {
  static thread_local bool sDropped = false;
  return sDropped;
}

inline js::SavedFrame* StealthUnwrapVisibleFrame(
    JSContext* aCx, JSPrincipals* aPrincipals, JS::Handle<JSObject*> aStack,
    JS::SavedFrameSelfHosted aSelfHosted, bool& aSkippedAsync,
    bool* aDroppedJuggler = nullptr) {
  JS::Rooted<js::SavedFrame*> frame(
      aCx,
      js::UnwrapSavedFrame(aCx, aPrincipals, aStack, aSelfHosted, aSkippedAsync));
  while (frame && StealthIsJugglerFrameSource(frame->getSource())) {
    if (aDroppedJuggler) {
      *aDroppedJuggler = true;
    }
    JS::Rooted<JSObject*> parent(aCx, frame->getParent());
    // GetFirstSubsumedFrame of no frame says "no async frame skipped": so does this.
    aSkippedAsync = false;
    frame = js::UnwrapSavedFrame(aCx, aPrincipals, parent, aSelfHosted,
                                 aSkippedAsync);
  }
  return frame;
}

// The next frame of the walk: the first frame from |aFrame| (the parent of the
// frame being shown) that the reader may see and that is not Juggler's.
// |aFirstSubsumed| is Mozilla's own search for it, js::GetFirstSubsumedFrame,
// which this function cannot name (it is private to SavedStacks.cpp); the hook
// passes the same arguments Mozilla's call had.
inline js::SavedFrame* StealthFirstVisibleFrame(
    JSContext* aCx, JSPrincipals* aPrincipals, JS::Handle<js::SavedFrame*> aFrame,
    JS::SavedFrameSelfHosted aSelfHosted, bool& aSkippedAsync) {
  JS::Rooted<JSObject*> from(aCx, aFrame.get());
  // GetFirstSubsumedFrame of no frame says "no async frame skipped", and
  // UnwrapSavedFrame of no frame leaves the flag alone: so the flag is set here.
  aSkippedAsync = false;
  bool droppedJuggler = false;
  js::SavedFrame* const next = StealthUnwrapVisibleFrame(
      aCx, aPrincipals, from, aSelfHosted, aSkippedAsync, &droppedJuggler);
  StealthJugglerTailDropped() = droppedJuggler && !next;
  return next;
}

// BuildStackString's `!nextFrame` for the V8 format, right after the call above for the same frame: no next frame, and no
// tail of Juggler's frames dropped after this one.
inline bool StealthIsLastFrame(bool aNoNextFrame) {
  return aNoNextFrame && !StealthJugglerTailDropped();
}

#endif  // vm_StealthStackFrames_h
