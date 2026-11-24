# fingerprint/audio/sample-rate

Category: spoof
Prefs: zoom.stealth.audio.sample_rate
Test: wrapper `tests/test_audio_sample_rate_is_declared_e2e.py::test_audio_context_sample_rate_is_the_declared_one` (new, written first and green on firefox-68); the existing `tests/test_fingerprint_surface.py::test_pin_audio_sample_rate_lands_in_AudioContext` stays as it is

## What it does

`new AudioContext().sampleRate` answers the rate the core declares in `zoom.stealth.audio.sample_rate`, instead of the rate of the host's audio device (a value that is the host's and that cubeb reads from the system).

`mozilla::CubebUtils::PreferredSampleRate` answers the pref when it is above 0, with no engine gate: a build launched without invisible_core has the pref at -1 and keeps the device's rate. The declared value is answered before the fingerprint-resistance 44100 and before `InitPreferredSampleRate()` reads the device, so with a declared rate the host's audio stack is not asked. Mozilla's own forced rate (`media.cubeb.force_sample_rate`, a test-only pref) is checked first, as it always was: a build that sets both pins the forced one.

The logic is in `dom/media/StealthSampleRate.h` (header-only on purpose: its one includer is `CubebUtils.cpp`, so no line is added to `dom/media/moz.build`): `StealthDeclaredSampleRate(uint32_t*)`, which answers false when the pref is not above 0 (Firefox keeps its own path) and otherwise fills its out parameter. The header includes `mozilla/StaticPrefs_zoom.h`, which `CubebUtils.cpp` no longer includes itself.

## Hooks in Mozilla files

All in `dom/media/CubebUtils.cpp`:

- Registration: `#include "StealthSampleRate.h"` in a block of ours after Mozilla's includes, before `#define AUDIOIPC_STACK_SIZE_DEFAULT`.
- Anchor, in `PreferredSampleRate` right after the forced-rate block (`if (sCubebForcedSampleRate) { return sCubebForcedSampleRate; }`): `if (uint32_t stealth; StealthDeclaredSampleRate(&stealth)) return stealth;`. It is an anchor only by position: at the top of the function it would answer before `media.cubeb.force_sample_rate`, inverting the order of the two prefs in the case where both are set.

Comment that stood above the old block, moved out of the Mozilla file verbatim:

> Stealth: sampleRate from pref set by Python at launch

Port note: if Mozilla moves or removes the forced-rate block, the hook follows what is left of it; it must stay before the `aShouldResistFingerprinting` branch and before `InitPreferredSampleRate()`.
