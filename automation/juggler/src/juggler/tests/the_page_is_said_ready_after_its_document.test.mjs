// The content process says the page is ready AFTER it has said the document that made it ready.
//
// A popup announced with `about:blank` as its address (a test of the client that waits for the popup and then reads its
// url): the page was said ready (`pageReady`, which the parent turns into `Page.ready`) before the document that made it
// ready was said (`frameDocumentInserted`, which becomes `Page.navigationCommitted`). The client announces a popup after
// `Page.ready` and one round of `Browser.getInfo`: that round only orders what the parent HAS written, so under load the
// popup was announced before the commit and its address was the one it was born with. Stock Juggler says the commit first.
//
// FrameTree._commit forced the page ready itself, before the callers said anything. Each caller says its document and then
// forces the ready: a new document (`onWindowEvent`, after `DocumentInserted`) and a document restored from the
// back-forward cache (after `DocumentRestored`). The message names the main frame of the one who says it (the parent
// holds it behind that frame's own events, PageHandler._onPageReady).
//
// A real FrameTree and a real PageAgent, loaded the way the content process loads them, with fakes for the frame, the
// docShell and the channel; what is checked is the order of the messages the channel sends to the parent.
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

const { FrameTree } = load('content/FrameTree.js', {
  Components: { interfaces: {}, results: {}, utils: {} },
  ChromeUtils: { importESModule: () => ({ Helper }) },
  dump: () => {},
}, ['FrameTree']);

const agentScope = () => {
  const scope = { Components: { interfaces: {}, results: {}, utils: {} }, dump: () => {},
    Cc: new Proxy({}, { get: () => ({ getService: () => ({ addObserver() {}, removeObserver() {} }) }) }) };
  scope.ChromeUtils = { importESModule: url => url.endsWith('Helper.js') ? { Helper: class extends Helper { addObserver() { return () => {}; } } }
      : { NetUtil: {}, setTimeout } };
  return scope;
};
const { PageAgent } = load('content/PageAgent.js', agentScope(), ['PageAgent']);

// The page as the content process holds it: a main frame, a tree that lets the agent listen to it, and a channel that
// writes what it sends to the parent. `ready`: the tree already said the page ready when the agent is made.
function page({ ready = false, url = 'about:blank' } = {}) {
  const wire = [];
  const channel = { connect: ns => ({ emit: (method, params) => wire.push([ns, method, plain(params)]), dispose() {} }), register: () => () => {} };
  const docShell = { QueryInterface() {}, currentURI: { spec: url } };
  const frame = {
    _frameId: 'mainframe-1', _children: [], _pendingNavigationId: null, _lastCommittedNavigationId: null, _url: url,
    _suppressedAbort: null, _browsingContext: { parent: null },
    id() { return this._frameId; }, url() { return this._url; }, name: () => '', parentFrame: () => null,
    pendingNavigationId() { return this._pendingNavigationId; }, lastCommittedNavigationId() { return this._lastCommittedNavigationId; },
    docShell: () => docShell, domWindow: () => ({ location: { href: url } }),
  };
  const subframe = {
    _frameId: 'subframe-2', _children: [], _pendingNavigationId: null, _lastCommittedNavigationId: null, _url: '',
    _suppressedAbort: null, _browsingContext: { parent: {} },
    id() { return this._frameId; }, url() { return this._url; }, name: () => '', parentFrame: () => frame,
    pendingNavigationId() { return this._pendingNavigationId; }, lastCommittedNavigationId() { return this._lastCommittedNavigationId; },
    docShell: () => ({ QueryInterface() {}, currentURI: { spec: 'https://b.test/' } }),
  };
  const listeners = new Map();
  const runtime = new Proxy({}, { get: (_, name) => name === 'executionContexts' ? () => []
    : name === 'events' ? new Proxy({}, { get: () => () => () => {} }) : function () {} });
  const tree = Object.create(FrameTree.prototype);
  Object.assign(tree, {
    _mainFrame: frame, _frameIdToFrame: new Map([[frame.id(), frame], [subframe.id(), subframe]]), _pageReady: ready,
    on: (name, handler) => { listeners.set(name, [...(listeners.get(name) || []), handler]); },
    off() {},
    emit: (name, ...args) => { for (const handler of [...(listeners.get(name) || [])]) handler(name, ...args); },
    runtime: () => runtime, frames: () => [frame], workers: () => [], frame: id => (id === frame.id() ? frame : null),
    frameForDocShell: docShell_ => (docShell_ === docShell ? frame : subframe),
    _installMainFrameInputListeners() {}, leaveCache() {}, enterCache() {},
  });
  const agent = new PageAgent(channel, tree);
  const initial = [...wire];
  wire.length = 0;
  const documentOf = target => ({ type: 'DOMDocElementInserted', target: { documentGlobal: { docShell: target } } });
  return { tree, agent, frame, subframe, docShell, wire, initial, documentOf };
}

