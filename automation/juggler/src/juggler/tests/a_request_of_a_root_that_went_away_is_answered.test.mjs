// A request for an execution context whose root went away for good is answered, not left to wait.
//
// A request routed by execution context (`evaluate`, `callFunction`, ...) goes to the content root that holds the
// context. If that root's actor is removed (`ContentMux.unbindRoot`) and no replacement is bound, the request stayed in
// the channel's pending requests for ever: the channel keeps it so that a NEW actor can have it again, and nothing
// refused it. `PageHandler.Runtime.evaluate` sends it plainly (no `_sendToCurrentDocument`), so the client waited for the
// whole of its own timeout ("Runtime.evaluate: no response in 30s").
//
// A context named by such a request belongs to a document that is gone, and the contexts of a new document are announced
// only after a new root is bound (their ids are unique to the session: content/Runtime.js `generateId`), so nobody can
// ever answer it with anything but "Failed to find execution context". It is refused with that very text, which the
// client reads as "context gone". What stays as it was:
//   - a replacement bound BEFORE the old actor is removed: `unbindRoot` does nothing, the request goes to the new actor
//     at its READY and is answered by it;
//   - the document that goes into the back-forward cache: its content end detaches, nothing is unbound, and the request
//     is kept for the READY that attaches it again;
//   - a request that is not routed by context (by frame, to the main root): it waits for the root as before.
//
// Loaded the way content_mux.test.mjs loads the mux, with the real SimpleChannel. No browser.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { settle, until } from './_turns.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function load(file, scope, names) {
  const source = fs.readFileSync(path.join(ROOT, file), 'utf8').replace(/^export /gm, '');
  vm.createContext(scope);
  vm.runInContext(source + `\n;globalThis.__names = { ${names.join(', ')} };`, scope);
  return scope.__names;
}

const { SimpleChannel } = load('SimpleChannel.js', { dump: () => {} }, ['SimpleChannel']);
const { ContentMux } = load('ContentMux.js', {}, ['ContentMux']);

const MAIN = 1;
const CONTEXT = 'id-7';
const NOT_FOUND = /Failed to find execution context with id = id-7/;

const plain = x => JSON.parse(JSON.stringify(x));
const never = () => new Promise(() => {});

// The content process of one root: a SimpleChannel whose handlers record what they were asked and answer
// `{answeredBy}` unless `behavior[method]` says otherwise.
function startContent(label) {
  const channel = new SimpleChannel('content-' + label, 'process-x');
  const content = {label, channel, calls: [], behavior: {}};
  const handler = new Proxy({}, {
    get: (_, method) => typeof method !== 'string' ? undefined : (...args) => {
      content.calls.push({method, args: plain(args)});
      const behave = content.behavior[method];
      return behave ? behave(...args) : {answeredBy: label};
    },
  });
  channel.register('page', handler);
  channel.register('', handler);
  content.of = method => content.calls.filter(call => call.method === method);
  const actor = {
    browsingContext: null,
    actorName: 'JugglerFrame-' + label,
    receiveMessage() {},
    sendAsyncMessage(name, obj) {
      queueMicrotask(() => channel._onMessage(structuredClone(obj)));
    },
  };
  channel.setTransport({
    sendMessage: obj => actor.receiveMessage({data: structuredClone(obj)}),
    dispose() {},
  });
  content.actor = actor;
  content.emit = (name, payload) => channel.connect('page').send(name, payload);
  // What the real content says when a context is not its own (content/Runtime.js findExecutionContext).
  content.behavior.evaluate = ({executionContextId}) => {
    throw new Error('Failed to find execution context with id = ' + executionContextId);
  };
  return content;
}

function world() {
  const top = {id: MAIN, parent: null, currentWindowGlobal: {isProcessRoot: true}};
  const pageTarget = {
    linkedBrowser: () => ({browsingContext: {id: MAIN}}),
    frameIdToBrowsingContext: id => id === 'ft' ? top : undefined,
  };
  const mux = new ContentMux({pageTarget, name: 'page', uid: 'parent', createChannel: (name, uid) => new SimpleChannel(name, uid)});
  mux.register('page', {
    runtimeExecutionContextCreated() {}, runtimeExecutionContextDestroyed() {}, runtimeExecutionContextsCleared() {},
    pageWorkerCreated() {}, pageWorkerDestroyed() {},
  });
  return {
    mux,
    page: mux.connect('page'),
    async bind(content) {
      mux.bindRoot(MAIN, content.actor, {isMain: true});
      await settle(30);
    },
  };
}

