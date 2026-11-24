/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/**
 * A visible pointer in the CHROME window, for watching an automated session.
 *
 * ⛔ IT IS NOT A STEALTH FEATURE AND IT IS NOT A HUMANIZE FEATURE. It draws
 * nothing the page can reach and it changes no event the page receives: it
 * exists so a person watching the monitor, or a screen recording made from
 * outside the browser, can see where the pointer is.
 *
 * ⛔ WHETHER IT IS ON IS NOT DECIDED HERE. This file reads
 * `stealthfox.showcursor` and obeys; the value is declared by
 * `invisible_core.prefs.DEFAULT_SHOW_CURSOR`, which since 2026-08-28 is true.
 * The `getBoolPref(PREF, false)` fallback below is not a competing default -
 * it answers the different question "this profile was not written by us". The
 * argument against shipping it on has not gone away and is recorded next to
 * that constant: a pointer moving on its own says "this is a bot" to anybody
 * looking at the screen.
 *
 * ⛔ IN THE CHROME DOCUMENT, NEVER IN THE PAGE. The overlay is a node in the
 * browser UI's own document, which runs in a different process from the
 * content: page JavaScript cannot see it, cannot find it with a selector,
 * cannot hit it with `elementFromPoint`, and cannot photograph it - it is
 * absent from `page.screenshot()`, which is a consequence and not a
 * limitation. Drawing it in the page's document would be a DOM node a site can
 * enumerate, which is a tell and breaks rule 12.
 *
 * ⛔ WHY IT CAN WORK AT ALL. Juggler dispatches the mouse INTO THE CHROME
 * WINDOW: `Page.dispatchMouseEvent` takes the `<browser>` bounding box and
 * calls `win.windowUtils.jugglerSendMouseEvent(...)` with page coordinates
 * offset into chrome space (`protocol/PageHandler.js`). So a `mousemove`
 * listener on the chrome document sees automated movement in exactly the
 * coordinates this overlay needs. ⛔ THAT IS THE LOAD-BEARING ASSUMPTION of
 * this file and it is VERIFIED, not assumed: `tests/gates/chrome_cursor.py`
 * drives `page.mouse.move` and reads the counter this object keeps.
 *
 * ⛔ AND IT IS OURS, NOT MOZILLA'S. Another anti-detect Firefox fork does this by patching
 * `browser/base/content/browser-init.js`, a Mozilla file, which is a conflict
 * to resolve at every major. Everything here lives under `juggler/`, which we
 * already own, and the only foreign line is two in `TargetRegistry.js`.
 */

const PREF_ENABLED = 'stealthfox.showcursor';

// ── the drawing ─────────────────────────────────────────────────────────────
//
// ⛔ IT IS THE WINDOWS ARROW, NOT A DOT, and the shape is the point of the
// feature rather than decoration. The overlay exists so a person watching the
// screen can follow what the automation is doing; a coloured circle reads as
// an instrument, an arrow reads as a pointer, and this project's whole target
// is looking like Windows. The path below is the standard arrow geometry -
// tip at the origin, the notch and tail on the lower right - drawn white with
// a dark outline exactly as the system one is, so what is ours is the colour
// AROUND it and not the cursor itself.
//
// The palette is the package logo's, sampled from `invisible_playwright-logo.png`:
// the two masks are #6CD830 green and #E42430 red over a #0C1824 outline.
//
// ⛔ ONE COLOUR, AND THE CLICK CHANGES THE SIZE RATHER THAN THE HUE. The first
// version turned the halo red while the button was down, which is the obvious
// way to show a press and the wrong one here: two colours read as two states
// of the TOOL, and a person watching then has to learn what red means. Widening
// the same green says "something happened" without adding a vocabulary.
const LOGO_INK = '%230C1824';      // the logo's outline navy, URL-encoded
const LOGO_GREEN = '108, 216, 48';
const GLOW_IDLE = `rgba(${LOGO_GREEN}, .95)`;
const GLOW_IDLE_SOFT = `rgba(${LOGO_GREEN}, .6)`;
const GLOW_PRESSED = `rgba(${LOGO_GREEN}, 1)`;
const GLOW_PRESSED_SOFT = `rgba(${LOGO_GREEN}, .75)`;
const RING_COLOUR = `rgba(${LOGO_GREEN}, .9)`;
//: The artwork, in viewBox units. The real Windows arrow is 12x19.
const ARROW_ART_W = 12;
const ARROW_ART_H = 19;
//: Room kept around it so the stroke is not clipped: the outline is 1.3 wide
//: and half of it falls outside the path.
const ARROW_PAD = 1;
//: How many pixels one viewBox unit is drawn as. Larger than 1 so the pointer
//: stays legible on a high-DPI screen, which is what a person watching is
//: looking at.
const ARROW_SCALE = 1.4;
const ARROW_W = (ARROW_ART_W + 2 * ARROW_PAD) * ARROW_SCALE;
const ARROW_H = (ARROW_ART_H + 2 * ARROW_PAD) * ARROW_SCALE;
//: ⛔ WHERE THE TIP SITS INSIDE ITS OWN BOX, and the reason every number above
//: is derived rather than typed. The padding pushes the artwork away from the
//: box origin, so the tip - which IS the hotspot - lands `ARROW_PAD` units in
//: from the corner. The first version wrote the box as a flat `17 x 27` and
//: left that offset uncompensated: the arrow drew about 1.2px below and right
//: of the coordinate it was reporting, and the two axes were scaled by
//: slightly different factors (17/14 against 27/21), so the shape was
//: distorted as well. Neither is visible in a photograph, which is what makes
//: it worth deriving: the relation is now true BY CONSTRUCTION instead of
//: because two hand-written numbers happened to agree.
const ARROW_OFFSET = ARROW_PAD * ARROW_SCALE;

