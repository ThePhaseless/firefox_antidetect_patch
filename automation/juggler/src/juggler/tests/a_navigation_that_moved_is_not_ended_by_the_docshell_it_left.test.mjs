// The registry of navigations (FrameNavigations.js), loaded the way the parent loads it: a navigation that the parent
// moved to another process is not ended by the docShell it left.
//
// The parent decides, synchronously, that a navigation leaves the docShell that started it (DocumentLoadListener::
// TriggerProcessSwitch). From then on the stand-in of the request left in that docShell counts for nothing: if the old
// page stops it (its own location.replace), the parent ignores the Cancel (its open promise is resolved) and the
// navigation commits in the other process. But the docShell it left says "aborted" all the same, and the registry
// believed it: goto raised NS_BINDING_ABORTED for a document that loaded (the wrapper's e2e, a_page_that_moves_on,
// runs 45012035299 and 44988820319). The parent tells the registry the decision (`onNavigationMoved`), with where the
// navigation was: the id of the browsing context and the process. An end told by that browsing context in that process
// after it is not the end of the navigation. Every other voice is as it was.
//
// Run: node --test juggler/tests/a_navigation_that_moved_is_not_ended_by_the_docshell_it_left.test.mjs

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

const { FrameNavigations } = load('FrameNavigations.js', {}, ['FrameNavigations']);

const MAIN = 'mainframe-1';
const URL_A = 'http://localhost/landed?i=x50-1';

// Where the navigation was when the parent moved it, and who may say something about it later.
const ORIGIN = { browsingContextId: 11, childId: 100 };
const DESTINATION = { browsingContextId: 11, childId: 200 };        // the same browsing context, in the process that takes it
const REPLACEMENT = { browsingContextId: 12, childId: 100 };        // a browsing context that replaced it, in the same process

function setup() {
  const events = [];
  const registry = new FrameNavigations((name, payload) => events.push([name, { ...payload }]));
  return { registry, events };
}

// The parent's decision.
const moved = (registry, frameId, navigationId, origin) => registry.onNavigationMoved(frameId, navigationId, origin);

const started = navigationId => ['navigationstarted', { frameId: MAIN, navigationId }];
const committed = navigationId => ['navigationcommitted', { frameId: MAIN, navigationId, url: URL_A, name: '' }];
const aborted = (navigationId, errorText = 'NS_BINDING_ABORTED') => ['navigationaborted', { frameId: MAIN, navigationId, errorText }];

// ── the four interleavings: the docShell that was left says "aborted" and the document comes ─────────────────────────────────

test('a request that ended, then the cut of the docShell it left, then the document: started and committed, once', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  registry.onDocumentInserted(MAIN, URL_A, '', 'nav-1');
  assert.deepEqual(events, [started('nav-1'), committed('nav-1')]);
});

test('a cut of the docShell it left, told while the parent carried the request, is not held: no barrier, no abort', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false, 'the request ended and no cut of the navigation waits for its barrier');
  registry.onCutConfirmed(MAIN, 'nav-1');
  registry.onDocumentInserted(MAIN, URL_A, '', 'nav-1');
  assert.deepEqual(events, [started('nav-1'), committed('nav-1')]);
});

test('the cut came first and the parent\'s decision after it: the cut that was kept is dropped when the request ends', () => {
  // PContent keeps the order: the Cancel and the message that tells it travel together. If the cut reached the registry
  // before `moved`, it was kept like any cut told while the parent carries the request; the decision makes it the
  // docShell's own, and the end of the request must not hold it behind a barrier.
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onCutConfirmed(MAIN, 'nav-1');
  registry.onDocumentInserted(MAIN, URL_A, '', 'nav-1');
  assert.deepEqual(events, [started('nav-1'), committed('nav-1')]);
});

test('a navigation that a newer one replaced and the parent moved is not ended by the cut of the docShell it left', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  registry.onDocumentRequest(MAIN, 'nav-2', 'http://localhost/other');     // replaces nav-1 without ending it
  moved(registry, MAIN, 'nav-1', ORIGIN);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  registry.onDocumentInserted(MAIN, URL_A, '', 'nav-1');
  assert.deepEqual(events, [started('nav-1'), started('nav-2'), committed('nav-1')]);
});

