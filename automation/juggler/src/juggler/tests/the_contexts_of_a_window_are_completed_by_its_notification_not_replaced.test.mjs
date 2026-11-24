// The contexts a tree makes for a window before the window's notification are completed by it, not replaced
// (the contexts of a frame end before its commit, firefox-69).
//
// A content process that starts with a page builds its FrameTree while the first window of the root is being born.
// The constructor makes a set of contexts for that window (the main world, then the named worlds the shared state
// declares, with their bindings); the notification `content-document-global-created` comes after, ONCE for that inner
// window, and used to destroy that set and make a second one, the one that also ran the init scripts. The first set
// had already been said to the parent (PageAgent reports the contexts at its start, before anything leaves the
// process), so the client was told of contexts that were dead before anyone could use them, and an `evaluate` woken by
// the first announcement failed with "Execution context was destroyed".
//
// The notification completes what is there: no context is destroyed, a world that has none gets it (with its
// bindings), and the init scripts of every world run once. It does so only when the contexts are of this very inner
// window and this very document and no script has run on them; in every other case it is what it was.
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

const { Helper } = load('Helper.js', {
  Cc: { '@mozilla.org/uuid-generator;1': { getService: () => ({}) } },
  Ci: {},
  ChromeUtils: { importESModule: () => ({}) },
}, ['Helper']);

const { FrameTree, Frame } = load('content/FrameTree.js', {
  Components: { interfaces: {}, results: {}, utils: {} },
  ChromeUtils: { importESModule: () => ({ Helper }) },
  dump: () => {},
}, ['FrameTree', 'Frame']);

// One frame of a tree, with what a window and a runtime do reduced to a log. `log` has, in order:
// ['created', world], ['destroyed', world], ['binding', world, name], ['script', world, source].
function setup({ href = 'about:blank', innerWindowId = 100 } = {}) {
  const log = [];
  const emitted = [];
  const runtime = {
    createExecutionContext(domWindow, global, auxData) {
      const world = auxData.name;
      log.push(['created', world]);
      return {
        world,
        addBinding: name => log.push(['binding', world, name]),
        evaluateScriptSafely: script => log.push(['script', world, script]),
      };
    },
    destroyExecutionContext: context => log.push(['destroyed', context.world]),
  };
  const writes = [];
  const docShell = new Proxy({}, { set(target, key, value) { writes.push(key); return true; } });
  const window = {
    docShell,
    windowGlobalChild: { innerWindowId },
    document: { name: 'the first document' },
    location: { href },
  };
  const tree = Object.create(FrameTree.prototype);
  tree._isolatedWorlds = new Map();
  tree._docShellSettings = { bypassCSP: true };
  tree._webSocketEventService = { addListener() {}, removeListener() {}, hasListenerFor: () => false };
  tree.emit = (...args) => emitted.push(args);
  tree._announceIfLocal = () => false;
  const frame = Object.create(Frame.prototype);
  frame._frameTree = tree;
  frame._runtime = runtime;
  frame._frameId = 'the-frame';
  frame._url = '';
  frame._worldNameToContext = new Map();
  frame._webSocketListenerInnerWindowId = 0;
  frame._createGlobal = kind => ({ kind });
  frame.domWindow = () => window;
  tree.frames = () => [frame];
  tree.frameForDocShell = () => frame;
  return { tree, frame, window, log, emitted, writes };
}

// What the shared state declares at the start of a root: a script for the main world, a world of the caller with a
// script of its own, and a binding in each.
function declare(tree) {
  tree.setInitScripts([
    { script: 'MAIN-SCRIPT' },
    { worldName: 'caller', worldKind: 'caller', script: 'CALLER-SCRIPT' },
  ]);
  tree.addBinding('', 'mainBinding', 'b1');
  tree.addBinding('caller', 'callerBinding', 'b2');
}

const plain = x => JSON.parse(JSON.stringify(x));
const count = (log, kind) => log.filter(entry => entry[0] === kind);

test('the notification for the window of the contexts already made completes them: nothing is destroyed, each script runs once', () => {
  const { tree, frame, window, log } = setup();
  frame._onGlobalObjectCleared();          // the constructor of the tree: the main world, nothing declared yet
  declare(tree);                           // the shared state: the worlds with their bindings, scripts only kept
  assert.deepEqual(plain(count(log, 'script')), [], 'no script runs before the notification');
  log.length = 0;

  tree._onDOMWindowCreated(window);        // content-document-global-created for the SAME window

  assert.deepEqual(plain(count(log, 'destroyed')), [], 'a context that was announced is not destroyed');
  assert.deepEqual(plain(count(log, 'created')), [], 'and none is made twice');
  assert.deepEqual(plain(count(log, 'script').sort()), [['script', '', 'MAIN-SCRIPT'], ['script', 'caller', 'CALLER-SCRIPT']]);
  assert.equal(count(log, 'binding').length, 0, 'the contexts have their bindings already: none again');
});

