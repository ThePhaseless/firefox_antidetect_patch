# automation/navigation

Category: juggler
Prefs: none read directly
Test: gtest TestStealthLinkClickAfter.*, TestStealthLoadInfo.* and TestStealthDocShellDefaults.* (docshell/base/test/gtest, in the default gtest filter of the candidate; TestStealthTRRContext.* for the TRRLoadInfo hooks); node juggler/tests/navigation_refused_before_a_channel.test.mjs (FrameTree's answer, and the only entry of the load); wrapper e2e tests/test_navigation_response.py::test_navigation_answers_with_a_real_response (the start of a navigation, both sides, and the load identifier on the response), tests/test_goto_script_redirect_e2e.py (a redirect clones the load info), tests/test_a_click_waits_for_the_navigation_it_plans_e2e.py (the "before" and "after" of a planned navigation), tests/test_a_goto_to_a_refused_port_ends_with_its_reason_e2e.py (a navigation refused before any channel ends with its reason), tests/test_a_navigation_that_moved_is_told_by_the_engine_e2e.py (a load that the parent moves to another process is told, with the process it left); node juggler/tests/navigation_hook_runs_only_for_a_load_that_leaves_the_document.test.mjs (a same-document load never reaches the start hook of the renderer)

## What it does

It makes the navigation events of Firefox reach Juggler, and carries the identifier of a load through the network layer. Only observer
notifications and one number on the LoadInfo: nothing a page can read, no network byte changes.

- The start of a top-level load, browser side (`juggler-navigation-started-browser`, subject the browsing context, data the load
  identifier as a decimal string): `CanonicalBrowsingContext::LoadURI` and `FixupAndLoadURIString` call `StealthNotifyNavigationStarted`
  (header-only, `StealthNavigationEvents.h`) right before Mozilla's `LoadURI(loadState, true)`. The call sits after the
  `GetIsCaptivePortalTab` block, where the local `loadState` exists (an anchor: a guard at the top has nothing to read, and the funnel
  `BrowsingContext::LoadURI(nsDocShellLoadState*, bool)` is shared by callers that must not notify).
- The start and the failure of a load, renderer side. Two anchors in `nsDocShell::InternalLoad`, around Mozilla's call of `DoURILoad`
  (untouched, as is its header): `StealthNavigationLoad stealthLoad(this, aLoadState);` right before
  `rv = DoURILoad(...)`. The object takes the docshell and the load state and reads the scheme of the load state's URI itself; it reports
  `juggler-navigation-started-renderer` unless the navigation is a `javascript:` URL. A same-document navigation never reaches the line:
  `InternalLoad` returns before `DoURILoad` whenever `sameDocument` is still true after `HandleSameDocumentNavigation`, and nothing writes it
  after (a node test reads `InternalLoad` and proves that). The second anchor is `stealthLoad.Failed(rv);` first in the
  `if (NS_FAILED(rv))` branch, which reports `juggler-navigation-failed-renderer` with the load identifier and the status, before
  `InternalLoad` shows the error page. A navigation Firefox refuses before any channel reports progress (a restricted port, an unknown
  protocol) ends there and nowhere else, so Juggler ends it with its reason.
- Planned navigations: a link click or a form submission is an `OnLinkClickEvent` that runs after the input that caused it returns (from
  157 a form submission too: `dom.forms.submit_async_navigation`). Juggler reports the plan as `Page.linkClicked` "before"
  (`juggler-link-click`) and its end as "after" (`juggler-link-click-sync`), so a client can tell an action that is about to navigate from
  one that is not; without it the POST of a submitted form was announced after `page.click()` had returned. `OnLinkClickWithLoadState`
  calls `StealthLinkClickBefore(aContent);` right before Mozilla's `return ev;` (the "before", only after the Dispatch succeeded, so never for a
  click that planned nothing); the event holds a `StealthLinkClickAfter` (member `mStealth`), whose state sends exactly one "after" per "before": from `Run`
  once `OnLinkClickSync` has started the navigation (`StealthSetRunning` brackets the call; `mStealth.Done(mContent);` sits right before Mozilla's final `return NS_OK;`),
  or from `Cancel` when the plan is cancelled (another submission replaces it) and `Run` is not inside `OnLinkClickSync`
  (`StealthCancelled`: Mozilla's comment says Cancel can be called from `OnLinkClickSync`, and it is, for a form: `InternalLoad` stops
  the docshell's network, which cancels its own planned form navigation; while Run is inside, it says "after" itself). The templates are
  templates because `OnLinkClickEvent` is complete only inside `nsDocShell.cpp`. Anchors: `StealthSetRunning(true)` after the
  `HasSourceElement` block, `StealthSetRunning(false)` right after `OnLinkClickSync(...)`, `StealthCancelled` after `mCancelled = true;`
  (they bracket a private member of `nsDocShell` that only the friend class reaches, or must run after Mozilla's statement).
- The load identifier. `nsILoadInfo.jugglerLoadIdentifier` (`[infallible]`) is set on the LoadInfo of each document load by the return of
  `CreateDocumentLoadInfo` (an anchor: `loadInfo->SetJugglerLoadIdentifier(aLoadState->GetLoadIdentifier());` right before Mozilla's `return loadInfo.forget();`) and kept by every copy of the LoadInfo
  (`Clone`, `CloneWithNewSecFlags`, `CloneForNewRequest`: a redirect, a separate request): `LoadInfo`'s copy constructor calls
  `StealthLoadInfoCopied` as the only statement of its body (the member is declared with a default of 0 and is no longer in the init
  list; nothing between the init list and the body reads it). The accessors of `LoadInfo` and of `TRRLoadInfo` (which answers
  `NS_ERROR_NOT_IMPLEMENTED`, as it does for the other `[infallible]` attributes it does not hold) live in `netwerk/base/StealthLoadInfo.cpp`.
- `netwerk/base/TRRLoadInfo` (the hooks carry the marker of network/doh; the folder owns the file and the functions): `Clone` carries the origin attributes
  of the DNS-over-HTTPS lookup into the clone (one added line in its body, before Mozilla's `return loadInfo.forget();`);
  `SetOriginAttributes` is answered by a guard (`StealthTRRSetOriginAttributes`, the member passed as argument) and Mozilla's refusal stays
  below it as in the tag.
- The two bit-fields `mFileInputInterceptionEnabled` and `mBypassCSPEnabled` of `nsDocShell` (owner: automation/docshell-attrs) are false
  at birth by their default member initializers (`= false` in `nsDocShell.h`); their two entries are removed from the constructor's init list (as in automation/docshell-attrs).

## Hooks in Mozilla files

- `docshell/base/CanonicalBrowsingContext.cpp`: registration (include of `StealthNavigationEvents.h`); two anchors, `StealthNotifyNavigationStarted(this, loadState);` before `LoadURI(loadState, true);` in `LoadURI` and `FixupAndLoadURIString`.
- `docshell/base/nsDocShell.cpp`: registration (include of `StealthNavigation.h`); anchors `StealthNavigationLoad stealthLoad(...)` (before `rv = DoURILoad(...)` in `InternalLoad`), `stealthLoad.Failed(rv);` (first in its error branch), `mStealth.StealthSetRunning(true)`, `mStealth.StealthSetRunning(false)`, `mStealth.StealthCancelled(mContent)`, `mStealth.Done(mContent);` (before the final `return NS_OK;` of `Run`) and `StealthLinkClickBefore(aContent);` (before `return ev;` of `OnLinkClickWithLoadState`); member `StealthLinkClickAfter mStealth;` (in `OnLinkClickEvent`). `DoURILoad` is Mozilla's, untouched. The two entries of the constructor's init list for the two bit-fields below are removed (the fields are false from their initial value), the same lines as in automation/docshell-attrs.
- `docshell/base/nsDocShell.h`: the two `= false` bit-fields (marker automation/docshell-attrs), the same lines as in that folder.
- `docshell/base/moz.build`: `StealthNavigation.cpp` (kept). `docshell/base/test/gtest/moz.build`: `include("stealth.build")`.
- `netwerk/base/LoadInfo.cpp`: registration (include of `StealthLoadInfo.h`); notice `StealthLoadInfoCopied(this, rhs);` in the copy constructor's body (the only statement of an empty body: the declared exception of this folder, G45).
- `netwerk/base/LoadInfo.h`: member `uint64_t mJugglerLoadIdentifier = 0;` after `mUserNavigationInvolvement`. `netwerk/base/nsILoadInfo.idl`: the attribute after `skipHTTPSUpgrade`.
- `netwerk/base/TRRLoadInfo.cpp`: registration (include), the added line in `Clone`, guard in `SetOriginAttributes`. `TRRLoadInfo.h` is Mozilla's.
- `netwerk/base/moz.build`: `StealthLoadInfo.cpp`. `netwerk/ipc/DocumentLoadListener.cpp`: registration (include of `StealthNavigationEvents.h`); the anchor `loadInfo->SetJugglerLoadIdentifier(...)` in `CreateDocumentLoadInfo`; the notice `StealthNotifyNavigationMoved(aContext, mContentParent, mLoadIdentifier, mIsDocumentLoad, aIsNewTab);` first in `TriggerProcessSwitch` (its arguments are parameters and members of Mozilla's function; the conditions for telling a move are in our header).

Candidates to remove in a later round (G24): `StealthSetRunning(false)` (after `Done`, `mNotified` makes `Cancelled` a no-op whatever `mRunning` is).

Firefox 160: `nsDocShell.cpp` hunk `OnLinkClickWithLoadState` conflicts (Mozilla removed it: `OnFormSubmit` and `OnLinkClick` build and dispatch the event inline, and `OnLinkClick` has a sync path with `ev->Run()` under `dom_links_sync_fragment_navigation`). The hook needs the content (`aForm`/`aContent`) and a point after a successful `Dispatch`, before the event can run, in both functions; in the sync path the "before" must precede `ev->Run()`, or the "after" of `Done` has no pair. Not resolved here: the line stays on 159.