/**
 * The arrow as a data URI.
 *
 * ⛔ URL-ENCODED BY HAND, and the `#` is why. A `data:image/svg+xml` inside a
 * CSS `url()` is parsed as a URL, so a raw `#` in a colour starts a fragment
 * and silently truncates the SVG - the rule still applies, the background just
 * never paints, and the cursor is invisible with no error anywhere. `%23` is
 * the fix; `<` and `>` are left alone because they are legal in a quoted
 * url() and encoding them costs readability for nothing.
 */
function _arrowSvg() {
  return 'data:image/svg+xml;utf8,' +
      `<svg xmlns='http://www.w3.org/2000/svg' width='${ARROW_W}'` +
      ` height='${ARROW_H}'` +
      ` viewBox='${-ARROW_PAD} ${-ARROW_PAD}` +
      ` ${ARROW_ART_W + 2 * ARROW_PAD} ${ARROW_ART_H + 2 * ARROW_PAD}'>` +
      `<path d='M0 0 L0 16.6 L4.1 12.7 L6.7 18.6 L9.4 17.4 L6.8 11.6 L11.7 11.6 Z'` +
      ` fill='%23FFFFFF' stroke='${LOGO_INK}' stroke-width='1.3'` +
      ` stroke-linejoin='round'/></svg>`;
}
// ⛔ The move counter is PUBLISHED as a pref, and that is not a debug
// leftover: there is no protocol command that evaluates in the chrome window,
// so a gate has no other way to ask whether this listener ever fired. A pref
// survives into `prefs.js` when the profile is written, which is exactly the
// channel a test can read after shutdown. Inventing a protocol command instead
// would add a field `checkScheme` validates only at runtime - the failure class
// a rebase reintroduces in silence.
//: How many rings at most stay queued for the next frame. See
//: `_onDown`: it is a ceiling against accumulation when rAF does not fire, not an
//: aesthetic choice.
const MAX_PENDING_RINGS = 3;

const PREF_MOVES = 'stealthfox.showcursor.moves';
// ⛔ How many overlays are alive. Same channel and same reason as the counter
// above, and it exists because the property it reports cannot be checked any
// other way: nothing outside the parent process can look at the chrome
// document and count nodes.
const PREF_OVERLAYS = 'stealthfox.showcursor.overlays';
const NODE_ID = '__stealth_cursor__';
// ⛔ There is no interval any more, and the measurement is why. A pref write
// on a timer was still a parent-process write in the path of input delivery,
// and `tests/gates/chrome_cursor_cost.py` caught it: 1 ms on the gap the PAGE
// measures between its own mousemove events, p = 0.0005. The count is now
// written once at the first event and once at teardown.
//
// ⛔ AND REMOVING IT DID NOT MAKE THE FEATURE FREE, WHICH IS WHAT THE GREEN
// AFTERWARDS SAID. That run was taken on a machine with another browser
// alive: noise inflates the variance and makes the permutation test less
// sensitive, so a real difference read as 0.000 ms. Measured on 2026-08-28 on
// a machine the gate itself certified idle, the SAME 1 ms shift was still
// there - with the arrow, and with the circle that predates it, so it was
// never about the drawing. The A/A control, where this file refuses to build
// the overlay at all while the bench believes it is comparing on against off,
// reports 0.000 ms and p = 1.0000: the statistic does not accuse itself.
// A false green under load left two places claiming this cost nothing.

