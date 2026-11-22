/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthInputEventBirth.h"

#include "mozilla/TextInputProcessor.h"
#include "nsContentUtils.h"

namespace mozilla {

/**
 * Stealthfox [B299]: nsITextInputProcessor.setNextKeyLatency(). Declared by
 * the idl line of the interface (NS_DECL_NSITEXTINPUTPROCESSOR), defined here
 * and not in TextInputProcessor.cpp: chrome only, as the rest of the
 * interface, then the latency and the page of the next key are stored in the
 * processor's field mStealthKeyBirth, for the scope that keydown(), keyup()
 * and commitCompositionWith() open to take.
 */
NS_IMETHODIMP TextInputProcessor::SetNextKeyLatency(double aLatencyMs,
                                                    uint64_t aPageId) {
  return StealthSetNextKeyLatency(mStealthKeyBirth, aLatencyMs, aPageId,
                                  nsContentUtils::IsCallerChrome());
}

}  // namespace mozilla
