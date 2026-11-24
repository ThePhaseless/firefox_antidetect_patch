# automation/docshell-attrs

Category: juggler
Prefs: none read directly
Test: wrapper:tests/test_file_chooser.py::test_without_interception_the_file_inputs_remain_normal (negative control: a page without interception keeps the browser's own file chooser); wrapper:tests/test_bypass_csp_e2e.py::test_bypass_csp_lifts_the_page_policy_and_its_absence_keeps_it (with and without `bypass_csp`); node `juggler/tests/docshell_settings_follow_every_local_docshell.test.mjs`

## What it does

Juggler sets two flags on a docshell: `fileInputInterceptionEnabled` and `bypassCSPEnabled`. Each is read where it acts: `fileInputInterceptionEnabled` by `HTMLInputElement` (the file picker of an `<input>`), `bypassCSPEnabled` by `CSP_IsBypassedFor` (`dom/security/StealthBypassCSP.cpp`, folder `automation/bypass-csp`). They are declared in `nsIDocShell.idl`, implemented by the accessors of `StealthDocShellAttrs.cpp` (declared by `NS_DECL_NSIDOCSHELL`) and backed by two bit-fields of `nsDocShell`. The bit-fields are false from construction (a default member initialiser in the header): they were once left uninitialised, and a bit-field nobody initialises holds whatever the allocation held, so a docshell Juggler never wrote to could intercept file pickers or bypass a policy. The port that first added the attributes also added `overrideHasFocus`, `forceActiveState` and `disallowBFCache` as storage only; nothing read them and they are gone. `languageOverride`, `overrideTimezone` and `overrideLocale` (the docshell's side channels for language and zone) are gone too: both now travel only in the BrowsingContext's `LanguageOverride` and `TimezoneOverride` fields (`dom/base/StealthSessionDeclaration.h`).

## Hooks in Mozilla files

- `docshell/base/moz.build`: `UNIFIED_SOURCES += ["StealthDocShellAttrs.cpp"]` after the closing `]` (registration). The next line registers `StealthNavigation.cpp` and belongs to `automation/navigation`.
- `docshell/base/nsDocShell.h`: two member lines, kept apart (one hook per line): `bool mFileInputInterceptionEnabled : 1 = false;` after `mIsExecutingOnLoadHandler`, and `bool mBypassCSPEnabled : 1 = false;` after `mInvisible`. Written byte for byte like the `automation/navigation` branch, which also drops the two initialisers of the constructor in `nsDocShell.cpp` (its file). This branch drops the same two entries of the init list (the comment line `// STEALTH-HOOK(automation/docshell-attrs)` and the two `(false)` entries), byte for byte like that branch, so each of the two branches compiles by itself (the header order and the init-list order agree: `-Wreorder`).
- `docshell/base/nsIDocShell.idl`: `attribute boolean fileInputInterceptionEnabled;` after `synchronizeLayoutHistoryState`, and `attribute boolean bypassCSPEnabled;` after `persistLayoutHistoryState` (members, kept apart). The order of the slots in the interface changes only inside one build (page-invisible; XPIDL has no explicit numbering).