/**
 * ⛔ ONE OVERLAY PER CHROME WINDOW, NOT PER PAGE, and the difference is
 * reachable rather than theoretical. `TargetRegistry.newPage` opens a window
 * of its own for every page, so most of the time the two are the same thing -
 * but a `noopener` popup opened by page JavaScript lands as a SECOND TAB IN
 * THE SAME WINDOW, and `TargetRegistry.js` says so in its own comment. With an
 * instance per `PageTarget` that window would then carry two listeners doing
 * two style writes on every mouse event, and two `<div>` elements sharing one
 * id.
 *
 * The dot is a property of the WINDOW - it is drawn in the window's document
 * and positioned in the window's coordinates - so the window is where it has
 * to be owned. A refcount rather than a plain cache, because the second tab
 * closing must not take the overlay away from the first.
 */
const _perWindow = new WeakMap();
let _live = 0;
let _peak = 0;

export class StealthCursor {
  /** The overlay for this chrome window, created once and shared. */
  static forWindow(win) {
    let entry = _perWindow.get(win);
    if (!entry) {
      entry = {cursor: new StealthCursor(win), refs: 0};
      _perWindow.set(win, entry);
    }
    entry.refs++;
    return entry.cursor;
  }

  /** One holder is done with it. The last one out disposes it. */
  static releaseWindow(win) {
    const entry = _perWindow.get(win);
    if (!entry)
      return;
    if (--entry.refs > 0)
      return;
    _perWindow.delete(win);
    entry.cursor.dispose();
  }

  static _publishCount(delta) {
    // ⛔ CALLED FROM THE CONSTRUCTOR, not from `forWindow`, and the difference
    // was found by running the mutation rather than by reading the code. With
    // the call in `forWindow`, restoring the old per-page construction made
    // the pref DISAPPEAR instead of reading 2 - so the number was reporting
    // "somebody used the shared entry point", which is not the property being
    // asserted. Counting where the objects are actually built says one against
    // two, which is the thing that had to be distinguishable.
    //
    // ⛔ And it counts OVERLAY OBJECTS, not holders. Counting holders would
    // report 2 for two tabs in one window under BOTH the correct arrangement
    // and the broken one, so the number could never fail.
    _live += delta;
    if (_live < 0)
      _live = 0;
    // ⛔ THE PEAK IS WHAT IS PUBLISHED, not the live count, and that is not a
    // stylistic choice: `prefs.js` is written at SHUTDOWN, by which time every
    // target has disposed and the live count is 0. A gate reading the live
    // number would see 0 whatever happened during the session - a value that
    // can never fail is not an assertion.
    if (_live > _peak) {
      _peak = _live;
      try { Services.prefs.setIntPref(PREF_OVERLAYS, _peak); }
      catch (e) {}
    }
  }

  constructor(win) {
    this._win = win;
    this._dot = null;
    this._style = null;
    //: The last position seen, and the frame already requested. NO input
    //: handler touches the DOM: they record numbers, and `_paint` draws on the frame.
    //: See the comment above `_schedule`.
    this._pendingX = 0;
    this._pendingY = 0;
    this._pendingVisible = false;
    this._pendingPressed = false;
    //: A press SEEN since the last time we painted. It is needed
    //: because a fast click opens and closes inside the same frame: without
    //: it, `pressed` would never be painted and the press would vanish
    //: from the drawing instead of from the input path.
    this._sawDown = false;
    //: How many rings to spawn at the next frame. A counter, not a node:
    //: creating the element here would put back into the handler exactly the work
    //: that this change removes.
    this._pendingRings = 0;
    this._frame = 0;
    this._listening = false;
    // ⛔ Counted for the gate, and it is the only reason this field exists.
    // A test that asserts "the dot moved" by looking at a style attribute is
    // asserting on our own write; counting the events we RECEIVED is asserting
    // that the chrome window is reached at all, which is the thing that was
    // never certain.
    this.moves = 0;
    this._published = 0;
    this._counted = true;
    StealthCursor._publishCount(1);

    this._onMove = this._onMove.bind(this);
    this._onDown = this._onDown.bind(this);
    this._onUp = this._onUp.bind(this);
    this._onLeave = this._onLeave.bind(this);
    this._onPrefChanged = this._onPrefChanged.bind(this);

    Services.prefs.addObserver(PREF_ENABLED, this._onPrefChanged);
    if (this._wanted())
      this._enable();
  }