// ── what stays as it was ──────────────────────────────────────────────────────────────────────────────────────────────────────

test('a cut with no decision of the parent ends the navigation, once', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  assert.deepEqual(events, [started('nav-1'), aborted('nav-1')]);
});

test('a cut of the docShell that RECEIVES the document ends the navigation: the same browsing context in the other process', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', DESTINATION);
  assert.deepEqual(events, [started('nav-1'), aborted('nav-1')]);
});

test('a cut of a browsing context that replaced the one left, in the same process, ends the navigation: the id and the process are both compared', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', REPLACEMENT);
  assert.deepEqual(events, [started('nav-1'), aborted('nav-1')]);
});

test('the cut of the parent itself, after the response had begun, goes through the barrier and ends the navigation, once', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  assert.equal(registry.onDocumentRequestFailed(MAIN, 'nav-1', 'NS_BINDING_ABORTED', true), true);
  assert.deepEqual(events, [started('nav-1')], 'held until the barrier comes back');
  registry.onCutConfirmed(MAIN, 'nav-1');
  registry.onCutConfirmed(MAIN, 'nav-1');
  assert.deepEqual(events, [started('nav-1'), aborted('nav-1')]);
});

test('a cut told with no reporter is what it was: the navigation ends', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED');
  assert.deepEqual(events, [started('nav-1'), aborted('nav-1')]);
});

test('a docShell of the parent process is child id 0 on both sides: its cut is the one the parent moved the navigation from', () => {
  const { registry, events } = setup();
  const inTheParent = { browsingContextId: 11, childId: 0 };
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', inTheParent);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', inTheParent);
  registry.onDocumentInserted(MAIN, URL_A, '', 'nav-1');
  assert.deepEqual(events, [started('nav-1'), committed('nav-1')]);
});

