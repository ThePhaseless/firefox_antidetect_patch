# automation/shadow-root

Category: juggler
Prefs: none read directly (the engine gate `StealthEngineActive()` reads `zoom.stealth.fpp.hw_seed`)
Test: wrapper `tests/test_ua_widget_not_selectable.py::test_an_author_closed_shadow_root_is_still_reachable`, `tests/test_ua_widget_not_selectable.py::test_the_page_itself_still_sees_null_on_both_kinds_of_closed_root` (the same closed root is null for the page and found by the sandbox), `tests/test_shadow_trusted_input.py`

## What it does

The `shadowRoot` getter of an element hides closed roots from the page (spec answer: null). The automation sandbox (Juggler's isolated world, a `Cu.Sandbox` on an `ExpandedPrincipal`) is given the author's closed root so selectors can pierce it; it never gets a UA widget (the calendar button of `<input type=date>`, video controls, ...), which would add engine internals to the page's DOM as seen by automation. The page keeps reading null on both kinds of closed root; with the engine off the getter is upstream's.

The decision is `StealthClosedShadowRootForBindings(aElement, aSubject, aMozilla)` in `dom/base/StealthShadowRoot.h` (inline, on purpose, namespace `mozilla::dom`). It takes the element, reads its shadow root itself with `GetShadowRoot()` (the same inline getter Mozilla's getter calls), asks `StealthClosedShadowRootException(aElement, aSubject)` and returns the root it gives for the automation sandbox, else `aMozilla`, which is Mozilla's own `nullptr`. The order of the tests in the exception is deliberate: the principal test (one load and one compare off `BasePrincipal::mKind`) goes first, so content returns on it and never reaches the UA-widget test or the pref read. What content pays there is readable from JS as a timing ratio (closed root over element with no root: retail 1.13, the first version 1.95), so the content path must stay as cheap as retail's.

The getter needs the caller's principal, so the attribute is declared `[NeedsSubjectPrincipal, BinaryName="shadowRootForBindings"]`: same attribute, same name, same spec answer for the page, nothing new on `Element.prototype` (a new accessor would be the tell).

## Hooks in Mozilla files

Declared exceptions (pm approved, `PM-DECISIONS.md`: the member + new BinaryName form was refused because it adds one call and one `GetShadowRoot()` on every path of `el.shadowRoot`, moving a ratio a page measures; the lines stay as they are):

- `dom/base/Element.cpp`, `Element::GetShadowRootForBindings`: the signature takes `nsIPrincipal& aSubject` (one line rewritten).
- `dom/base/Element.h`: the declaration with the same parameter (one line rewritten).
- `dom/webidl/Element.webidl`: `[NeedsSubjectPrincipal, BinaryName="shadowRootForBindings"]` on the `shadowRoot` attribute (one line rewritten).

A wrap of Mozilla's expression (not an exception): in `Element::GetShadowRootForBindings`, the `return nullptr;` of the closed-or-no-root branch is `return StealthClosedShadowRootForBindings(this, aSubject, nullptr);`. No local of the getter is passed: `this` and `aSubject` are the object and the parameter above, and Mozilla's `nullptr` is the third argument, the answer for everyone but the sandbox.

Registration: `#include "StealthShadowRoot.h"` in a block of ours after Mozilla's includes in `Element.cpp`.

Port note: if Mozilla changes the getter's body or the attribute annotation the conflict is the signal; what the hook needs is the branch "shadow is null or closed" of the getter and the caller's subject principal.
