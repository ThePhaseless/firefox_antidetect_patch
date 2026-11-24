# fingerprint/input/event-birth

Category: spoof
Prefs: none read directly
Test: gtest suites StealthKeyBirthScope.*, StealthInputEventBirth.*, StealthBirthOrder.* (dom/base/test/gtest/TestStealthInputEventBirth.cpp, in the
candidate filter), among them the ones on a real TextInputProcessor (TheMemberOfTheProcessorHasTheShapeOfTheDeclaration,
SetNextKeyLatencyOfARealProcessorDeclaresTheNextKeyAndTheScopeTakesIt) and on the mouse hook (TheMouseHookReadsTheLatencyOfTheDataAndStampsTheEvent);
the node test juggler/tests/key_event_is_born_in_the_past_not_delayed.test.mjs (the only entries that deliver a key open the scope first, the only
stamps are those of the two copies, the only definition of setNextKeyLatency is ours); the wrapper e2e
tests/test_input_is_born_before_the_page_sees_it_e2e.py

## What it does

A synthetic key or mouse movement is born in the past, as one of a real system is: the latency the caller declares moves its `timeStamp` back, and the
births of one page never go backwards (keys, mouse and wheel of a page are one ordered stream; two pages are two streams). Nothing is added to the
web-exposed KeyboardEventInit. The logic lives in `dom/base/StealthInputEventBirth.{h,cpp}`.

- Keys: `nsITextInputProcessor.setNextKeyLatency(latencyMs, pageId)` (chrome only) stores the latency of the NEXT key in the processor's private field
  `mStealthKeyBirth` (`TextInputProcessor::SetNextKeyLatency` is defined in `StealthInputEventBirth.cpp`: it asserts the chrome caller and stores).
  `keydown()`, `keyup()` and `commitCompositionWith()` each open a `StealthKeyBirthScope` as their first statement, passing the field: the scope takes
  the latency (one use: it is cleared) and holds the birth for the whole call. `KeydownInternal()` and `KeyupInternal()` stamp their local copy of the
  key event right after `keyEvent.mMessage = ...`; `TextEventDispatcher` copies the stamp with `AssignKeyEventData` and the keypress events are copies of
  the keydown, so every key event of the call carries the birth. With no latency declared the scope holds no birth and the stamp does nothing. It
  replaces the chrome setTimeout of juggler/content/PageAgent.js, which under load moved the delivery itself. Known limit: on `commitCompositionWith()`
  the composition and input events keep their delivery time (they are created by `TextEventDispatcher::CommitComposition()`, a line of Mozilla's).
- Mouse: `nsContentUtils::SynthesizeMouseEvent` stamps its local event after the last statement of Mozilla that writes it and before the three dispatch
  calls: `StealthSetMouseEventBirth(event, aMouseEventData, aPresShell)` reads `aMouseEventData.mLatency` in our template and finds the page from the
  PresShell.

## Hooks in Mozilla files

- `dom/base/TextInputProcessor.cpp`: one include in a block of ours; `StealthKeyBirthScope stealthBirth(mStealthKeyBirth);` as the first statement of
  `Keydown(Event*, ...)`, `Keyup(Event*, ...)` and `CommitCompositionWith(...)` (a notice: it only takes the latency of the field it is given and holds
  the birth until the method returns; the two release assertions of Mozilla that follow it read nothing of it and end the process when they fail; the
  private field is passed, no `friend`); two anchors `StealthKeyBirthScope::Stamp(keyEvent);` after `keyEvent.mMessage = eKeyDown;` (KeydownInternal) and
  `keyEvent.mMessage = eKeyUp;` (KeyupInternal): they change the local copy of the const parameter that Mozilla uses afterwards, and a guard or wrap
  cannot reach it (accepted by the pm).
- `dom/base/TextInputProcessor.h`: the member `mStealthKeyBirth`, an anonymous struct `{ double mLatencyMs; uint64_t mPageId; }` (no include in an
  exported header), after `mModifierKeyDataArray`; a gtest holds it to the shape of `StealthKeyBirth` of our header.
- `dom/interfaces/base/nsITextInputProcessor.idl`: the method `setNextKeyLatency` after `keyup` (chrome-only builtin-class XPCOM interface, no numbered
  space of Mozilla touched).
- `dom/base/nsContentUtils.cpp`: one include in a block of ours (shared with `StealthJugglerEventId.h` of automation/input, which keeps its marker) and
  the anchor `StealthSetMouseEventBirth(mouseOrPointerEvent, aMouseEventData, aPresShell);` after the `mMovementX.WasPassed()` block of
  `SynthesizeMouseEvent`. The two other hooks of this function (`StealthSetJugglerId`, `StealthJugglerNotAsyncSynthesized`) belong to automation/input.
- `dom/base/moz.build` (`UNIFIED_SOURCES += ["StealthInputEventBirth.cpp"]`) and `dom/base/test/gtest/moz.build` (`UNIFIED_SOURCES +=
  ["TestStealthInputEventBirth.cpp"]`), after the closing brackets, one line per owner folder.
- No Mozilla line is removed or changed in this folder.

## Our own files

- `dom/base/StealthInputEventBirth.{h,cpp}`, `dom/base/test/gtest/TestStealthInputEventBirth.cpp`, and the node test above.