test('before the notification the tree has each context once, the bindings in, and no script', () => {
  const { tree, frame, log } = setup();
  frame._onGlobalObjectCleared();
  declare(tree);
  assert.deepEqual(plain(log), [
    ['created', ''],
    ['created', 'caller'],
    ['binding', '', 'mainBinding'],
    ['binding', 'caller', 'callerBinding'],
  ]);
});

test('a world declared by the shared state with no context yet gets it, with its bindings before its scripts', () => {
  const { tree, frame, window, log } = setup();
  frame._onGlobalObjectCleared();
  // a world the frame has no context for (declared while the frame had no window, say): the world only is known
  tree._isolatedWorlds.set('late', { _kind: 'isolated', _scriptsToEvaluateOnNewDocument: ['LATE-SCRIPT'], _bindings: new Map([['lateBinding', 'b3']]) });
  log.length = 0;

  tree._onDOMWindowCreated(window);

  assert.deepEqual(plain(log), [
    ['created', 'late'],
    ['binding', 'late', 'lateBinding'],
    ['script', 'late', 'LATE-SCRIPT'],
  ]);
});

test('scripts that already ran on the contexts: the notification is what it was, a new set', () => {
  const { tree, frame, window, log } = setup();
  declare(tree);
  frame._onGlobalObjectCleared();          // contexts made WITH the scripts: they ran
  assert.equal(count(log, 'script').length, 2);
  log.length = 0;

  tree._onDOMWindowCreated(window);

  assert.deepEqual(plain(count(log, 'destroyed').sort()), [['destroyed', ''], ['destroyed', 'caller']]);
  assert.equal(count(log, 'created').length, 2);
  assert.equal(count(log, 'script').length, 2, 'the new contexts run the scripts, once');
});

test('the tree of a constructor with no notification: one set of contexts, no script', () => {
  const { tree, frame, log } = setup();
  frame._onGlobalObjectCleared();
  declare(tree);
  assert.equal(count(log, 'created').length, 2);
  assert.equal(count(log, 'destroyed').length, 0);
  assert.equal(count(log, 'script').length, 0);
});

test('a new inner window: the contexts are destroyed and made again, the scripts run once', () => {
  const { tree, frame, window, log } = setup();
  frame._onGlobalObjectCleared();
  declare(tree);
  log.length = 0;
  window.windowGlobalChild = { innerWindowId: 101 };

  tree._onDOMWindowCreated(window);

  assert.deepEqual(plain(count(log, 'destroyed').sort()), [['destroyed', ''], ['destroyed', 'caller']]);
  assert.equal(count(log, 'created').length, 2);
  assert.deepEqual(plain(count(log, 'script').sort()), [['script', '', 'MAIN-SCRIPT'], ['script', 'caller', 'CALLER-SCRIPT']]);
});

test('the same inner window with another document: the contexts are destroyed and made again, the scripts run once', () => {
  const { tree, frame, window, log } = setup();
  frame._onGlobalObjectCleared();
  declare(tree);
  log.length = 0;
  window.document = { name: 'another document' };

  tree._onDOMWindowCreated(window);

  assert.equal(count(log, 'destroyed').length, 2);
  assert.equal(count(log, 'created').length, 2);
  assert.equal(count(log, 'script').length, 2);
});

test('a window the frame has no contexts for: made as always', () => {
  const { tree, window, log } = setup();
  const frames = tree.frames;
  tree.frames = () => [];                  // the worlds are declared while the frame has no window: kept, no context
  declare(tree);
  tree.frames = frames;
  tree._onDOMWindowCreated(window);
  assert.equal(count(log, 'destroyed').length, 0);
  assert.deepEqual(plain(count(log, 'created').sort()), [['created', ''], ['created', 'caller']]);
  assert.equal(count(log, 'script').length, 2);
});

test('the docShell settings are written once per notification, and the notification does not announce twice', () => {
  const { tree, frame, window, writes } = setup();
  frame._onGlobalObjectCleared();
  declare(tree);
  tree._onDOMWindowCreated(window);
  assert.deepEqual(plain(writes), ['bypassCSPEnabled']);
});

test('the about:blank a tree finds before its location is set is still committed by the notification', () => {
  const { tree, frame, window, emitted } = setup({ href: '' });
  frame._onGlobalObjectCleared();          // the location is not there yet: nothing to commit
  declare(tree);
  assert.deepEqual(plain(emitted), []);
  window.location.href = 'about:blank';

  tree._onDOMWindowCreated(window);

  assert.equal(emitted.length, 1);
  assert.equal(emitted[0][0], FrameTree.Events.NavigationCommitted);
  assert.equal(frame._url, 'about:blank');
});
