# stillborn/security-state

Category: build, stillborn
Prefs: zoom.stealth.securitystate.generate, zoom.stealth.intermediates.file, zoom.stealth.onecrl.file, zoom.stealth.crlite.file (read only in the generate mode)
Test: security/manager/ssl/stealth/test/run_stealth_security_state_gate.py (cases generate, ready, ready_settles, empty, generate_without_delta, generate_fails, quit_refused, run_and_quit, marker, result_not_writable, profile_not_writable, no_import, never_asked, category, poller; `$FF_EXE -xpcshell`, a step of the gate job of gate.yml on linux-x86_64 and win-x86_64); security/manager/ssl/stealth/test/run_stealth_generate_launch_gate.py (the real launch in the generate mode, the next step of the same job); juggler/tests/the_client_gets_nothing_before_cert_storage_has_read_the_security_state.test.mjs (node, in the candidate's node step); scripts/ci/test_gate_security_state.py (the jobs of gate.yml set the security state from the wrapper's pin; run by scripts/ci/test_ci.py); the wrapper's suite wrapper.e2e.securitystate (tests/test_security_state_engine_e2e.py, job wrapper-e2e of gate.yml, both legs)

## What it does

A retail Firefox holds in `<profile>/security_state/` three collections of the
Remote Settings bucket `security-state`: the intermediate certificates
(`intermediates`), the CRLite filters (`cert-revocations`: one full filter and its
deltas) and the revocations of intermediates and roots (`onecrl`). A page tells the
states apart: a chain that only a preloaded intermediate completes, a certificate
revoked in a CRLite filter, an intermediate OneCRL lists. The engine never syncs
them from the network; the core fetches the data, the engine turns them into
cert_storage's own files once, and the core copies those files into every profile.

- Hook 1, `RemoteSecuritySettings.sys.mjs`: `init()` returns first thing, always
  (`StealthSecurityState.ownsSync()`). None of the three clients is created, so
  Remote Settings registers no client, no sync observer and no poll-end observer for
  the bucket, and the poller skips its collections (`_client()` returns null).
  BrowserGlue still calls `init()` at browser-idle-startup.
- Hook 2, `security/manager/ssl/moz.build`: `DIRS += ["stealth"]`. The directory
  registers a component under `profile-after-change` (`components.conf`,
  `@mozilla.org/psm/stealth-security-state;1`, parent process only) and installs
  `StealthSecurityState.sys.mjs`.

## The generate mode

