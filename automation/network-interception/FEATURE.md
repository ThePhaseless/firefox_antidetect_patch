# automation/network-interception

Category: juggler
Prefs: none read directly
Test: wrapper:tests/test_service_worker_controller_e2e.py::test_a_reloaded_page_is_controlled_by_its_service_worker (a page is controlled by its service worker with Juggler attached; the path with mServiceWorkerResetBypass=false); wrapper `tests/test_service_worker.py`; node `juggler/tests/held_requests_end_with_their_request.test.mjs`

## What it does

The automation driver (Juggler) intercepts the requests it is told to. A request a service worker could answer is offered to the worker first: the driver calls `interceptAfterServiceWorkerResets()` to be called again if the worker lets the request through, and finally resumes it with `resetInterceptionWithURI(uri)`. The two methods are declared in `nsIInterceptedChannel`, the state (`mInterceptAfterServiceWorkerResets`, `mServiceWorkerResetBypass`) lives in `InterceptedHttpChannel`, and the logic is in `netwerk/protocol/http/StealthInterception.cpp`: `StealthOwnsInterception` and `StealthInterceptAgain` (called by one line in Mozilla's `ResetInterception`) are ours, and the two methods are defined there.

## Hooks in Mozilla files

- `netwerk/base/nsINetworkInterceptController.idl` (members, kept apart, one hook per line): `void resetInterceptionWithURI(in nsIURI aURI);` after `resetInterception`, and `void interceptAfterServiceWorkerResets();` after `synthesizeStatus`. Declarations only; the implementations are in `StealthInterception.cpp`. The order of the slots of the interface changes only inside one build.
- `netwerk/protocol/http/InterceptedHttpChannel.cpp` (anchor, one line): in Mozilla's `ResetInterception`, directly after the `INTERCEPTED_LOG` line, `if (StealthOwnsInterception()) return StealthInterceptAgain(aBypass);`. `StealthOwnsInterception` (ours, `StealthInterception.cpp`) tells whether the driver asked to be called again; `StealthInterceptAgain` spends the flag, keeps the bypass in `mServiceWorkerResetBypass` and gives the channel back to the interceptors (`ChannelIntercepted`), or returns `NS_ERROR_DOM_INVALID_STATE_ERR` with no controller. Mozilla's signature and body are untouched (0 Mozilla lines rewritten), and Mozilla's debug line is printed on both roads, as before.
- `netwerk/protocol/http/InterceptedHttpChannel.h` (members, four lines kept apart): `bool StealthOwnsInterception();` and `nsresult StealthInterceptAgain(bool aBypass);` after the `friend`, `bool mServiceWorkerResetBypass{true};` after `mStatusHost`, `bool mInterceptAfterServiceWorkerResets{false};` after `mInterceptionReset`.

## netwerk/base/nsINetworkInterceptController.idl: resetInterceptionWithURI, interceptAfterServiceWorkerResets

Both methods sit in interface nsIInterceptedChannel, after resetInterception,
each marked `// STEALTH-HOOK(automation/network-interception)` (the second sits after `synthesizeStatus`).
They used to sit between the markers `// ----- Playwright begin -----` and
`// ----- Playwright end -------`, which are gone.

- resetInterceptionWithURI(in nsIURI aURI): Same as resetInterception, but
  updates the URI.
- interceptAfterServiceWorkerResets(): After resetInterception is called, this
  request will be intercepted again.
