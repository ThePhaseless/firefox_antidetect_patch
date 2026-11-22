// `Page.ready` leaves the parent behind everything its main frame said before it, and the dialogs follow it.
//
// The content process now says `frameDocumentInserted` and then `pageReady` (the_page_is_said_ready_after_its_document).
// In the parent the commit of the main frame is held by PageHandler._emitFrameKeyed while the client does not know the
// frame yet (the announcement comes from the parent's FrameLifecycle, a channel of its own), or behind a name or a `load`
// of the frame; `pageReady` went out at once, `Page.ready` before the commit it follows, and a client that announces a
// popup after `Page.ready` read the address the popup was born with. `Page.ready` now goes through the same
// _emitFrameKeyed, keyed by the main frame the content process names, with an event that is not lost (a frame dropped, a
// full queue, no frame named leave it at once). The page counts as ready, and the dialogs that were open are told, when
// `Page.ready` is written for the client, not when `pageReady` arrives.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function load(file, scope, names) {
  const source = fs.readFileSync(path.join(ROOT, file), 'utf8').replace(/^export /gm, '');
  vm.createContext(scope);
  vm.runInContext(source + `\n;globalThis.__names = { ${names.join(', ')} };`, scope);
  return scope.__names;
}
const plain = x => JSON.parse(JSON.stringify(x));

const { Helper } = load('Helper.js', {
  Cc: { '@mozilla.org/uuid-generator;1': { getService: () => ({}) } }, Ci: {}, ChromeUtils: { importESModule: () => ({}) },
}, ['Helper']);
const { FrameNavigations } = load('FrameNavigations.js', {}, ['FrameNavigations']);

const dialog = { id: () => 'dialog-1', type: () => 'alert', message: () => 'hi', defaultValue: () => '' };

function pageHandler() {
  const scope = { Components: { classes: {}, interfaces: {}, utils: {}, results: {} }, dump: () => {}, setTimeout, clearTimeout };
  scope.ChromeUtils = { importESModule: url => url.endsWith('Helper.js') ? { Helper, EventWatcher: class {} }
      : url.endsWith('Timer.sys.mjs') ? { setTimeout, clearTimeout }
      : url.endsWith('FrameNavigations.js') ? { FrameNavigations } : new Proxy(function () {}, { get: () => class {} }) };
  const { PageHandler } = load('protocol/PageHandler.js', scope, ['PageHandler']);
  const events = [];
  const h = Object.create(PageHandler.prototype);
  h._workersNotToldYet = new Map();
  h._workers = new Map();
  h._droppedFrameIds = new Set();
  h._restoreBeingSaid = false;
  h._isPageReady = false;
  h._session = { emitEvent: (name, payload) => events.push([name, payload === undefined ? undefined : plain(payload)]) };
  h._reportedFrameIds = new Set();
  h._liveFrameIds = new Set();
  h._parentOfFrame = new Map();
  h._frameEventsBeforeFrame = new Map(); h._contextFrame = new Map(); h._contextsOfFrame = new Map();
  h._eventsAfterName = new Map(); h._heldBackFrames = new Map();
  h._pageNetwork = { onMainFrameNavigationCommitted() {} };
  h._frameLifecycle = { reannounceBelow() {}, framesBelow: () => [] };
  h._frameNavigations = new FrameNavigations(h._onFrameNavigationEvent.bind(h));
  h._pageTarget = { dialogs: () => [dialog], frameIdToBrowsingContext: () => undefined };
  return { h, events };
}

const names = events => events.map(([name]) => name);
const main = { frameId: 'mainframe-1', parentFrameId: undefined };

// The document of the main frame arrives from the content process: its navigation started, then its document.
function documentArrives(h, navigationId = 'nav-1') {
  h._unlessDropped('mainframe-1', () => h._frameNavigations.onContentNavigationStarted('mainframe-1', navigationId));
  h._unlessDropped('mainframe-1', () => h._frameNavigations.onDocumentInserted('mainframe-1', 'https://popup.test/', '', navigationId));
}