The core launches `firefox -headless -no-remote -profile <work profile>` (never
`-app`: the engine is the whole Firefox) with a `user.js` holding exactly
`zoom.stealth.securitystate.generate=true` and the paths of the three files it
fetched and verified (format 1). The component, at `profile-after-change`, runs the
generation and keeps the application open until it ends
(`enterLastWindowClosingSurvivalArea`), then quits with its status before leaving
the area (the first quit wins). It hands the files to `nsICertStorage` as
`RemoteSecuritySettings` hands the downloaded data (`addCerts` with
`TRUST_INHERIT`, `setRevocations` with `STATE_ENFORCE` for every OneCRL record,
`setFullCRLiteFilter` and then `addCRLiteDelta` in the manifest's order), asks
`getCRLiteFilterHashes` last (it comes back after every write on cert_storage's
serial queue), writes `<profile>/securitystate-result.json` (format, ok, error,
engine version and BuildID, the collections with their timestamps and the CRLite
channel, the filter hashes) and exits 0 only with `ok: true`. Before anything it
writes the result as "generation did not finish", so a process that ends early
leaves `ok: false`; a result that cannot be written is status 1 and no file. A
request to quit that can be refused is refused while it runs. Nothing is printed.

On the full Firefox the mode asks the network for nothing and opens no window: the
IO service goes offline (without managing the offline status), every HTTP channel
is cancelled at `http-on-opening-request` (offline alone lets a channel through a
proxy on the loopback; the launch counter and Region were heard there), and the
default window is prevented (`command-line-startup`, `preventDefault`; the default
window of BrowserContentHandler opens only without it). On Windows `-headless` makes
the launcher process wait for the browser and pass on its exit code.

## The normal launch and the wait of Juggler

A normal launch has none of the prefs and imports nothing: cert_storage opens
`<profile>/security_state/` by itself (`cert_storage/src/lib.rs`,
`do_construct_cert_storage`, a task on its serial queue reads the deltas, the
database and the full filter). Without the folder the engine starts like a retail
Firefox with a new profile. `StealthSecurityState.whenStorageReady()` is one promise
that resolves at the callback of `hasPriorData`, dispatched to the same queue and so
run after that task (after 30 s at most; at once if anything throws; never
rejected). Juggler (`juggler/components/Juggler.js`, `final-ui-startup`) holds every
message of the pipe and the readiness line until it settles: the client's first
navigation sees the full filter and every delta.

## Where it sits

`stillborn/`: the engine kills at birth a download that would change the browser
installed; the same content is declared by the core.

## Test

`run_stealth_security_state_gate.py` makes a root, intermediates and leaves at every
run (library `cryptography`, pinned in the gate step), writes the files in the
core's formats and reads Mozilla's CRLite test data from `crlite_test_data.json`
(path, sha256 and base64 of each file of
`security/manager/ssl/tests/unit/test_crlite_filters/`); each case is one
`firefox -xpcshell stealth_security_state_case.js` with its own profile (the package
has the shell, not the harness). `poller` checks that `init()` leaves the three
clients null and that a poll of a local settings server listing the three
collections and a collection of another bucket asks only for the other one.
`run_stealth_generate_launch_gate.py` launches the engine as the core does, with
every per-user folder redirected and a proxy listener in `user.js`: exit and result,
BuildID, hashes, bytes, the same bytes twice, the failures, 66 deltas, no connection,
no file outside the profile (Linux: fontconfig's cache in the redirected cache
folder only). The wrapper's `wrapper.e2e.securitystate` checks the generation through
the core, a normal launch with no pref, a certificate revoked in a CRLite delta
refused at the first navigation through Juggler, and a launch with no or an empty
state.

Mozilla's `test_intermediate_preloads.js`, `test_crlite_filters.js` (the Remote
Settings part) and the OneCRL sync tests are not valid in this tree: the clients they
drive are never created.

## Hooks in Mozilla files

- `security/manager/ssl/RemoteSecuritySettings.sys.mjs` (guard, first statement of `RemoteSecuritySettings.init()`): `if (ChromeUtils.importESModule("resource://gre/modules/psm/StealthSecurityState.sys.mjs").StealthSecurityState.ownsSync()) return this;`. `ownsSync()` is always true, so none of the three clients of the bucket security-state is created and no client, sync observer or poll-end observer is registered; it runs before the `_initialized` check, as the import and the check did before. The module is imported in line because the `lazy` list at the top of Mozilla's file cannot take a line of ours. `ownsSync` keeps its name (G41; the contract tool flags it as C10).
- `security/manager/ssl/moz.build` (registration, after the DIRS list): `DIRS += ["stealth"]`. The directory registers the profile-after-change component and installs the module; without it the gate cases `never_asked` and `generate` fail.

The only entry that makes a client of the bucket is `init()`: `juggler/tests/the_client_gets_nothing_before_cert_storage_has_read_the_security_state.test.mjs` asserts that each of Mozilla's three constructions (`RemoteSettings("onecrl"`, `new IntermediatePreloads(`, `new CRLiteFilters(`) exists once, inside `init()` and below the guard, and that the file makes no other `RemoteSettings` client; a client that Mozilla adds outside `init()` makes it red. The behaviour is proved by the `poller` case of `run_stealth_security_state_gate.py`: `init()` leaves the three clients null and a poll of a fake server that lists them asks for none (without the guard the clients are created and the case is red).

## Our own files

- `security/manager/ssl/stealth/StealthSecurityState.sys.mjs`
- `security/manager/ssl/stealth/components.conf`
- `security/manager/ssl/stealth/moz.build`
- `security/manager/ssl/stealth/test/crlite_test_data.json`
- `security/manager/ssl/stealth/test/run_stealth_generate_launch_gate.py`
- `security/manager/ssl/stealth/test/run_stealth_security_state_gate.py`
- `security/manager/ssl/stealth/test/stealth_security_state_case.js`
