# stillborn/telemetry

Category: stillborn
Prefs: none read directly (the child reads the session's `prefs.js`: `network.proxy.*`, `network.trr.*`)
Test: node juggler/tests/pingsender_route_reaches_the_channel.test.mjs (callbacks on the channel, bypass, no proxy, road missing,
negative control), juggler/tests/pingsender_route_lives_in_our_file.test.mjs (the program, the environment variable around the
child, the only start of the child, the only use of the program), juggler/tests/no_ping_leaves_before_the_session_proxy_is_decided.test.mjs
(undecided / decided, network/doh); wrapper e2e
invisible_playwright/tests/test_exit_ping_leaves_as_the_background_task_e2e.py::test_exit_ping_leaves_as_the_background_task

## What it does

The telemetry ping at exit leaves by the session's road, never by the host's. Mozilla starts the standalone `pingsender[.exe]`,
which takes its road from the host (WinINet's system proxy on Windows, libcurl's environment on Linux: a session behind a proxy
sent its shutdown pings from the machine's own address, with SOCKS5, with an HTTP proxy and with none). Here the pings always go
to `firefox --backgroundtask pingsender`, the engine with necko, and that task leaves by the road its parent hands it.

- `StealthPingsender.invocation()` overrides Mozilla's choice of the program after it: `firefox[.exe] --backgroundtask pingsender`,
  a fresh `params` array on every call.
- `StealthPingsender.runAsync(process, params, observer)` starts the child. The road, `{proxy, prefs}`, goes in the environment
  variable `STEALTHFOX_PINGSENDER_ROUTE` only around the start of that one child (not on the command line, which any process can
  list, and not in a file with a proxy password in it); the variable is emptied right after the start, also when the start throws.
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
  - `import * as StealthPingsender ...` in a block of ours after Mozilla's imports (form registration);
  - `StealthPingsender.attachRoute(request, endpoint);` in `sendStandalonePing`, right after `request.open("POST", endpoint, true);`
    (form anchor: `request` is a local of Mozilla's executor and `open()` returns nothing to wrap; the signature of
    `sendStandalonePing` is Mozilla's);
  - `({ exeName, params } = StealthPingsender.invocation());` in `TelemetrySendImpl.runPingSender`, after Mozilla's choice of the
    program and before `exeName` is used (form anchor that assigns Mozilla's locals; kept as today by decision of the pm: the
    pref that would let Mozilla's own lines choose the background task, `toolkit.telemetry.shutdownPingSender.backgroundtask.enabled`,
    is not declared because the override must not depend on a pref that can change; exception recorded in the hook list);
  - `StealthPingsender.runAsync(process, params, observer);` replaces `process.runAsync(params, params.length, observer);`, the last
    line of `runPingSender` (form wrap-expression, G29: the receiver becomes the first argument and `params.length` is derived
    inside; our function calls `process.runAsync` itself when it is its turn).
- `toolkit/components/telemetry/pings/BackgroundTask_pingsender.sys.mjs`: the import of `StealthPingsenderRoute.sys.mjs` in a block
  of ours after Mozilla's import (registration) and `StealthRoute.takeSessionRoute();` as the first statement of
  `runBackgroundTask` (form notice; it throws when the road is missing, failing closed). The call of `sendStandalonePing` is
  Mozilla's.
- `toolkit/components/telemetry/moz.build`: two registration lines after the closing `]` of `EXTRA_JS_MODULES` and of
  `EXTRA_JS_MODULES.backgroundtasks`.

## Our own files

- `toolkit/components/telemetry/app/StealthPingsender.sys.mjs` (`PINGSENDER_ROUTE_ENV`, `attachCallbacks`, `useCallbacksFrom`,
  `attachRoute`, `invocation`, `runAsync`; `sessionRoute()` asks `TargetRegistry.roadOfSession(0)`).
- `toolkit/components/telemetry/pings/StealthPingsenderRoute.sys.mjs` (`takeSessionRoute`, `pingAuthFor`; it imports
  `PINGSENDER_ROUTE_ENV` and `useCallbacksFrom` from `StealthPingsender.sys.mjs`).
- Tests: `juggler/tests/pingsender_route_lives_in_our_file.test.mjs`, `juggler/tests/pingsender_route_reaches_the_channel.test.mjs`.
