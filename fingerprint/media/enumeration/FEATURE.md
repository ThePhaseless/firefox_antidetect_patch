# fingerprint/media/enumeration

Category: spoof
Prefs: zoom.stealth.media.enumeration_ms
Test: wrapper:tests/test_the_device_enumeration_takes_the_declared_time_e2e.py::test_the_first_enumeration_takes_the_declared_time, wrapper:tests/test_the_device_enumeration_takes_the_declared_time_e2e.py::test_the_engine_waits_the_declared_time_and_never_asks_the_host, wrapper:tests/test_the_device_enumeration_takes_the_declared_time_e2e.py::test_the_enumeration_with_no_declaration_does_not_wait_and_asks_the_host, wrapper:tests/test_the_device_enumeration_takes_the_declared_time_e2e.py::test_the_camera_only_enumeration_never_asks_the_host_speakers

## What it does

With `zoom.stealth.media.enumeration_ms` declared, the host's speakers are not asked, neither for the device list nor to correlate a camera's groupId, and the first `enumerateDevices` of the session resolves after the declared time, the same on every host. The list is then kept as Firefox keeps it, so only the first one waits, as on a real machine. With the pref at 0 nothing changes: speakers are asked and the list resolves at once.

Why (B300): the speakers were the only part of an enumeration with fake cameras and microphones that went to the machine, through its audio stack, and their time was the host's (measured on Windows 250-350 ms on the first enumeration, on a host without audio 15-40).

All the logic is in `dom/media/StealthMediaEnumeration.h`: `StealthHostSpeakersMayBeAsked`, `StealthHostSpeakersRequested(bool)` (the one place that decides whether the speakers are enumerated; takes the flag as a bool so the header never names MediaManager's private `EnumerationFlag`), `StealthHostSpeakersForCorrelation(bool)` (Mozilla's `videoBackend == realBackend` ANDed with the same test) and `StealthDeclaredEnumeration` (the declared wait). `MOZ_LOG=StealthMediaEnumeration:4` logs "declared wait: N ms" once per enumeration and "host speakers asked: yes|no", for tests that must not depend on the load of the machine.

## Hooks in Mozilla files

`dom/media/MediaManager.cpp`:
- include of `StealthMediaEnumeration.h` in a block of ours after Mozilla's includes (registration).
- `MediaManager::EnumerationParams::RealDeviceRequested`: last operand of the return, wrapped in `StealthHostSpeakersRequested(...)` (wrap-expression).
- `MediaManager::MaybeRequestPermissionAndEnumerateRawDevices`: initialiser of `hasAudioOutput`, wrapped (wrap-expression).
- `MediaManager::EnumerateRawDevices`: condition of the speaker enumeration, wrapped in `StealthHostSpeakersRequested(...)` (wrap-expression); condition of the groupId correlation, wrapped in `StealthHostSpeakersForCorrelation(videoBackend == realBackend)` (wrap-expression).
- `MediaManager::GetPhysicalDevices`: the resolve step of the `Then` is a local lambda handed to `StealthDeclaredEnumeration`, which runs it now (pref 0) or after the declared delay through `NS_DelayedDispatchToCurrentThread`. Declared exception (G35, approved by the pm): no form expresses it without reading the pref one event-loop hop earlier and delaying the reject lambda. Known risk: the nsresult of the delayed dispatch is ignored; if the dispatch failed the enumeration promise would never resolve (not reproduced).
