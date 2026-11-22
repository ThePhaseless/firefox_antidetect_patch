# fingerprint/input/latency

Category: spoof
Prefs: none read directly
Test: gtest StealthInputEventBirth.* (dom/base/test/gtest/TestStealthInputEventBirth.cpp, in the default gtest filter); the wrapper's e2e tests/test_input_is_born_before_the_page_sees_it_e2e.py (every key and move is born before its handler runs: event.timeStamp below the handler's performance.now(); red when latency is 0); node juggler/tests/key_event_is_born_in_the_past_not_delayed.test.mjs

## What it does

A page's handler runs after its input event was born: with a real keyboard and
mouse, `event.timeStamp` is a few milliseconds below the `performance.now()` read in
the handler (3 to 18 ms on retail Windows Firefox with real devices). An event that
is synthesized by the chrome code of the driver is born at its dispatch, so the two
are equal, which a tracker that keeps only events from the past can tell. The
dictionary of the chrome-only `synthesizeMouseEvent` takes two members for this
folder's part of the work:

- `latency` (double, default 0): how many milliseconds before its dispatch the event was born. 0 is born now. It is read in `nsDOMWindowUtils.cpp` (stored in `mLatency`, and used by `nsContentUtils::InputEventBirth(aLatency)` for the timestamp a page reads as `event.timeStamp`): folders fingerprint/input/event-birth and automation/input.
- `jugglerEventId` (unsigned long, default 0): the Juggler event identifier that follows an event across processes (read in `nsDOMWindowUtils.cpp` and `nsContentUtils.cpp`: automation/input).

## Hooks in Mozilla files

- `dom/webidl/Window.webidl` (member, dictionary `SynthesizeMouseEventData`): two lines, one per member, each with its marker and a Mozilla member on both sides and apart from each other (the contract's C1 reads two adjacent lines as one hook of two lines): `double latency = 0;` after `short inputSource = 1;`, and `unsigned long jugglerEventId = 0;` after `long modifiers = 0;`. The members are not first in the dictionary any more: WebIDL sorts the members of a dictionary by name when it builds the binding (`Dictionary.members.sort` in dom/bindings/parser/WebIDL.py, unless the dictionary is `[Unsorted]`), so the position in the source changes nothing in the generated code. Same types, same defaults.
- The contract tool flags the two lines as C11 (a value of ours in a numbered space): false positive, `= 0` is the default of a member, not a constant of an enum or of a bit space.