  _wanted() {
    // ⛔ THIS `false` IS NOT THE PRODUCT'S DEFAULT. It answers "nobody wrote
    // this pref", which is a profile we did not create; the shipped default is
    // declared by `invisible_core.prefs.DEFAULT_SHOW_CURSOR` and has been true
    // since 2026-08-28. Reading this line as the default is how a compiled
    // fallback becomes a second source of truth.
    try { return Services.prefs.getBoolPref(PREF_ENABLED, false); }
    catch (e) { return false; }
  }

  _stepMs() {
    // ⛔ READ, never written here. The same number in two places is exactly
    // the duplication that caused the defect in section 32 of
    // `20-our-patches.md`: the motion planner already owns this value, so the
    // overlay's transition asks IT rather than carrying a copy that can drift.
    try { return Services.prefs.getIntPref('stealthfox.humanize.stepMs', 10); }
    catch (e) { return 10; }
  }

  _onPrefChanged() {
    if (this._wanted())
      this._enable();
    else
      this._disable();
  }

  _enable() {
    if (this._listening)
      return;
    this._build();
    // ⛔ `{passive: true}` and capture FALSE, both deliberate. Passive
    // guarantees this listener can never call `preventDefault`, so it cannot
    // change what the content receives; bubble phase means it runs after the
    // event has already been dispatched onward rather than in front of it.
    // Together they remove the only credible way this overlay could become
    // visible to a page: by delaying or altering input.
    const opts = {passive: true, capture: false};
    this._win.addEventListener('mousemove', this._onMove, opts);
    this._win.addEventListener('mousedown', this._onDown, opts);
    this._win.addEventListener('mouseup', this._onUp, opts);
    this._win.addEventListener('mouseleave', this._onLeave, opts);
    this._listening = true;
  }

  _disable() {
    if (this._listening) {
      const opts = {capture: false};
      this._win.removeEventListener('mousemove', this._onMove, opts);
      this._win.removeEventListener('mousedown', this._onDown, opts);
      this._win.removeEventListener('mouseup', this._onUp, opts);
      this._win.removeEventListener('mouseleave', this._onLeave, opts);
      this._listening = false;
    }
    // ⛔ REMOVED, not hidden. "Off" has to mean the node is absent: a hidden
    // node is still a node, and a gate that asserts on visibility passes on a
    // switch that does not switch anything.
    if (this._dot) {
      this._dot.remove();
      this._dot = null;
    }
    // (!) The requested frame must be CANCELLED: a callback that fires after the
    // node has been removed writes to a detached element, and on a window
    // that is closing it is a console error that nobody explains.
    if (this._frame) {
      try { this._win.cancelAnimationFrame(this._frame); } catch (e) {}
      this._frame = 0;
    }
    if (this._style) {
      this._style.remove();
      this._style = null;
    }
  }

