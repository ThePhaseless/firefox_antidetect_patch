// The network ends a frame left in the queue behind its `load` are told when the frame detaches, loaded the way the parent
// loads PageHandler.js.
//
// The `load` of a frame waits while a frame below it has no first document yet, and what the frame says after it waits
// behind it (PageHandler._loadsBehindFirstDocuments). When that frame detached, the queue was deleted with it: a
// `Network.requestFinished` or `Network.requestFailed` it held was never told, though the client had heard the start of the
// request (it was told before the `load`): a request that began and never ended, and networkidle waited for it for ever.
// Now the ends the queue holds leave before `Page.frameDetached`, each with the `Network.responseReceived` that is held too,
// but only the ends of requests whose start the client was told: a request whose `Network.requestWillBeSent` is held in the same
// queue was never heard of, and is dropped whole. The rest of the queue is dropped, as it was.
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

const anything = new Proxy(function () {}, { get: () => class {} });
const { PageHandler } = load('protocol/PageHandler.js', {
  Components: { classes: {}, interfaces: {}, utils: {}, results: {} },
  ChromeUtils: { importESModule: () => anything },
  dump: () => {},
}, ['PageHandler']);

// A handler with the fields the frame gate and the queues use, as the constructor leaves them. The frame `f2`, below `f1`,
// is held back and waits for its first document: it holds the `load` of `f1`.
function pageHandler({ announce = true } = {}) {
  const events = [];
  const handler = Object.create(PageHandler.prototype);
  handler._workersNotToldYet = new Map();
  handler._restoreBeingSaid = false;
  handler._session = { emitEvent: (name, payload) => events.push([name, JSON.parse(JSON.stringify(payload ?? null))]) };
  handler._reportedFrameIds = new Set();
  handler._droppedFrameIds = new Set();
  handler._liveFrameIds = new Set();
  handler._parentOfFrame = new Map();
  handler._heldBackFrames = new Map();
  handler._frameNavigations = { forget() {}, waitsForItsFirstDocument: id => id === 'f2' };
  handler._frameEventsBeforeFrame = new Map();
  handler._eventsAfterName = new Map();
  handler._contextFrame = new Map();
  handler._contextsOfFrame = new Map();
  handler._workers = new Map();
  if (announce)
    handler._onFrameAttached({ frameId: 'f1', parentFrameId: 'main' });
  handler._heldBackFrames.set('f2', { frameId: 'f2', parentFrameId: 'f1' });
  events.length = 0;
  return { handler, events };
}

const say = (handler, name, payload) => handler._emitFrameKeyed(name, payload, 'f1');
const names = events => events.map(([name, payload]) => payload && payload.requestId ? name + ' ' + payload.requestId : name);

test('a frame that detaches with its load held tells the network ends held behind it, before Page.frameDetached', () => {
  const { handler, events } = pageHandler();
  say(handler, 'Page.eventFired', { frameId: 'f1', name: 'load' });
  // r1 and r3 began before the load: the client heard of them, only their ends wait here.
  say(handler, 'Network.responseReceived', { requestId: 'r1' });
  say(handler, 'Network.requestFinished', { requestId: 'r1' });
  say(handler, 'Network.responseReceived', { requestId: 'r2' });      // no end for it: dropped with the rest
  say(handler, 'Network.requestFailed', { requestId: 'r3' });
  say(handler, 'Runtime.console', { type: 'log' });
  assert.deepEqual(events, [], 'nothing leaves while the load is held');

  handler._onFrameDetached('f1');
  assert.deepEqual(names(events), [
    'Network.responseReceived r1',
    'Network.requestFinished r1',
    'Network.requestFailed r3',
    'Page.frameDetached',
  ], 'the ends, in order, with the response that belongs to one of them, and before the detach');
  assert.equal(handler._behindFirstDocuments.has('f1'), false, 'the queue is gone');
});

test('a request whose start and end are both held behind the load is not told at all: the client never heard of it', () => {
  const { handler, events } = pageHandler();
  say(handler, 'Page.eventFired', { frameId: 'f1', name: 'load' });
  say(handler, 'Network.requestWillBeSent', { requestId: 'r1' });
  say(handler, 'Network.responseReceived', { requestId: 'r1' });
  say(handler, 'Network.requestFinished', { requestId: 'r1' });
  say(handler, 'Network.requestWillBeSent', { requestId: 'r2' });
  say(handler, 'Network.requestFailed', { requestId: 'r2' });
  handler._onFrameDetached('f1');
  assert.deepEqual(names(events), ['Page.frameDetached'], 'no end without a start on the wire');
});

test('a request whose start was told before the load and whose end is held is told, a request held whole is not', () => {
  const { handler, events } = pageHandler();
  say(handler, 'Page.eventFired', { frameId: 'f1', name: 'load' });
  say(handler, 'Network.requestFinished', { requestId: 'told' });
  say(handler, 'Network.requestWillBeSent', { requestId: 'held' });
  say(handler, 'Network.requestFinished', { requestId: 'held' });
  handler._onFrameDetached('f1');
  assert.deepEqual(names(events), ['Network.requestFinished told', 'Page.frameDetached']);
});

test('a frame that detaches with its load held and no end in the queue says only that it is detached', () => {
  const { handler, events } = pageHandler();
  say(handler, 'Page.eventFired', { frameId: 'f1', name: 'load' });
  say(handler, 'Network.requestWillBeSent', { requestId: 'r1' });
  handler._onFrameDetached('f1');
  assert.deepEqual(names(events), ['Page.frameDetached']);
});

test('a frame the client never heard of tells nothing when it detaches', () => {
  const { handler, events } = pageHandler({ announce: false });
  say(handler, 'Page.eventFired', { frameId: 'f1', name: 'load' });
  say(handler, 'Network.requestFinished', { requestId: 'r1' });
  handler._onFrameDetached('f1');
  assert.deepEqual(events, []);
});
