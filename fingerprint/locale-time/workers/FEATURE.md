# fingerprint/locale-time/workers

Category: other, spoof
Prefs: none read directly (the session's prefs are read by intl/locale/StealthSessionPrefs.h, not in this folder)
Test: wrapper tests/test_context_locale_e2e.py::test_a_context_locale_reaches_navigator_intl_and_the_header (dedicated, shared and service workers of a context whose language differs from the launch one); new, to write in the wrapper: test_an_audio_worklet_of_a_context_speaks_its_language_and_zone, test_a_running_worker_follows_a_language_set_after_its_birth, test_a_worker_with_its_own_language_ignores_the_accept_languages_pref, test_a_service_worker_of_a_context_with_its_own_zone_has_it. Browser test dom/base/test/browser_stealth_language_workers.js (dedicated, nested, shared; no workflow of the series runs it).

## What it does

A worker (dedicated, shared, service) and a worklet speak the language and keep the time of the context that created them, not those of the process: the same navigator.languages, Intl locale and zone as the window of that context. The language and the zone are carried from the creating context to the worker's `WorkerLoadInfo` (a service worker has no owner document: the language and zone its context's pages agree on are written into its `RemoteWorkerData` before each spawn), and the worker's realm is born with them. A worker that follows its owner's language ignores the process-wide `intl.accept_languages` broadcast, exactly as the owner's `Navigator::GetLanguages` does.

## Hooks in Mozilla files

Every hook is one line with the marker `// STEALTH-HOOK(fingerprint/locale-time/workers)`. Every anchor stays at the moment where the code ran before the rework; no row was moved.

- `dom/serviceworkers/ServiceWorkerPrivate.cpp`: include of `StealthServiceWorkerDeclaration.h` in our block after Mozilla's includes; anchor `StealthWorkerDeclaration(mInfo->Principal(), mRemoteWorkerData);` right after the statement that fills `registrationDescriptor` in `RefreshRemoteWorkerData` (last statement of the function, G30). It passes the two private fields it needs (G14).
- `dom/serviceworkers/moz.build`: `UNIFIED_SOURCES += ["StealthServiceWorkerDeclaration.cpp"]` after the closing bracket.
- `dom/workers/WorkerPrivate.cpp`: include of `StealthWorkerDeclaration.h` in our block; anchor `StealthDeclareWorkerLanguageAndZone(mLoadInfo);` right after `AssertIsOnMainThread();` in the no-parent branch of the constructor body (G23: a constructor hook stays in the body); wrap-expression `JS::SetRealmLocaleOverride(realm, StealthWorkerRealmLocale(aLanguageOverride.get()));` in `UpdateLanguageOverrideInternal` (Mozilla's line, with its argument wrapped); guard `if (StealthWorkerFollowsOwnerLanguage(this)) return;` at the top of `UpdateLanguagesInternal`.
- `dom/worklet/WorkletGlobalScope.cpp`: include of `StealthWorkletDeclaration.h` in our block; anchor `StealthDeclareWorkletRealm(this, options);` after Mozilla's two resistFingerprinting branches in `CreateRealmOptions`.
- `dom/worklet/WorkletImpl.cpp`: include of `StealthWorkletDeclaration.h` in our block; anchor `StealthWorkletAccess::Declare(this, aWindow);` as the last statement of the `WorkletLoadInfo` constructor, after `mOuterWindowID` is set.
- `dom/worklet/WorkletImpl.h`: our block with `#include "nsString.h"`; `friend struct StealthWorkletAccess;` after the explicit constructor; one member `std::pair<nsCString, nsString> mStealthDeclared;` (language first, zone second) after `mOuterWindowID`. No public accessor.
- `dom/base/test/browser.toml`: the entry of `browser_stealth_language_workers.js`, marker on the entry line.

## Our files

- `dom/workers/StealthWorkerDeclaration.h` (header only): `StealthDeclareWorkerLanguageAndZone(WorkerLoadInfo&)`, `StealthWorkerRealmLocale(const char*)` (an object that holds the primary language tag and converts to `const char*`; the temporary lives to the end of the `SetRealmLocaleOverride` statement), `StealthWorkerFollowsOwnerLanguage(const WorkerPrivate*)` (reads the public `GetLanguageOverride()`).
- `dom/serviceworkers/StealthServiceWorkerDeclaration.{h,cpp}`: `StealthWorkerDeclaration(nsIPrincipal*, RemoteWorkerData&)`, which scans the browsing context groups of the principal's user context and writes the language and zone its top-level pages agree on (empty when none or when they disagree). The two files take a name that is unique in the tree (G19): another header, `dom/workers/StealthWorkerDeclaration.h`, kept its name.
- `dom/worklet/StealthWorkletDeclaration.h` (header only, no line in moz.build): `StealthWorkletAccess` (friend of `WorkletLoadInfo`: `Declare`, `Language`, `Timezone`) and `StealthDeclareWorkletRealm(const WorkletGlobalScope*, JS::RealmOptions&)`. It includes `nsPIDOMWindowInlines.h` itself: `GetBrowsingContext()` is declared inline in `nsPIDOMWindow.h` and defined in `nsPIDOMWindowInlines.h`, and without that include `WorkletImpl.cpp` links only when the unified build happens to group it with a file that includes it (151 did, 157 does not: an undefined symbol in libxul).

## Why these decisions

- Constructors (WorkerPrivate, WorkletLoadInfo): the hook stays in the body at today's moment (G23), not in the initialization list, because the order of construction would change.
- B165, B334, B346: the realm arguments were empty literals once. The language until 2026-08-20: the worker spoke the machine's locale while its page spoke the declared one, in all of Intl and in toLocaleString (B165). The zone until firefox-50: the worker took the PROCESS's zone, the `TZ` the core put in the environment, which was right only where `TZ` was; on Windows the C runtime and ICU read `TZ` differently and no value satisfies both, so America/Phoenix gave the machine's zone in a Worker (B334), and a second context with a zone of its own gave the session's (B346). Until firefox-50 a worklet's realm got only resistFingerprinting's values: it took the process's zone and a default locale nobody set (WorkletThread, "FIXME: JS_SetDefaultLocale"), so Intl in an AudioWorklet answered en-US whatever the session declared.
- The values of a worklet are read on the main thread when the worklet is created and never modified: any thread may read them.
- `dom/workers/WorkerLoadInfo.h` carries three fields (`mLanguageOverrideLocale`, `mLanguageOverride`, `mTimezoneOverride`) that also reach service workers from the context of the registration (`RefreshRemoteWorkerData`); `WorkerPrivate`'s constructor fills empty ones with the session's (`intl/locale/StealthSessionPrefs.h`).
- Cost: `StealthWorkerDeclaration` walks every `BrowsingContextGroup` on each `RefreshRemoteWorkerData` (each service-worker spawn). Main thread only.
- UpdateLanguagesInternal ignores `intl.accept_languages` for workers that follow an owner's LanguageOverride.
