# stillborn/telemetry

Category: stillborn
Prefs: none read directly (the child reads the session's `prefs.js`: `network.proxy.*`, `network.trr.*`)
Test: node juggler/tests/pingsender_route_reaches_the_channel.test.mjs (callbacks on the channel, bypass, no proxy, road missing,
negative control), juggler/tests/pingsender_route_lives_in_our_file.test.mjs (the program, the environment variable around the
child, the only start of the child (ours: Mozilla's own process is never started), the only use of the program), juggler/tests/no_ping_leaves_before_the_session_proxy_is_decided.test.mjs
(undecided / decided, network/doh); wrapper e2e
invisible_playwright/tests/test_the_shutdown_ping_leaves_by_the_background_task_e2e.py::test_the_shutdown_ping_is_sent_by_the_background_task_and_not_by_the_host_program

## What it does

The telemetry ping at exit leaves by the session's road, never by the host's. Mozilla starts the standalone `pingsender[.exe]`,
which takes its road from the host (WinINet's system proxy on Windows, libcurl's environment on Linux: a session behind a proxy
sent its shutdown pings from the machine's own address, with SOCKS5, with an HTTP proxy and with none). Here the pings always go
to `firefox --backgroundtask pingsender`, the engine with necko, and that task leaves by the road its parent hands it.

- `StealthPingsender.invocation()` is the program of the child: `firefox[.exe] --backgroundtask pingsender`, a fresh `params` array on
  every call. Mozilla's own choice of the program in `runPingSender` (`pingsender[.exe]`, or the background task when a Nimbus
  variable says so) stays as Mozilla wrote it; the process it initialises is never started.
- `StealthRoutedProcess(process).runAsync(params, count, observer)` is Mozilla's start of that process, with the receiver wrapped and
  the three arguments in place. It starts the child: a process of its own (an `nsIProcess` can be initialised once), built from
  `invocation()` with Mozilla's parameters (the ping urls and paths) after the program's own. The road, `{proxy, prefs}`, goes in the
  environment variable `STEALTHFOX_PINGSENDER_ROUTE` only around the start of that one child (not on the command line, which any process
  can list, and not in a file with a proxy password in it); the variable is emptied right after the start, also when the start throws.
  When the session's proxy is undecided (a Juggler-driven browser that no command has told "this proxy" or "none") nothing is
  started and the observer gets `process-failed`: a null record would mean DIRECT. The ping stays on disk.
- `StealthPingsenderRoute.takeSessionRoute()` is the first statement of `runBackgroundTask`. It reads the variable and empties
  it, reads the session's `prefs.js` into the empty profile of the task, registers a proxy channel filter (priority 0) that applies
  the record with the functions of `SessionRoute.js`, and registers `pingAuthFor` as the provider of callbacks. It throws when the
  variable is missing: the task fails closed, it never falls back to the defaults of its own profile (the host's road).
- `StealthPingsender.attachRoute(request, endpoint)` is called in `sendStandalonePing` right after `request.open(...)`: the
  channel exists only after `open()` and XMLHttpRequest takes the channel's callbacks when it sends (`mNotificationCallbacks` in
  `XMLHttpRequestMainThread.cpp`), so the set must come between the two. The callbacks are those of the endpoint's host
  (`pingAuthFor(new URL(endpoint).hostname)`: the answer to an HTTP proxy's 407, none when the host is in the record's bypass list
  or the session has no proxy). A background request gets no prompt of its own. In the browser process no provider is
  registered, so the call does nothing there.

The exit ping and the undecided proxy: why and tests in network/doh.

## Hooks in Mozilla files

- `toolkit/components/telemetry/app/TelemetrySend.sys.mjs`:
  - `import * as StealthPingsender ...` and `import { StealthRoutedProcess } ...` in a block of ours after Mozilla's imports (form
    registration, one line each);
  - `StealthPingsender.attachRoute(request, endpoint);` in `sendStandalonePing`, right after `request.open("POST", endpoint, true);`
    (form anchor: `request` is a local of Mozilla's executor and `open()` returns nothing to wrap; the signature of
    `sendStandalonePing` is Mozilla's);
  - `StealthRoutedProcess(process).runAsync(params, params.length, observer);` is Mozilla's last line of `runPingSender`,
    `process.runAsync(params, params.length, observer);`, with the receiver wrapped (form wrap-expression): the arguments are
    Mozilla's, in the same order. Mozilla's choice of `exeName` and `params` above it is untouched and no line of ours assigns them:
    the pref that would let Mozilla's own lines choose the background task,
    `toolkit.telemetry.shutdownPingSender.backgroundtask.enabled`, is not declared because the program must not depend on a pref that
    can change, so the child is chosen inside `StealthRoutedProcess`.
- `toolkit/components/telemetry/pings/BackgroundTask_pingsender.sys.mjs`: the import of `StealthPingsenderRoute.sys.mjs` in a block
  of ours after Mozilla's import (registration) and `StealthRoute.takeSessionRoute();` as the first statement of
  `runBackgroundTask` (form notice; it throws when the road is missing, failing closed). The call of `sendStandalonePing` is
  Mozilla's.
- `toolkit/components/telemetry/moz.build`: two registration lines after the closing `]` of `EXTRA_JS_MODULES` and of
  `EXTRA_JS_MODULES.backgroundtasks`.

## Our own files

- `toolkit/components/telemetry/app/StealthPingsender.sys.mjs` (`PINGSENDER_ROUTE_ENV`, `attachCallbacks`, `useCallbacksFrom`,
  `attachRoute`, `invocation`, `StealthRoutedProcess`; `sessionRoute()` asks `TargetRegistry.roadOfSession(0)`).
- `toolkit/components/telemetry/pings/StealthPingsenderRoute.sys.mjs` (`takeSessionRoute`, `pingAuthFor`; it imports
  `PINGSENDER_ROUTE_ENV` and `useCallbacksFrom` from `StealthPingsender.sys.mjs`).
- Tests: `juggler/tests/pingsender_route_lives_in_our_file.test.mjs`, `juggler/tests/pingsender_route_reaches_the_channel.test.mjs`.