test('a frame that is forgotten keeps no decision of the parent', () => {
  const { registry, events } = setup();
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  moved(registry, MAIN, 'nav-1', ORIGIN);
  registry.forget(MAIN);
  registry.onDocumentRequest(MAIN, 'nav-1', URL_A);
  assert.equal(registry.onDocumentRequestEnded(MAIN, 'nav-1'), false);
  registry.onNavigationAborted(MAIN, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  assert.deepEqual(events, [started('nav-1'), started('nav-1'), aborted('nav-1')]);
});

// ── the rest of the way: the content process tells who it is, the parent hears the decision ──────────────────────────────────
//
// FrameTree (reporter of every end), PageHandler (the observer of the decision, the reporter handed to the registry) and
// the hook of the engine are tested where they are: navigation_abort, navigation_refused_before_a_channel and
// page_handler_wires_the_frame_lifecycle. Here: what PageAgent sends, and the engine's side read as text (the C++ is built
// on GitHub; a name that is not the same on both sides, or a condition that left the function, is found here).

function agentSaying() {
  const scope = { Components: { interfaces: {}, results: {}, utils: {} }, dump: () => {},
    Cc: new Proxy({}, { get: () => ({ getService: () => ({ addObserver() {}, removeObserver() {} }) }) }) };
  const { Helper } = load('Helper.js', {
    Cc: { '@mozilla.org/uuid-generator;1': { getService: () => ({}) } }, Ci: {}, ChromeUtils: { importESModule: () => ({}) },
  }, ['Helper']);
  scope.ChromeUtils = { importESModule: url => url.endsWith('Helper.js') ? { Helper: class extends Helper { addObserver() { return () => {}; } } }
      : { NetUtil: {}, setTimeout } };
  const { PageAgent } = load('content/PageAgent.js', scope, ['PageAgent']);
  const said = [];
  const channel = { connect: ns => ({ emit: (method, params) => said.push([ns, method, JSON.parse(JSON.stringify(params))]), dispose() {} }), register: () => () => {} };
  const main = { id: () => 'mainframe-1', docShell: () => ({}), url: () => 'about:blank', name: () => '', pendingNavigationId: () => null,
    lastCommittedNavigationId: () => null, domWindow: () => null };
  const runtime = new Proxy({}, { get: (_, name) => name === 'executionContexts' ? () => []
    : name === 'events' ? new Proxy({}, { get: () => () => () => {} }) : function () {} });
  const tree = { runtime: () => runtime, mainFrame: () => main, frames: () => [], isPageReady: () => false, workers: () => [],
    frame: () => null, _isPageMain: () => true, enterCache() {}, leaveCache() {}, on() {}, off() {} };
  const agent = new PageAgent(channel, tree);
  said.length = 0;
  return { agent, said };
}

test('the page agent tells an end with the reporter it was given', () => {
  const { agent, said } = agentSaying();
  agent._onNavigationAborted({ id: () => MAIN }, 'nav-1', 'NS_BINDING_ABORTED', ORIGIN);
  assert.deepEqual(said, [['frames', 'frameNavigationAborted', { frameId: MAIN, navigationId: 'nav-1', errorText: 'NS_BINDING_ABORTED', reporter: ORIGIN }]]);
});

const read = file => fs.readFileSync(path.join(ROOT, '..', file), 'utf8');

test('the engine tells the decision on the topic the parent listens on, with the load identifier and the child id', () => {
  const header = read('docshell/base/StealthNavigationEvents.h');
  const handler = read('juggler/protocol/PageHandler.js');
  assert.ok(header.includes('"juggler-navigation-moved"'));
  assert.ok(handler.includes("'juggler-navigation-moved'"));
  // "<load identifier> <child id>": the two numbers the parent splits on a space.
  assert.ok(header.includes('nsPrintfCString("%" PRIu64 " %" PRIu64, aLoadIdentifier, childId)'));
  assert.ok(handler.includes("const [loadIdentifier, childId] = String(data).split(' ');"));
});

test('the conditions of the decision are in our function, and a load with no content process says child id 0', () => {
  const header = read('docshell/base/StealthNavigationEvents.h');
  const at = header.indexOf('inline void StealthNotifyNavigationMoved(');
  assert.ok(at > 0, 'the function is there');
  const body = header.slice(at);
  assert.ok(body.includes('if (!aIsDocumentLoad || aIsNewTab) {\n    return;\n  }'));
  assert.ok(body.includes('aContentParent ? uint64_t(aContentParent->ChildID()) : 0'));
  assert.ok(header.includes('#include "mozilla/dom/ContentParent.h"'));
});

test('the hook is one line in TriggerProcessSwitch, before the listeners of the old process are disconnected', () => {
  const source = read('netwerk/ipc/DocumentLoadListener.cpp');
  const hooks = source.split('\n').filter(line => line.includes('StealthNotifyNavigationMoved'));
  assert.deepEqual(hooks, ['  StealthNotifyNavigationMoved(aContext, mContentParent, mLoadIdentifier, mIsDocumentLoad, aIsNewTab);  // STEALTH-HOOK(automation/navigation)']);
  const start = source.indexOf('void DocumentLoadListener::TriggerProcessSwitch(');
  const hook = source.indexOf('StealthNotifyNavigationMoved(');
  const disconnect = source.indexOf('DisconnectListeners(NS_BINDING_ABORTED, NS_BINDING_ABORTED, !aIsNewTab);', start);
  assert.ok(start > 0 && hook > start && disconnect > hook, 'the decision is told before the old listeners go');
  // The header is not exported: the include goes by its path, and the path is the file.
  const include = '#include "../../docshell/base/StealthNavigationEvents.h"  // STEALTH-HOOK(automation/navigation)';
  assert.ok(source.split('\n').includes(include), 'the include of the header, marked');
  assert.ok(fs.existsSync(path.join(ROOT, '..', 'netwerk/ipc', '../../docshell/base/StealthNavigationEvents.h')));
});
