/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef DOM_MEDIA_WEBAUDIO_STEALTHAUDIOCONTEXTVALUES_H_
#define DOM_MEDIA_WEBAUDIO_STEALTHAUDIOCONTEXTVALUES_H_

#include <stdint.h>

#include "mozilla/StaticPrefs_zoom.h"

// The two values of an AudioContext that Firefox reads from the audio
// backend (cubeb), declared by the launcher instead. Each function returns
// true and the declared value when its pref is > 0; when it returns false
// nothing is declared and Mozilla's own computation runs.

// AudioContext.outputLatency, in seconds. zoom.stealth.audio.output_latency_ms
// is in milliseconds. Called right after Mozilla's shut-down check in
// AudioContext::OutputLatency, before its reduceFingerprinting branch and the
// backend read.
inline bool StealthAudioOutputLatency(double* aOut) {
  int32_t latency_ms =
      mozilla::StaticPrefs::zoom_stealth_audio_output_latency_ms();
  if (latency_ms > 0) {
    *aOut = latency_ms / 1000.0;
    return true;
  }
  return false;
}

// AudioDestinationNode.maxChannelCount (AudioContext::MaxChannelCount).
inline bool StealthAudioMaxChannelCount(uint32_t* aOut) {
  int32_t ch = mozilla::StaticPrefs::zoom_stealth_audio_max_channel_count();
  if (ch > 0) {
    *aOut = (uint32_t)ch;
    return true;
  }
  return false;
}

#endif  // DOM_MEDIA_WEBAUDIO_STEALTHAUDIOCONTEXTVALUES_H_
