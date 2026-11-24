# fingerprint/audio/context-values

Category: spoof
Prefs: zoom.stealth.audio.max_channel_count, zoom.stealth.audio.output_latency_ms
Test: wrapper:tests/test_audio_context_values_are_declared_e2e.py::test_output_latency_and_max_channel_count_are_the_declared_ones (the existing wrapper:tests/test_fingerprint_surface.py::test_pin_audio_max_channels_lands_in_destination also covers maxChannelCount)

## What it does

`AudioContext.outputLatency` and `AudioDestinationNode.maxChannelCount` are values Firefox reads from the audio backend (cubeb) of the host. The launcher declares them with `zoom.stealth.audio.output_latency_ms` (milliseconds) and `zoom.stealth.audio.max_channel_count`; when a pref is > 0 the page gets the declared value, before Mozilla's reduceFingerprinting branch and before the backend is read, so the host value is never read. With a pref <= 0 (the default) Mozilla's own computation runs unchanged.

## Hooks in Mozilla files

All in `dom/media/webaudio/AudioContext.cpp`; own code in `dom/media/webaudio/StealthAudioContextValues.h` (header only, inline `StealthAudioOutputLatency(double*)` and `StealthAudioMaxChannelCount(uint32_t*)`, each true and the value when its pref is > 0).

- registration: `#include "StealthAudioContextValues.h"` in our block after Mozilla's includes.
- anchor, `AudioContext::OutputLatency`: `if (double stealth; StealthAudioOutputLatency(&stealth)) return stealth;` right after Mozilla's `if (mIsShutDown) { return 0.0; }` block. It is an anchor, not a head guard, because the head guard would have to redo Mozilla's shut-down check (a shut-down context answers 0.0 even when a latency is declared); the value and the position are those of the patch before the rework.
- guard, `AudioContext::MaxChannelCount`: `if (uint32_t stealth; StealthAudioMaxChannelCount(&stealth)) return stealth;` as the first statement, before Mozilla's resistFingerprinting branch (which returns 2) and the cubeb read (`CubebUtils::MaxNumberOfChannels`).
