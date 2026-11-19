# stillborn/intermediates

Category: build, stillborn
Prefs: zoom.stealth.intermediates.file
Test: security/manager/ssl/stealth/test/run_stealth_intermediates_gate.py (cases with, without, poller, category; a step of the gate job of gate.yml, on linux-x86_64 and win-x86_64, with `$FF_EXE -xpcshell`)

## What it does

The intermediate certificates of Mozilla's list (about 1850) come from a file the
core declares, never from the network. A retail Firefox downloads the Remote
Settings collection `security-state/intermediates` once the browser is idle (after
the first navigation), and a page tells the two states apart: a chain that only a
preloaded intermediate completes verifies in one and fails in the other. The engine
never creates that collection, so no request is made for it, and writes the same
list into cert_storage before any window.

- Hook 1, `RemoteSecuritySettings.sys.mjs`: the constructor of `IntermediatePreloads`
  returns first thing, always (`StealthIntermediates.ownsPreloads()`). With no
  client created, `RemoteSettings("intermediates")` is never called, so the poller
  finds no client for the collection of the bucket `security-state` and skips it
  (`services/settings/remote-settings.sys.mjs`, `_client()` returns null), and the
  sync observer and the `remote-settings:changes-poll-end` observer of the class are
  never registered. Nothing else reads `IntermediatePreloadsClient.client`
  (only its own methods, which nothing calls). `RemoteSecuritySettings.init()`,
  OneCRL and CRLite are unchanged.
- Hook 2, `security/manager/ssl/moz.build`: `DIRS += ["stealth"]`. The directory
  registers a component under `profile-after-change` (`components.conf`,
  `@mozilla.org/psm/stealth-intermediates;1`, parent process only) whose module,
  `StealthIntermediates.sys.mjs`, reads the file named by
  `zoom.stealth.intermediates.file` (empty: nothing happens) with a synchronous
  stream, checks `format == 1`, builds `nsICertInfo` objects with
  `TRUST_INHERIT` exactly as `RemoteSecuritySettings` does, and calls
  `nsICertStorage.addCerts`. An error is one console line. `load()` can be called
  by a test; `lastLoad` keeps the durations and the result (evidence only).
- `addCerts` dispatches the write to cert_storage's own serial queue and returns:
  a verification asked in the same turn finds the intermediate only if the write
  task has taken the lock first (`cert_storage/src/lib.rs`: `AddCerts`,
  `SecurityStateTask::run`, `FindCertsBySubject`). Nothing orders the two.

The pref is read at `profile-after-change`, so it must be in the profile
(`user.js` or the command line) at launch: a value that arrives later by the
protocol is not read.

## Where it sits

`stillborn/`: the engine kills at birth a download that would change the browser
installed; the same content is declared by the core (as the API keys are).

## Test

`run_stealth_intermediates_gate.py` makes a root, an intermediate and a leaf at every
run (library `cryptography`, pinned in the gate step), writes the list in the core's
format (the intermediate among filler certificates of the same root) and runs one
`firefox -xpcshell stealth_intermediates_case.js` per case, each with its own empty
profile:

- `with`: the component is called the way the category calls it and the
  verification of the leaf is asked at once, without waiting for the callback of
  `addCerts`: it must succeed.
- `without`: same verification with no pref: `SEC_ERROR_UNKNOWN_ISSUER`.
- `poller`: `RemoteSecuritySettings.init()` and one poll of a local server whose
  feed lists `security-state/intermediates` and `security-state/onecrl`: no request
  whose path contains `intermediates`, and a request for onecrl carrying the feed's
  own timestamp (the poller is alive).
- `category`: `profile-after-change` has the entry `StealthIntermediates`.

The package has the xpcshell shell but not the harness, so the script sets the
profile directory provider up by hand. The gate step checks the series out at the
commit under test (the test lives in this folder).

## Hooks in Mozilla files

- `security/manager/ssl/RemoteSecuritySettings.sys.mjs` (IntermediatePreloads constructor, first statement, already-hook): Early return, with or without the pref: the engine never creates the security-state/intermediates client. Mozilla's lines are untouched.
- `security/manager/ssl/moz.build` (after the DIRS list, already-hook): builds our directory, which registers the profile-after-change component and installs the module.

## Our own files

- `security/manager/ssl/stealth/StealthIntermediates.sys.mjs`
- `security/manager/ssl/stealth/components.conf`
- `security/manager/ssl/stealth/moz.build`
- `security/manager/ssl/stealth/test/run_stealth_intermediates_gate.py`
- `security/manager/ssl/stealth/test/stealth_intermediates_case.js`
