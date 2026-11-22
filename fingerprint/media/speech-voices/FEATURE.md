# fingerprint/media/speech-voices

Category: spoof
Prefs: zoom.stealth.voices.list
Test: wrapper:tests/test_voices_e2e.py::test_the_voices_are_retail_windows_in_its_order_and_none_is_the_default, wrapper:tests/test_voices_e2e.py::test_the_voice_uri_is_the_retail_form_and_an_empty_list_falls_to_the_registry, wrapper:tests/test_voices_e2e.py::test_a_declared_list_with_missing_fields_reads_as_the_pref_says

## What it does

With `zoom.stealth.voices.list` non-empty, `speechSynthesis.getVoices()` answers the voices the core declares, in the retail Windows form (`voiceURI` `urn:moz-tts:sapi:NAME?LANG`, `name`, `lang`, `default`, `localService`), and the OS voice registry is never consulted. With the pref empty the Firefox path runs unchanged. Entries are comma-separated `NAME|LANG|D|L` (D = default 0|1, L = local 0|1; a missing field reads as "").

The declared voices are never registered with the OS: speaking with one falls back, in `nsSynthVoiceRegistry::FindBestMatch`, to a voice chosen by language or default.

## Hooks in Mozilla files

All hooks are one line with the marker on the line.

- `dom/media/webspeech/synth/SpeechSynthesis.cpp`: registration (`#include "StealthSpeechVoices.h"` in a block of ours after Mozilla's); anchor in `SpeechSynthesis::GetVoices` right after the `ShouldResistFingerprinting` return: `if (StealthGetVoices(this, aResult, mVoiceCache)) return;`. It stays an anchor because a guard at the head would run before `aResult.Clear()` and the RFP check (G28). `StealthGetVoices` returns false when the pref is empty; otherwise it builds the voices from the pref, replaces the cache `mVoiceCache` (passed as that field, private) and returns true.
- `dom/media/webspeech/synth/SpeechSynthesisVoice.cpp`: registration (`#include "StealthSpeechVoice.h"` in a block of ours); guards as the first statement of `GetVoiceURI`, `GetName`, `GetLang` (`if (StealthVoiceX(mUri, aRetval)) return;`) and of `LocalService`, `Default` (`if (bool stealth = false; StealthVoiceX(mUri, &stealth)) return stealth;`). `mUri` is private and passed as that field.
- `dom/media/webspeech/synth/moz.build`: `UNIFIED_SOURCES += [...]` for our two sources, after the closing `]`.

## Our files

- `StealthSpeechVoices.cpp/.h`: `StealthGetVoices`.
- `StealthSpeechVoice.cpp/.h`: `StealthVoiceRetailURI/Name/Lang(aUri, aOut)`, `StealthVoiceLocal/Default(aUri, bool* aOut)` (true and `*aOut` set for an internal URI, false and untouched otherwise), `StealthVoiceMakeURI`. The internal URI `stealth-voice:NAME|LANG|D|L` never reaches the page: `voiceURI` is the retail form, with scheme `sapi:` on every platform (retail Linux says `speechd:`, macOS `osx:`; the declared platform is Windows everywhere; format copied from `windows/SapiService.cpp`, which builds `"urn:moz-tts:sapi:" + description + "?" + locale`). The long explanation lives next to `StealthVoiceRetailURI`.
