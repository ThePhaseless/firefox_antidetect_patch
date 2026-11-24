# automation/ignore-https-errors

Category: juggler
Prefs: none read directly
Test: wrapper:tests/test_ignore_https_errors_e2e.py::test_ignore_https_errors_loads_a_self_signed_page

## What it does

`IsDebugger()` in `security/manager/ssl/nsCertOverrideService.cpp` answers true
when an automation client is attached to the Juggler pipe, the same way it asks
whether Marionette or the Remote Agent is running. With that,
`Browser.setIgnoreHTTPSErrors` can flip the per-context switch of the
certificate override service (`SetDisableAllSecurityChecksAndLetAttackersInterceptMyData`
and the per-user-context override): without it `new_context(ignore_https_errors=True)`
raised `NS_ERROR_NOT_AVAILABLE`, so a caller asking to ignore certificate errors
got no context at all. A page cannot see this: it is the browser's own
switch. The pipe is asked by `StealthJugglerPipeConnected()`
(`juggler/pipe/StealthJugglerGate.cpp`, main thread only: off the main thread
the pipe refuses to answer and the function returns false). The narrower
variant of an upstream automation-layer patch: only the Juggler pipe is added.

## Hooks in Mozilla files

In `security/manager/ssl/nsCertOverrideService.cpp`, one line each:

- Registration: `#include "StealthIgnoreHTTPSErrors.h"` in a block of ours after
  Mozilla's includes. The header (own file, security/manager/ssl) carries the
  `#ifdef ENABLE_WEBDRIVER` and includes `StealthJugglerGate.h` there, so
  Mozilla's `#ifdef ENABLE_WEBDRIVER` include group is as in the tag and the
  gate comes in the same builds as before.
- Guard, first statement of `IsDebugger()` inside Mozilla's
  `#ifdef ENABLE_WEBDRIVER` block, before the Marionette and Remote Agent
  lookups: `if (StealthJugglerPipeConnected()) return true;`.

## Test

`wrapper:tests/test_ignore_https_errors_e2e.py::test_ignore_https_errors_loads_a_self_signed_page`:
a local https page with a self-signed certificate; a context without the option
must fail to load it (control arm in the same test: the certificate is not
trusted for another reason), a context with `ignore_https_errors=True` loads it.
Without the guard `new_context(ignore_https_errors=True)` raises.
