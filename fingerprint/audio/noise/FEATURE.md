# fingerprint/audio/noise

Category: spoof
Prefs: zoom.stealth.audio.fp_noise, zoom.stealth.fpp.hw_seed
Test: gtest dom/media/gtest/TestStealthAudioNoise.cpp (StealthAudioNoise.*, 10 tests: bit-for-bit against the reference computation, and unchanged when the seed is absent or the switch is off); wrapper e2e tests/test_audio_noise_e2e.py::test_audio_values_follow_the_seed_only_when_fp_noise_is_on (the four values a page reads, equal for equal seeds, different between seeds, equal between seeds when fp_noise is false); registered in the same `dom/media/gtest/moz.build` hunk, and named by its hooks, the gtests of other folders: `StealthMediaDeclaration.SupportsAsyncAnswersFromTheDeclaration` (fingerprint/media/decode-declaration), `StealthMediaEnumeration.WithADeclarationTheCallbackRunsLaterWithTheSameValue` (fingerprint/media/enumeration)

## What it does

Adds a per-session perturbation to the audio values a page can read back, so the sums it computes over them differ between sessions while one session always sees the same numbers. It is on only when `zoom.stealth.fpp.hw_seed` is positive and `zoom.stealth.audio.fp_noise` is true (the wrapper ships the switch false). Four sites: `getFloatFrequencyData` (0.05 to 0.25 dB), `getFloatTimeDomainData` (5e-5 to 2.5e-4 on samples in [-1, 1], no length guard, silent or not), the buffer an `OfflineAudioContext` renders (5e-7 to 2.5e-6, skipping silent channels, contexts of 200 frames or fewer and the first 100 samples), and `DynamicsCompressorNode.reduction` (within +-1e-5). The logic is all in `StealthAudioNoise.cpp`; the hooks only call it.

## Hooks in Mozilla files

- `dom/media/webaudio/AnalyserNode.cpp`, `AudioDestinationNode.cpp`: `#include "StealthAudioNoise.h"` in a block of ours after Mozilla's includes (registration).
- `AnalyserNode.cpp`, `AnalyserNode::GetFloatFrequencyData` (anchor): `StealthAddFrequencyNoise(aData, length);` right after the loop that writes the decibel values, as the last line of the ProcessData lambda (the noise needs what the loop wrote). A function wrap is not used: when `FFTAnalysis()` fails Mozilla returns without writing and the noise would land on unwritten data; wrapping the 2-line decibel expression would rewrite 2 Mozilla lines.
- `AnalyserNode.cpp`, `AnalyserNode::GetFloatTimeDomainData` (anchor): `StealthAddTimeDomainNoise(aData, length);` right after `GetTimeDomainData(aData.Elements(), length);`, last line of the lambda. `GetTimeDomainData` itself is not wrapped because the Byte variant calls it too and must stay unperturbed.
- `AudioDestinationNode.cpp`, `OfflineDestinationNodeEngine::ProcessBlock` (anchor, one line): `StealthAddOfflineAudioNoise(aInput.IsNull(), i, inputChannelCount, mWriteIndex, mLength, duration, outputData);` right after the copy loop of each channel, last line of the channel block. The class is local to the .cpp, so no function of ours can wrap it, and the noise needs what the copy loop wrote and the not yet advanced `mWriteIndex`; it does not move after the channel loop.
- `DynamicsCompressorNode.h`: the declaration of `StealthPerturbCompressorReduction` (the header is exported and cannot include ours; `SetReduction` is inline) and `aReduction = StealthPerturbCompressorReduction(aReduction);` at the top of `SetReduction` (a pure addition, as on the 68 base; Mozilla's `mReduction = aReduction;` is intact, 0 Mozilla lines rewritten).
- `dom/media/webaudio/moz.build`, `dom/media/gtest/moz.build`: one `UNIFIED_SOURCES +=` line each, after the closing `]`, for `StealthAudioNoise.cpp` and its gtest. The hunk of `dom/media/gtest/moz.build` also carries the lines of two other folders, `TestStealthMediaDeclaration.cpp` (fingerprint/media/decode-declaration) and `TestStealthMediaEnumeration.cpp` (fingerprint/media/enumeration), right after this folder's.

## Notes for a port

- Gating on the seed alone once let the noise ignore `fp_noise`; every site gates on both. The offline path's scale comment: 5e-7 is the lower bound of the range, not the whole range.