// What became of a promise, read from a state the test builds, not from a timer.
function watch(promise) {
  const state = {outcome: 'pending', value: undefined};
  promise.then(
      value => { state.outcome = 'resolved'; state.value = value; },
      error => { state.outcome = 'rejected'; state.value = error; });
  return state;
}

// A top root bound, a context announced in it, and an `evaluate` for the context that its content has received and never answers.
async function pendingEvaluate() {
  const w = world();
  const content = startContent('old');
  content.behavior.evaluate = never;
  await w.bind(content);
  await content.emit('runtimeExecutionContextCreated', {executionContextId: CONTEXT, auxData: {frameId: 'ft'}});
  assert.equal(w.mux.contextRoot(CONTEXT), MAIN);
  const request = w.page.send('evaluate', {executionContextId: CONTEXT, expression: '1'});
  const state = watch(request);
  await until('the content has received the request', () => content.of('evaluate').length === 1);
  await settle(30);
  assert.equal(state.outcome, 'pending');
  return {...w, content, state};
}

test('a context request whose root went away with no replacement is refused: the context is gone', async () => {
  const w = await pendingEvaluate();
  assert.ok(w.mux.unbindRoot(MAIN, w.content.actor), 'the bound actor is unbound');
  await settle(30);
  assert.equal(w.state.outcome, 'rejected', 'the request is answered once its root is gone');
  assert.match(w.state.value.message, NOT_FOUND);
});

test('a replacement bound before the old actor is removed answers the request, as before', async () => {
  const w = await pendingEvaluate();
  const next = startContent('new');
  await w.bind(next);
  assert.equal(w.mux.unbindRoot(MAIN, w.content.actor), null, 'the old actor is no longer the bound one');
  await settle(30);
  assert.equal(next.of('evaluate').length, 1, 'the request was sent again to the new actor, once');
  assert.equal(w.state.outcome, 'rejected');
  assert.match(w.state.value.message, NOT_FOUND, 'and it answered "not found", being of another document');
});

test('a replacement bound after the old actor is removed ends in the same answer', async () => {
  const w = await pendingEvaluate();
  assert.ok(w.mux.unbindRoot(MAIN, w.content.actor));
  await w.bind(startContent('new'));
  await settle(30);
  assert.equal(w.state.outcome, 'rejected');
  assert.match(w.state.value.message, NOT_FOUND);
});

test('a document that goes into the back-forward cache keeps the request for the READY that attaches it again', async () => {
  const w = world();
  const content = startContent('doc');
  let asked = 0;
  content.behavior.evaluate = () => (++asked === 1 ? never() : {answeredBy: 'doc again'});
  await w.bind(content);
  await content.emit('runtimeExecutionContextCreated', {executionContextId: CONTEXT, auxData: {frameId: 'ft'}});
  const state = watch(w.page.send('evaluate', {executionContextId: CONTEXT, expression: '1'}));
  await until('the content has received the request', () => content.of('evaluate').length === 1);

  content.channel.detachFromPeer();     // pagehide, persisted: nothing is unbound in the parent
  await settle(30);
  assert.equal(state.outcome, 'pending');

  await w.bind(content);                // pageshow: the document is current again, its actor is bound again
  await until('the request is answered', () => state.outcome !== 'pending');
  assert.equal(state.outcome, 'resolved');
  assert.deepEqual(plain(state.value), {answeredBy: 'doc again'});
});

test('a request that is not routed by context waits for its root, as before', async () => {
  const w = world();
  const content = startContent('old');
  content.behavior.describeNode = never;
  await w.bind(content);
  const state = watch(w.page.send('describeNode', {frameId: 'ft'}));
  await until('the content has received the request', () => content.of('describeNode').length === 1);

  assert.ok(w.mux.unbindRoot(MAIN, content.actor));
  await settle(30);
  assert.equal(state.outcome, 'pending', 'not refused: no context of a gone document is named');

  const next = startContent('new');
  await w.bind(next);
  await until('the request is answered', () => state.outcome !== 'pending');
  assert.equal(state.outcome, 'resolved');
  assert.deepEqual(plain(state.value), {answeredBy: 'new'});
});