test('the ready of a page whose main frame the client does not know yet goes after the frame and after its commit', () => {
  const { h, events } = pageHandler();
  h._onDialogOpened(dialog);                       // a dialog of the page, before the page is ready: nothing says it yet
  documentArrives(h);
  h._onPageReady({ frameId: 'mainframe-1' });
  assert.deepEqual(events, [], 'nothing leaves for a frame the client does not know, and the ready is not the exception');
  assert.equal(h._isPageReady, false, 'the page is not ready for the client before `Page.ready` is written');
  h._onFrameAttached(main);
  assert.deepEqual(names(events), ['Page.frameAttached', 'Page.navigationStarted', 'Page.navigationCommitted', 'Page.ready', 'Page.dialogOpened']);
  assert.equal(events.find(([name]) => name === 'Page.ready')[1], undefined, '`Page.ready` has no payload');
  assert.equal(h._isPageReady, true);
});

test('the ready of a frame the client knows leaves at once, with its dialogs after it, and an event of the frame keeps its order with it', () => {
  const { h, events } = pageHandler();
  h._onFrameAttached(main);
  events.length = 0;
  h._onPageReady({ frameId: 'mainframe-1' });
  assert.deepEqual(names(events), ['Page.ready', 'Page.dialogOpened']);
  h._emitFrameKeyed('Page.eventFired', { frameId: 'mainframe-1', name: 'load' }, 'mainframe-1');
  assert.deepEqual(names(events), ['Page.ready', 'Page.dialogOpened', 'Page.eventFired']);
});

test('a repeated ready is repeated', () => {
  const { h, events } = pageHandler();
  h._onFrameAttached(main);
  events.length = 0;
  h._onPageReady({ frameId: 'mainframe-1' });
  h._onPageReady({ frameId: 'mainframe-1' });
  assert.deepEqual(names(events).filter(name => name === 'Page.ready'), ['Page.ready', 'Page.ready']);
});

test('the ready waits behind the events of its frame that wait behind a name, and goes with them', () => {
  const { h, events } = pageHandler();
  h._onFrameAttached(main);
  events.length = 0;
  const queue = [];
  h._eventsAfterName.set('mainframe-1', queue);    // a commit of the frame waits for its name
  h._emitFrameKeyed('Page.eventFired', { frameId: 'mainframe-1', name: 'load' }, 'mainframe-1');
  h._onPageReady({ frameId: 'mainframe-1' });
  assert.deepEqual(events, [], 'nothing leaves, and the page is not ready yet');
  assert.equal(h._isPageReady, false);
  h._eventsAfterName.delete('mainframe-1');
  h._flushAfterName('mainframe-1', queue);
  assert.deepEqual(names(events), ['Page.eventFired', 'Page.ready', 'Page.dialogOpened']);
});

test('the ready of a frame the client never heard of and that is gone leaves at once', () => {
  const { h, events } = pageHandler();
  h._droppedFrameIds.add('mainframe-1');
  h._onPageReady({ frameId: 'mainframe-1' });
  assert.deepEqual(names(events), ['Page.ready', 'Page.dialogOpened']);
  assert.equal(h._isPageReady, true);
});

test('the ready that waits for its frame when the frame is dropped is not lost', () => {
  const { h, events } = pageHandler();
  h._onPageReady({ frameId: 'mainframe-1' });
  assert.deepEqual(events, []);
  h._dropBufferedFrameEvents('mainframe-1');
  assert.deepEqual(names(events), ['Page.ready', 'Page.dialogOpened']);
  assert.equal(h._isPageReady, true);
});

test('the ready leaves at once when the events waiting for its frame are at the limit', () => {
  const { h, events } = pageHandler();
  for (let i = 0; i < 1000; i++)
    h._handleNetworkEvent('Network.requestWillBeSent', { requestId: 'r' + i }, 'mainframe-1');
  h._onPageReady({ frameId: 'mainframe-1' });
  assert.deepEqual(names(events), ['Page.ready', 'Page.dialogOpened'], 'the 1001st event is not kept, the ready is not that kind of event');
  assert.equal(h._frameEventsBeforeFrame.get('mainframe-1').length, 1000);
});

test('the ready with no frame named leaves at once, as it did', () => {
  const { h, events } = pageHandler();
  h._onPageReady({});
  assert.deepEqual(names(events), ['Page.ready', 'Page.dialogOpened']);
  const other = pageHandler();
  other.h._eventsAfterName.set('subframe-2', [['Page.eventFired', { frameId: 'subframe-2', name: 'load' }]]);
  other.h._onPageReady(undefined);
  assert.deepEqual(names(other.events), ['Page.ready', 'Page.dialogOpened'], 'an event of no frame is not held behind the name of another');
});