  _build() {
    if (this._dot)
      return;
    const doc = this._win.document;
    const root = doc.documentElement;
    if (!root)
      return;

    this._style = doc.createElement('style');
    // ⛔ `transform`, never `left`/`top`. Position through the transform with
    // `will-change` keeps the dot on its own compositor layer; writing
    // left/top relayouts the chrome document on every mouse event, which is
    // work done in the parent process while an input event is in flight - the
    // one thing that could make this measurable from the page.
    //
    // ⛔ `pointer-events: none` and no `cursor:` declaration, so the overlay
    // never enters the chrome hit-test and never changes what is under the
    // pointer.
    // ⛔ THE HOTSPOT IS THE ELEMENT'S ORIGIN, NOT ITS CENTRE, and that is what
    // separates an arrow from the dot this replaced. A dot is symmetric, so
    // centring it on the coordinate with a negative margin put the drawing
    // where the pointer was. An arrow points: its tip is the hotspot, exactly
    // as Windows defines it, and the tip is at (0,0) of the artwork. Any
    // margin here would draw the cursor beside the place it is actually
    // clicking, which is worse than a dot - it would look right and lie.
    this._style.textContent = `
      #${NODE_ID} {
        position: fixed; top: 0; left: 0;
        width: ${ARROW_W}px; height: ${ARROW_H}px;
        margin: ${-ARROW_OFFSET}px 0 0 ${-ARROW_OFFSET}px;
        background: url("${_arrowSvg()}") no-repeat 0 0 / 100% 100%;
        filter: drop-shadow(0 0 5px ${GLOW_IDLE})
                drop-shadow(0 0 13px ${GLOW_IDLE_SOFT});
        pointer-events: none;
        z-index: 2147483647;
        opacity: 1;
        will-change: transform;
        transition: transform ${this._stepMs()}ms linear, opacity 120ms linear;
      }
      #${NODE_ID}.pressed {
        filter: drop-shadow(0 0 6px ${GLOW_PRESSED})
                drop-shadow(0 0 20px ${GLOW_PRESSED_SOFT});
      }
      #${NODE_ID} > .ring {
        position: absolute; top: 0; left: 0;
        width: 14px; height: 14px; margin: -7px 0 0 -7px;
        border-radius: 50%;
        border: 2px solid ${RING_COLOUR};
        pointer-events: none;
        animation: __stealth_cursor_ring__ 380ms ease-out forwards;
      }
      @keyframes __stealth_cursor_ring__ {
        from { transform: scale(1);   opacity: .9; }
        to   { transform: scale(3.4); opacity: 0;  }
      }
    `;
    root.appendChild(this._style);

    this._dot = doc.createElement('div');
    this._dot.id = NODE_ID;
    root.appendChild(this._dot);
  }

  _onMove(event) {
    this.moves++;
    // ⛔ ONCE, on the first event, and then never again in this path. The
    // first version wrote the count every 250 ms, and the bench found what
    // that cost: with the overlay on, the gap between the mousemove events
    // THE PAGE receives moved by 1 ms with p = 0.0005 - a real, page-visible
    // difference, produced not by the feature but by the instrumentation
    // measuring it. A parent-process pref write sits directly in the path of
    // input delivery.
    //
    // The number the gate actually reads is written in `dispose()`, where it
    // costs nothing. This one write exists so that "the pref is absent" keeps
    // its unambiguous meaning - the listener never fired - instead of also
    // meaning "the browser did not shut down cleanly".
    if (!this._published) {
      this._published = 1;
      this._publishMoves();
    }
    if (!this._dot)
      return;
    // (!) THE STYLE WRITE DOES NOT HAPPEN HERE, and this is the second time
    // that work inside the input delivery path has been removed from
    // this file. The first was a pref written on a timer; this is the
    // `transform` written inside the mousemove handler, that is, in the parent
    // process while an input event is in flight.
    //
    // Measured on 2026-08-28 on a machine TRULY idle: with the overlay on
    // the median distance between the mousemove events that THE PAGE receives shifts by
    // one whole step (18 ms against 17), p = 0.0005 - and it happens with the circle
    // as with the arrow, so it is not the drawing. The A/A control - the
    // bench that believes it compares on against off while the overlay never
    // turns on - reports 0.000 ms and p = 1.0000, so the statistic does not
    // accuse itself.
    //
    // (!) AND THE PREVIOUS MEASUREMENT THAT SAID "0.000 ms" WAS TAKEN UNDER LOAD.
    // Noise inflates the variance and makes the permutation test less
    // sensitive: it was a false green, and it left written in two places that
    // this function cost zero.
    //
    // The position is only recorded; the drawing is done by the next frame.
    // (!) THE NUMBERS, NOT THE EVENT. Holding the event object across a
    // frame keeps it alive together with what it points to, and this file has already
    // paid once for an object that outlived its round.
    this._pendingX = event.clientX;
    this._pendingY = event.clientY;
    this._pendingVisible = true;
    this._schedule();
  }

