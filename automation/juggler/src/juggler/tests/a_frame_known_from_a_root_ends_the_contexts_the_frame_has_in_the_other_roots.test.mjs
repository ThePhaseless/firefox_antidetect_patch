// The contexts a frame has in the process it left end BEFORE the process that holds it now says the frame is there
// (the contexts of a frame end before its commit, firefox-69).
//
// A cross-site iframe starts in the process of its embedder (an about:blank with its contexts) and goes to a process of
// its own. The client keeps, per (frame, world), the context it was told of and drops it only when it is told it ended:
// a commit does not drop anything. If the contexts of the process the frame left end only when the new process
// announces its first context, which comes AFTER the commit, the client can evaluate in the dead context of the old
// document and fail with "Execution context was destroyed".
//
// The new process says `frameKnown` for the frame when it starts (PageAgent._reportFrame), before its contexts: that is
// where the mux ends the contexts the frame still has in the other roots, so the client has none of the old document
// when the commit reaches it. Only `frameKnown`: it is said only when a root starts, while a `frameDocumentInserted`
// from a root that is being left behind would end the contexts that are alive.
//
// Loaded the way content_mux_roots_end.test.mjs loads the mux, with the real SimpleChannel. No browser.
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

const { SimpleChannel } = load('SimpleChannel.js', { dump: () => {} }, ['SimpleChannel']);
const { ContentMux } = load('ContentMux.js', {}, ['ContentMux']);

const MAIN = 1;

const plain = x => JSON.parse(JSON.stringify(x));
const settle = async (n = 6) => {
  for (let i = 0; i < n; i++)
    await new Promise(resolve => setTimeout(resolve, 0));
};

