# automation/input

Category: juggler
Prefs: none read directly
Test: gtest StealthDragGesture.*, StealthMouseEventIPC.*, StealthMouseEventCopy.*, StealthJugglerCoalesce.*, StealthJugglerMouseAck.*, StealthSurfaceFlags.*; juggler/tests/mouse_ack_comes_from_any_root.test.mjs, wheel_waits_for_its_delivery.test.mjs, keys_go_to_the_focused_root.test.mjs, input_review_findings.test.mjs; end to end in the wrapper (tests/test_a_pointer_event_is_handled_before_the_call_returns_e2e.py: test_each_pointer_call_answers_after_the_page_handled_its_event; tests/test_mouse_events_keep_their_values_e2e.py: test_the_events_of_the_page_and_of_an_iframe_of_its_process_keep_their_order_and_values; tests/test_cross_origin_iframe.py; tests/test_drag_motion.py: test_a_real_page_sees_a_drag_that_travelled; tests/test_input_is_born_before_the_page_sees_it_e2e.py; tests/test_canvas_reads_as_drawn.py)

## What it does

The mouse, the wheel and the drag of Juggler (nsIDOMWindowUtils.jugglerSendMouseEvent, jugglerSendDragEvent and
sendWheelEvent) go through the asynchronous route: the APZ hit test, one process per site. Every mouse event Juggler sends
carries an id (WidgetMouseEventBase::mJugglerEventId) that crosses the IPC between the processes and the coalescing of
moves; the renderer that handles the event notifies `juggler-mouse-event-hit-renderer` with "<type> <id>" once, after the
handling, and the driver's call returns only then. A drag gesture that a Juggler press started is continued only by Juggler
moves.

## The route of the mouse and the wheel (one process per site)

A mouse event of Juggler goes to the widget on the asynchronous route (`StealthJugglerInput.h`: `mIsAsyncEnabled = true`), so
the APZ hit test gives it the layers id of the process that owns the point and a click on an iframe of another site reaches
it; on the main thread, which is the controller thread, the dispatch is still in place and the event keeps its id. The
asynchronous route marks a synthesized event "async synthesized for tests", which would send a drag to the native drag loop:
`StealthJugglerNotAsyncSynthesized` (`StealthJugglerEventId.h`, one hook line in `nsContentUtils.cpp`) clears the flag for an event
that carries a Juggler id. The wheel takes the same route with `WHEEL_EVENT_ASYNC_ENABLED` and waits for the engine's delivery
callback. The renderer's ack of a mouse event comes from whichever process handled it; the page handler counts the acks of the
ids it sent, from every root of the page, and reads the landing verdict the owner root sent with its ack.

## Our files

