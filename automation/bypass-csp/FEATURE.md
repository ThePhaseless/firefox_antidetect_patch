# automation/bypass-csp

Category: juggler
Prefs: none read directly
Test: wrapper:tests/test_bypass_csp_e2e.py::test_bypass_csp_lifts_the_page_policy_and_its_absence_keeps_it (with and without `bypass_csp`: the run without it is the negative control); node `juggler/tests/docshell_settings_follow_every_local_docshell.test.mjs` (the flag reaches every local docshell)

## What it does

When the automation asks for `bypass_csp`, the docshell carries the flag `bypassCSPEnabled` (declared in `nsIDocShell.idl`, stored in `nsDocShell.h`, both owned by `automation/docshell-attrs`). `CSP_IsBypassedFor` (`dom/security/StealthBypassCSP.cpp`) is the one place that answers the question: true when the docshell the document lives in has the flag set; a document without a docshell (loaded as data, or already detached) is never bypassed. Two places read it: `Document::InitCSP` (the policies the page sends in its headers; the call is a hook of `fingerprint/locale-time/timezone`, marker `automation/bypass-csp`) and `CSP_ApplyMetaCSPToDoc` (a policy in a `<meta>` element). Until the function existed the attribute was stored and never read, so `bypass_csp=True` changed nothing a page enforced (issue #295 of the wrapper's repo).

## Hooks in Mozilla files

- `dom/security/moz.build`: `UNIFIED_SOURCES += ["StealthBypassCSP.cpp"]`, after the closing `]` (registration).
- `dom/security/nsCSPUtils.h`: the declaration `bool CSP_IsBypassedFor(const mozilla::dom::Document& aDoc);` in the block of the `CSP_*` declarations, one line (registration, G40). The function keeps its name (G41): `Document.cpp` calls it and reaches it through this header.
- `dom/security/nsCSPUtils.cpp`: `if (CSP_IsBypassedFor(aDoc)) return;` in `CSP_ApplyMetaCSPToDoc`, right after Mozilla's `if (aDoc.IsLoadedAsData()) { return; }` block (anchor). It is not the first statement of the function: at the top it would run before the `IsLoadedAsData` check, which gives the same result only if no data document (external resources) ever has a docshell; that is not proven, so the hook stays where it is today.