// The content process of one root: a SimpleChannel joined to the parent's actor by a loopback. `page` and `frames`
// are the two namespaces a root speaks in.
function startContent(label) {
  const channel = new SimpleChannel('content-' + label, 'process-x');
  const content = {label, channel};
  const actor = {
    browsingContext: null,
    actorName: 'JugglerFrame',
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
  const page = channel.connect('page');
  const frames = channel.connect('frames');
  content.context = (executionContextId, frameId, name = '') =>
    page.send('runtimeExecutionContextCreated', {executionContextId, auxData: {frameId, name}});
  content.frameKnown = frameId => frames.send('frameKnown', {frameId, url: 'about:blank', name: ''});
  content.frameDocumentInserted = frameId => frames.send('frameDocumentInserted', {frameId, url: 'about:blank', name: '', navigationId: undefined});
  return content;
}

// What the PageHandler registers, in the two namespaces, recorded in the order the mux hands it over.
function world() {
  const bcs = new Map();
  const pageTarget = {
    linkedBrowser: () => ({browsingContext: {id: MAIN}}),
    frameIdToBrowsingContext: id => bcs.get(id),
  };
  const mux = new ContentMux({pageTarget, name: 'page', uid: 'parent', createChannel: (name, uid) => new SimpleChannel(name, uid)});
  const events = [];
  const record = name => (payload, meta) => { events.push({name, payload: plain(payload), rootId: meta.rootId}); };
  mux.register('page', {
    runtimeExecutionContextCreated: record('runtimeExecutionContextCreated'),
    runtimeExecutionContextDestroyed: record('runtimeExecutionContextDestroyed'),
    runtimeExecutionContextsCleared: record('runtimeExecutionContextsCleared'),
    pageWorkerCreated: record('pageWorkerCreated'),
    pageWorkerDestroyed: record('pageWorkerDestroyed'),
  });
  mux.register('frames', {
    frameKnown: record('frameKnown'),
    frameDocumentInserted: record('frameDocumentInserted'),
  });
  return {
    mux, events,
    async root(rootId, {isMain = false} = {}) {
      const content = startContent('root' + rootId);
      mux.bindRoot(rootId, content.actor, {isMain});
      await settle(3);
      return content;
    },
  };
}

const brief = events => events.map(e => [e.name, e.payload.executionContextId ?? e.payload.frameId, e.rootId]);

test('a frameKnown from a root ends the contexts the frame has in another root before it is forwarded', async () => {
  const w = world();
  const top = await w.root(MAIN, {isMain: true});
  const other = await w.root(2);
  await top.context(1, 'ftop');
  await top.context(5, 'fb');            // the about:blank of the iframe, in the process of its embedder
  await top.context(6, 'fb', 'world');
  w.events.length = 0;

  await other.frameKnown('fb');          // the process of its own starts, and says the frame is here
  assert.deepEqual(brief(w.events), [
    ['runtimeExecutionContextDestroyed', 5, MAIN],
    ['runtimeExecutionContextDestroyed', 6, MAIN],
    ['frameKnown', 'fb', 2],
  ], 'the old contexts end first, then the frame is said known: the commit that follows finds none of them');
  assert.equal(w.mux.contextRoot(1), MAIN, 'the other frames of the top keep theirs');
  assert.throws(() => w.mux.contextRoot(5), /Failed to find execution context/);
  assert.throws(() => w.mux.contextRoot(6), /Failed to find execution context/);

  // The contexts of the new process come after, and end nothing: there is nothing left of the old document.
  w.events.length = 0;
  await other.context(10, 'fb');
  await other.context(11, 'fb', 'world');
  assert.deepEqual(brief(w.events), [
    ['runtimeExecutionContextCreated', 10, 2],
    ['runtimeExecutionContextCreated', 11, 2],
  ]);
  assert.equal(w.mux.contextRoot(10), 2);
});

test('a frameDocumentInserted from another root ends no context', async () => {
  const w = world();
  const top = await w.root(MAIN, {isMain: true});
  const other = await w.root(2);
  await top.context(5, 'fb');
  w.events.length = 0;

  // A root that is being left behind can say a document inserted late: the contexts it ends would be the live ones.
  await other.frameDocumentInserted('fb');
  assert.deepEqual(brief(w.events), [['frameDocumentInserted', 'fb', 2]]);
  assert.equal(w.mux.contextRoot(5), MAIN);
});

test('a frameKnown from the root that already holds the contexts of the frame ends none', async () => {
  const w = world();
  const top = await w.root(MAIN, {isMain: true});
  await w.root(2);
  await top.context(5, 'fb');
  await top.context(6, 'fb', 'world');
  w.events.length = 0;

  await top.frameKnown('fb');
  assert.deepEqual(brief(w.events), [['frameKnown', 'fb', MAIN]]);
  assert.equal(w.mux.contextRoot(5), MAIN);
  assert.equal(w.mux.contextRoot(6), MAIN);
});

test('a frameKnown for a frame ends the contexts of that frame only', async () => {
  const w = world();
  const top = await w.root(MAIN, {isMain: true});
  const other = await w.root(2);
  await top.context(5, 'fb');
  await top.context(7, 'fc');
  w.events.length = 0;

  await other.frameKnown('fd');          // a frame the top has no context for
  assert.deepEqual(brief(w.events), [['frameKnown', 'fd', 2]]);
  assert.equal(w.mux.contextRoot(5), MAIN);
  assert.equal(w.mux.contextRoot(7), MAIN);

  w.events.length = 0;
  await other.frameKnown('fb');
  assert.deepEqual(brief(w.events), [
    ['runtimeExecutionContextDestroyed', 5, MAIN],
    ['frameKnown', 'fb', 2],
  ]);
  assert.equal(w.mux.contextRoot(7), MAIN, 'the contexts of another frame stay');
});

test('a frameKnown that comes while no handler takes the contexts is forwarded all the same', async () => {
  // The page handler registers the two namespaces one after the other: a frameKnown that comes between has nobody to
  // tell that the contexts ended, and must still reach the one that is there.
  const w = world();
  const top = await w.root(MAIN, {isMain: true});
  const other = await w.root(2);
  await top.context(5, 'fb');
  w.mux._unregister('page');
  w.events.length = 0;

  await other.frameKnown('fb');
  assert.deepEqual(brief(w.events), [['frameKnown', 'fb', 2]]);
});