- `dom/base/StealthJugglerInput.h`: `nsDOMWindowUtils::JugglerSendMouseEvent` and `JugglerSendDragEvent` (member definitions: they need the protected GetWidget and GetPresShell; the header is included by `nsDOMWindowUtils.cpp` alone). The mouse method takes 14 inputs and returns the id. `PARAM_BUFFER_COUNT` in `xptinfo.h` is 15 because XPConnect holds the 14 inputs and the return value of that method (14 + 1 XPT parameters); a 16th failed the build, so the argument `aLatency` took the place of the `aDisablePointerEvent` that the method ignored.
- `dom/base/StealthJugglerEventId.h`: the id on the event, the flag a Juggler event does not carry on the asynchronous route.
- `layout/base/StealthJugglerAck.h`: `StealthJugglerMouseAck`, the object that acks. It is the first local of `PresShell::HandleEvent`, so every way out of the function acks, after the handling and never before it (the observer runs JavaScript synchronously; a promise resumed from it would read the landing before the listeners below had recorded it). Zeroing the id after the notification is what makes it once: a nested HandleEvent on a child shell sees 0. The assert and `RecordModifiers` that come after it in the function neither read nor change the id and do not return, and no local lies between the old place and the new one, so the order of destruction is the one of before.
- `dom/events/StealthDragGesture.h` (B288): `StealthDragGestureBegin` and `StealthSkipDragGesture`. In a visible session the system's real pointer sits over the window, and its native moves reach the process during a press that Juggler sent: one from far away crossed the threshold and started a NATIVE drag out of a click on a link. That drag then ended on its own, the driver's release went to a drag session that no longer existed, and the click failed (measured on X11 with XTest moves during the press; seen on Windows as "session is null" in dispatchDragEvent). The id is set on every event from jugglerSendMouseEvent, carried across processes and coalescing, and is 0 for native input. A move whose Juggler origin differs from the press is still dispatched; it only does not count for the gesture, and tracking goes on.
- `dom/ipc/StealthJugglerCoalesce.h` (B217): `StealthCoalesceJugglerEventId`: the folded event takes the id of the LAST move folded into it, which is the one a caller waiting on "has my move landed" holds. The id was lost in the FF150 port (it was generated and written into a dictionary nobody read), and the ack with it.
- `widget/StealthMouseEventIPC.h` (B217): `mozilla::StealthReadJugglerEventId(aReader, aResult, aReadSoFar)`, the read of the id from the IPC message. It reads the id only when `aReadSoFar`, the result of Mozilla's read of the field before it, is true, so the stream order is the order of the write and nothing is consumed after a failed read.
- Gtests in `dom/ipc/gtest/` (`TestStealthDragGesture.cpp`, `TestStealthMouseEventIPC.cpp`, `TestStealthJugglerCoalesce.cpp`) and `layout/base/gtest/TestStealthJugglerMouseAck.cpp`.

## Hooks in Mozilla files

