/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthMouseEventIPC_h
#define mozilla_StealthMouseEventIPC_h

#include "ipc/IPCMessageUtils.h"
#include "mozilla/MouseEvents.h"

namespace IPC {

/**
 * Stealthfox [B217]: the id of a Juggler mouse event travels with the event
 * (WidgetMouseEventBase::mJugglerEventId, automation/input/FEATURE.md). The
 * write is one line after the last field of
 * ParamTraits<WidgetMouseEventBase>::WriteForDerivedClass; this is the read,
 * the last link of the && chain of ReadForDerivedClass, which wraps Mozilla's
 * read of the field before it (mInputSource): aReadSoFar is that read's result,
 * and the id is read only when it succeeded, as the chain short-circuits.
 * The stream order is the order of the write.
 */
inline bool StealthReadJugglerEventId(MessageReader* aReader,
                                      mozilla::WidgetMouseEventBase* aResult,
                                      bool aReadSoFar) {
  return aReadSoFar && ReadParam(aReader, &aResult->mJugglerEventId);
}

}  // namespace IPC

#endif  // mozilla_StealthMouseEventIPC_h