  // (!) ONLY ONE PLACE TOUCHES THE DOM, and this is the reason why the
  // fix of 2026-08-28 was not enough. That one deferred the `transform`
  // of `_onMove` alone and left the other three handlers writing synchronously
  // inside the input delivery: `_onDown` added a class, CREATED A
  // NODE, attached a listener to it and appended it starting an animation,
  // that is more work than what had been removed; `_onUp` removed a
  // class; `_onLeave` wrote the opacity. Fixing only `_onDown` would have
  // been a patch: after the fix the places that write would still have been
  // more than one.
  //
  // The rule now is one and holds for all: **a handler records numbers and
  // asks for the frame, it touches nothing**. The one that draws is `_paint`, and the one that
  // calls it is the frame.
  _schedule() {
    if (this._frame)
      return;
    this._frame = this._win.requestAnimationFrame(() => {
      this._frame = 0;
      this._paint();
    });
  }

  _paint() {
    if (!this._dot)
      return;
    this._dot.style.opacity = this._pendingVisible ? '1' : '0';
    this._dot.style.transform =
        `translate3d(${this._pendingX}px, ${this._pendingY}px, 0)`;
    // (!) A press seen inside this frame is painted EVEN if the
    // release has already arrived: a fast click is born and dies between two frames,
    // and without this the class would never appear. The release is done by the
    // next frame, which is requested below.
    const press = this._pendingPressed || this._sawDown;
    this._dot.classList.toggle('pressed', press);
    while (this._pendingRings > 0) {
      this._pendingRings--;
      const ring = this._win.document.createElement('div');
      ring.className = 'ring';
      ring.addEventListener('animationend', () => ring.remove(), {once: true});
      this._dot.appendChild(ring);
    }
    if (this._sawDown) {
      this._sawDown = false;
      if (!this._pendingPressed)
        this._schedule();
    }
  }

  _publishMoves() {
    try { Services.prefs.setIntPref(PREF_MOVES, this.moves); }
    catch (e) {}
  }

  _onDown(event) {
    // (!) NO DOM HERE. Until 2026-08-31 this handler ran synchronously
    // inside the delivery of the mousedown and created a node, attached a
    // listener to it and appended it starting an animation - more work than the
    // `transform` that the remedy of 2026-08-28 had removed from `_onMove`
    // because it shifted by one whole step the times that THE PAGE measures.
    // The same shape, on the click path, was not measured by any
    // gate: `chrome_cursor_cost.py` injects and listens only to `mousemove`, that is
    // the branch already fixed. The bench that looks at this one is
    // `chrome_cursor_click_cost.py`.
    //
    // The ring stays, with its measured why: a press is read
    // as the halo that SWELLS - 802 pixels of glow against 715 at rest,
    // +12% - and not as an outline that widens, because the halo is of
    // one colour only. Only WHEN it is built changes: at the frame, not
    // in the event.
    this._pendingPressed = true;
    this._sawDown = true;
    // (!) With a ceiling: if the chrome window goes to the background rAF stops
    // firing, and without this every press would accumulate a ring to be
    // built all at once on return. Only one is seen at a time anyway -
    // the animation lasts less than the distance between two clicks - so the ceiling
    // removes nothing visible and removes a burst of nodes.
    if (this._pendingRings < MAX_PENDING_RINGS)
      this._pendingRings++;
    this._schedule();
  }

  _onUp(event) {
    this._pendingPressed = false;
    this._schedule();
  }

  _onLeave(event) {
    // ⛔ Without this the dot stays frozen wherever the pointer left the
    // window, which looks exactly like a stuck automation and is the opposite
    // of what a person watching wants to see.
    this._pendingVisible = false;
    this._schedule();
  }

  dispose() {
    try { Services.prefs.removeObserver(PREF_ENABLED, this._onPrefChanged); }
    catch (e) {}
    this._disable();
    // ⛔ The number the gate reads, written where it costs nothing: teardown
    // happens once, off the input path, and `prefs.js` is flushed after it.
    this._publishMoves();
    // ⛔ Guarded: `dispose()` is reachable twice (the refcount drops to zero,
    // and a caller holding the object calls it directly), and a live count
    // that can go down twice for one object reports fewer overlays than exist
    // - which is the direction that hides the defect this number exists to
    // catch.
    if (this._counted) {
      this._counted = false;
      StealthCursor._publishCount(-1);
    }
    this._win = null;
  }
}