const methods = wire => wire.map(([, method]) => method);

test('a new document is said before the page is said ready by it', () => {
  const { tree, frame, docShell, wire, documentOf } = page();
  frame._pendingNavigationId = 'nav-1';
  tree.onWindowEvent(documentOf(docShell));
  const order = methods(wire).filter(method => method === 'frameDocumentInserted' || method === 'pageReady');
  assert.deepEqual(order, ['frameDocumentInserted', 'pageReady']);
  assert.equal(tree.isPageReady(), true);
});

test('the ready names the main frame of the one who says it', () => {
  const { tree, frame, docShell, wire, documentOf } = page();
  frame._pendingNavigationId = 'nav-1';
  tree.onWindowEvent(documentOf(docShell));
  assert.deepEqual(wire.filter(([, method]) => method === 'pageReady').map(([, , params]) => params), [{ frameId: 'mainframe-1' }]);
});

test('a document restored from the back-forward cache is said before the page is said ready by it', () => {
  const { tree, wire } = page({ url: 'https://example.test/back' });
  tree.announceRestoredDocument();
  const order = methods(wire).filter(method => method === 'frameDocumentRestored' || method === 'pageReady');
  assert.deepEqual(order, ['frameDocumentRestored', 'pageReady']);
  assert.deepEqual(wire.filter(([, method]) => method === 'pageReady').map(([, , params]) => params), [{ frameId: 'mainframe-1' }]);
});

test('the page the agent finds ready says so with the frame it is ready for', () => {
  // The agent that is made over a ready tree says it while it is made.
  const { initial } = page({ ready: true });
  assert.deepEqual(initial.filter(([, method]) => method === 'pageReady').map(([, , params]) => params), [{ frameId: 'mainframe-1' }]);
});

test('the ready is said once, with the first document that makes the page ready', () => {
  const { tree, frame, docShell, wire, documentOf } = page();
  frame._pendingNavigationId = 'nav-1';
  tree.onWindowEvent(documentOf(docShell));
  frame._pendingNavigationId = 'nav-2';
  tree.onWindowEvent(documentOf(docShell));
  assert.deepEqual(methods(wire).filter(method => method === 'pageReady'), ['pageReady']);
  assert.deepEqual(methods(wire).filter(method => method === 'frameDocumentInserted'), ['frameDocumentInserted', 'frameDocumentInserted']);
});

test('the document of an iframe never says the page ready', () => {
  const { tree, subframe, wire, documentOf } = page();
  subframe._pendingNavigationId = 'nav-3';
  tree.onWindowEvent(documentOf(subframe.docShell()));
  assert.deepEqual(methods(wire).filter(method => method === 'pageReady'), []);
});

test('a document no navigation of this process made commits nothing and says nothing ready', () => {
  const { tree, docShell, wire, documentOf } = page();
  tree.onWindowEvent(documentOf(docShell));
  assert.deepEqual(methods(wire), ['frameDocumentInserted']);
  assert.equal(tree.isPageReady(), false);
});
