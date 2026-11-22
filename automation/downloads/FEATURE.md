# automation/downloads

Category: juggler
Prefs: none read directly
Test: juggler/tests/download_complete_follows_the_idl.test.mjs; end to end in the wrapper (tests/test_download_is_intercepted_e2e.py: test_a_clicked_download_is_reported_and_saved, test_a_navigation_that_ends_in_a_download_is_reported, test_a_canceled_download_reports_once_as_canceled, test_a_context_without_download_options_is_left_to_firefox)

## What it does

Our automation's download interceptor (Juggler, juggler/TargetRegistry.js) owns
the downloads its client asked for (Browser.setDownloadOptions). In
nsExternalAppHandler::OnStartRequest, before SetUpTempFile, StealthDownloadIntercept
asks it; when it takes the download, the saver writes straight to the file it
chose, with no nsITransfer and no downloads UI, and exactly one
onDownloadComplete follows (OnSaveComplete or Cancel; empty error name on
success). No interceptor, or one that declines or throws: stock Firefox.

Juggler installs the interceptor at startup with
nsIExternalHelperAppService.setDownloadInterceptor (declared in
nsIExternalHelperAppService.idl, because an XPIDL method can only be declared
inside its own interface; the interface nsIDownloadInterceptor is in our
StealthDownloadInterceptor.idl). The setter only stores it in
nsExternalHelperAppService::mInterceptor; Start asks it on each download and
Complete tells it when the download ended.

## Our files

- `uriloader/exthandler/StealthDownloadInterceptor.idl`: nsIDownloadInterceptor
  (interceptDownloadRequest, onDownloadComplete(aHandler, aErrorName)).
- `uriloader/exthandler/StealthDownloadIntercept.h/.cpp`: Start, Complete, the
  saver setup and the definition of `nsExternalHelperAppService::SetDownloadInterceptor`.

## Hooks in Mozilla files

- `uriloader/exthandler/moz.build`: registration of StealthDownloadInterceptor.idl (XPIDL_SOURCES) and StealthDownloadIntercept.cpp (UNIFIED_SOURCES), after the closing `]` of each list.
- `uriloader/exthandler/nsExternalHelperAppService.cpp`:
  - registration: `#include "StealthDownloadIntercept.h"` in a block of ours after Mozilla's includes.
  - anchor in nsExternalAppHandler::OnStartRequest: `if (StealthDownloadIntercept::Start(this, request)) return NS_OK;` right after the `if (XRE_IsContentProcess()) { return NS_OK; }` block. It cannot sit at the head of the function: Start reads mSourceUrl and mBrowsingContext, which OnStartRequest sets up above (GetURI, MaybeCloseWindow), and must come after the early returns (spam, forbidden download, content process). Wrapping SetUpTempFile would not skip the dialog and the transfer that follow.
  - pure additions, one line each, at the end of the two blocks: `StealthDownloadIntercept::Complete(this, aStatus);` as the last statement of `nsExternalAppHandler::OnSaveComplete` before its final `return NS_OK`, and `StealthDownloadIntercept::Complete(this, aReason);` as the last statement of `nsExternalAppHandler::Cancel` before its final `return NS_OK` (G30). The signatures of both functions are Mozilla's, unchanged.
- `uriloader/exthandler/nsExternalHelperAppService.h`: members `mInterceptor` (nsExternalHelperAppService), `mStealthIntercepted` (nsExternalAppHandler), and `friend class StealthDownloadIntercept` in both classes. Each after an existing member, none last in its block.
- `uriloader/exthandler/nsIExternalHelperAppService.idl`: `#include "StealthDownloadInterceptor.idl"` in a block of ours after Mozilla's include, and the method `setDownloadInterceptor` right after applyDecodingForExtension.

## Why the hooks give the same result as before

The two `Complete` lines are the ones of the base, unchanged: no function is renamed or wrapped. Each runs as the last statement of its block, as before.
- Complete reports once per intercepted download: it clears mStealthIntercepted first.

## Tests

- juggler/tests/download_complete_follows_the_idl.test.mjs: onDownloadComplete takes the arguments the IDL gives.
- Wrapper e2e (tests/test_download_is_intercepted_e2e.py): a clicked download and a navigation that ends in a download are reported and saved by Start and Complete; a canceled download reports once, as canceled (the Cancel hook); a context without setDownloadOptions gets no event and the file goes the stock Firefox way (negative control of every hook).