- `dom/base/nsDOMWindowUtils.cpp`:
  - registration: three includes in a block of ours after the `#undef GetClassName` block (`StealthCanvasAsDrawn.h` for fingerprint/canvas/as-drawn, `StealthInputEventBirth.h` for fingerprint/input/event-birth, `StealthJugglerInput.h`). The Juggler header defines members of nsDOMWindowUtils with qualified names and includes its own dependencies; it is included after Mozilla's includes now, where the X11 headers of the GTK block are already in: the Linux candidate build proves it.
  - declared exception (G35, approved): `SendWheelEvent` gets the parameter `double aLatency` (the last parameter; Mozilla's line `nsISynthesizedEventCallback* aCallback,` gets a comma). The C++ signature of an XPIDL method is generated from the IDL, so this and the IDL line are one change. Marker of fingerprint/input/event-birth.
  - anchor in `SendWheelEvent`: `StealthSetInputEventBirth(wheelEvent, aLatency, GetDocument());` right after `wheelEvent.mFlags.mIsSynthesizedForTests = true;` (fingerprint/input/event-birth): it stamps the local `wheelEvent` before the dispatch, and `GetDocument()` is a protected member of this, so the template cannot take `this`.
  - call wrap in `CanvasToDataSourceSurface` (static, used by `CompareCanvases` only): `nsLayoutUtils::SurfaceFromElement(aCanvas)` becomes `nsLayoutUtils::StealthSurfaceFromElementAsDrawn(aCanvas)`, a member template of `nsLayoutUtils` that makes the same call with the as-drawn flag (fingerprint/canvas/as-drawn); the line keeps `nsLayoutUtils::` and the argument. A chrome-only test hook of the browser; a page cannot call it.
- `dom/events/EventStateManager.cpp`: registration of `StealthDragGesture.h`; anchor in `BeginTrackingDragGesture` `StealthDragGestureBegin(mGestureDownFromJuggler, aMouseDownOrTouchDragEvent);` right after `mGestureDownButton = ...;` (a notice at the head would also run when the early return on a null mWidget leaves without starting a gesture, and would overwrite the flag of a gesture being tracked); anchor in `GenerateDragGesture` `if (StealthSkipDragGesture(mGestureDownFromJuggler, aMouseOrTouchOrPointerEvent)) return;` right after the `if (!IsTrackingDragGesture()) { return; }` block (a guard at the head would decide before that check). The field is passed, no friend.
- `dom/events/EventStateManager.h`: member `bool mGestureDownFromJuggler = false;`, after `mGestureDownButton`.
- `dom/interfaces/base/nsIDOMWindowUtils.idl`: declared exception (G35, approved) `[optional] in double aLatency` in `sendWheelEvent` (the previous line gets a comma); one line for `jugglerSendMouseEvent` and one for `jugglerSendDragEvent` (the second after `suppressAnimation`, so the two lines are not a run). The doc of both methods is at their implementations in `StealthJugglerInput.h`.
- `dom/ipc/CoalescedMouseData.cpp`: registration of `StealthJugglerCoalesce.h`; anchor in `Coalesce` `StealthCoalesceJugglerEventId(*mCoalescedInputEvent, aMouseOrPointerEvent);` right after the `mPressure` copy: only the else branch has a coalesced event (a call at the head would dereference null on the first event). `*mCoalescedInputEvent` is a field read: the base class gives no accessor.
- `layout/base/PresShell.cpp`: registration of `StealthJugglerAck.h` after the last Mozilla include; `StealthJugglerMouseAck jugglerMouseAck(aGUIEvent);` as the first statement of `PresShell::HandleEvent` (notice by object with scope, G10).
- `widget/MouseEvents.h`: member `uint32_t mJugglerEventId = 0;` after `mInputSource`, and its copy `mJugglerEventId = aEvent.mJugglerEventId;` as the first statement of `AssignMouseEventBaseData` (G44; the copy is independent of every field copied there, so first or last gives the same event). The id is the one `jugglerSendMouseEvent` handed back, 0 for every event that did not come from it.
- `widget/nsGUIEventIPC.h`: registration of `ipc/StealthMouseEventIPC.h` in a block of ours; anchor in `ParamTraits<WidgetMouseEventBase>::WriteForDerivedClass` `WriteParam(aWriter, aParam.mJugglerEventId);` after the last write of the block (G30), and, in `ReadForDerivedClass`, a wrap of Mozilla's last read of the `&&` chain: `ReadParam(aReader, &aResult->mInputSource)` becomes the third argument of `StealthReadJugglerEventId(aReader, aResult, ...)`, with Mozilla's expression unchanged (`aReader` and `aResult` are parameters of Mozilla's function). The id stays last in the stream; both sides are built together.
- `xpcom/reflect/xptinfo/xptinfo.h`: `PARAM_BUFFER_COUNT` 15 instead of 14 (declared value; the reason is in "Our files").
- `dom/ipc/gtest/moz.build`, `layout/base/gtest/moz.build`: registration of the gtests above and of `TestStealthSurfaceFlags.cpp` (fingerprint/canvas/as-drawn) (and `/dom/events` in the local includes of the first, where `StealthDragGesture.h` is).

## dom/events/EventStateManager.cpp: EventStateManager::GenerateDragGesture

See `dom/events/StealthDragGesture.h` above (B288).

## widget/MouseEvents.h: WidgetMouseEventBase::mJugglerEventId

See "Our files" (`StealthJugglerAck.h`, B217).

## Tests

The gtests prove the functions of ours: the decision table of the drag gesture (a Juggler press continues with Juggler moves only, a native press with native moves only; without the call of `StealthDragGestureBegin` a Juggler move is skipped), the id through an IPC message, read only when the field before it was read (after a failed read nothing is consumed), and through `Duplicate`/`AssignMouseEventData` (a fresh event reads 0), the coalescing (5 then 6 leaves 6; an event alone keeps its id; a later native move leaves 0) and the ack (once, "mousedown 7", id cleared; none for an event without an id, for an id another handler took, or for a message that has no type). The end to end tests of the wrapper prove the hooks through the browser: the call of the driver returns only when the renderer acked the id.
