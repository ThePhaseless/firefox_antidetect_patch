// Every request the client was told of ends once, loaded the way the parent process loads NetworkObserver.js, with the real
// Helper, a real NetworkObserver and real NetworkRequests on fake channels.
//
// The client (invisible_core/juggler/lifecycle.py, like Playwright's) counts a request from `Network.requestWillBeSent` until
// its `requestFinished` or `requestFailed`; networkidle waits for the count to reach zero. A request that was announced and
// never ended keeps it up for ever. The engine said no end in four ways, all read in NetworkObserver.js:
//   S1. the channel a redirect arrives on dies before it is adopted (http-on-modify-request never comes for it): its stop
//       reaches the listener it inherited, which is the old request, and was dropped as a stop of "another channel";
//   S2. the redirect goes to a channel that is not HTTP: no one ever adopts it, and the same drop;
//   S3. the channel an internal redirect replaced is stopped while the replacement has not started, and no resume is expected
//       (only a resumed request was told failed);
//   S4. the end is not told when `responseEndTime` is not a number.
// And a request must not end twice, nor end without having been announced. The channels the request does not own still reach
// the listener the chain would have called without us.
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

const Cr = { NS_BINDING_ABORTED: 0x804b0002, NS_ERROR_FAILURE: 0x80004005, NS_ERROR_NET_RESET: 0x804b0014 };
// What `instanceof` is asked of: a channel is HTTP when it is one of these.
class HttpChannel { QueryInterface() { return this; } }
class UploadChannel {}
const Ci = {
  nsITransportSecurityInfo: { TLS_VERSION_1: 1, TLS_VERSION_1_1: 2, TLS_VERSION_1_2: 3, TLS_VERSION_1_3: 4 },
  nsIHttpChannel: HttpChannel,
  nsIUploadChannel: UploadChannel,
  nsIContentPolicy: { TYPE_OTHER: 1 },
  nsIChannelEventSink: { REDIRECT_INTERNAL: 4, REDIRECT_STS_UPGRADE: 8 },
};

class EventEmitter {
  on() {}
  off() {}
  once() {}
  emit() {}
}

const { Helper } = load('Helper.js', {
  Cc: { '@mozilla.org/uuid-generator;1': { getService: () => ({}) } },
  Ci, Cr,
  ChromeUtils: { importESModule: () => ({ EventEmitter }) },
}, ['Helper']);

const traced = [];
const { NetworkObserver, PageNetwork, NetworkRequest } = load('NetworkObserver.js', {
  Components: { classes: {}, interfaces: Ci, utils: {}, results: Cr, manager: {},
                Constructor: () => function () {} },
  ChromeUtils: {
    generateQI: () => function () {},
    importESModule: url => /Trace\.js$/.test(url)
      ? { trace: (where, what, detail) => traced.push(JSON.parse(JSON.stringify({ where, what, detail }))) }
      : { Helper, NetUtil: {}, ChannelEventSinkFactory: {}, newProxyInfoFor: () => null },
  },
  Services: {},
  dump: () => {},
}, ['NetworkObserver', 'PageNetwork', 'NetworkRequest']);

const Events = PageNetwork.Events;

// A page network that keeps what it says, and an observer on it.
function world() {
  traced.length = 0;
  const events = [];
  const pageNetwork = {
    emit: (event, payload) => events.push([event, payload]),
    combinedExtraHTTPHeaders: () => [],
    _interceptedRequests: new Map(),
    _responseStorage: { noteNavigationStart() {}, addResponseBody() {} },
    _requestInterceptionEnabled: false,
    _target: { browserContext: () => ({ requestInterceptionEnabled: false }) },
  };
  PageNetwork.forPageTarget = () => pageNetwork;
  const observer = Object.create(NetworkObserver.prototype);
  observer._channelToRequest = new Map();
  observer._expectedRedirect = new Map();
  observer._targetRegistry = { targetForBrowserId: () => ({}), browserContextForUserContextId: () => undefined };

  // The listener the page gave the first channel, and what it was called with.
  const calls = [];
  const listener = {
    onStartRequest: r => calls.push(['start', r.channelId]),
    onDataAvailable: (r, stream, offset, count) => calls.push(['data', r.channelId, stream, offset, count]),
    onStopRequest: (r, status) => calls.push(['stop', r.channelId, status]),
  };
  return { events, observer, listener, calls };
}

function channel(id, listener, extra = {}) {
  const c = new HttpChannel();
  Object.assign(c, {
    channelId: id,
    isMainDocumentChannel: false,
    URI: { spec: 'https://example.test/' + id },
    requestMethod: 'POST',
    loadInfo: {
      frameBrowsingContext: { browserId: 1, parent: null, id: 1 },
      originAttributes: { userContextId: 0 },
      externalContentPolicyType: 1,
      internalContentPolicyType: 1,
    },
    visitRequestHeaders() {},
    visitResponseHeaders() {},
    responseStatus: 200,
    responseStatusText: 'OK',
    responseEndTime: 1000,
    transferSize: 10,
    encodedBodySize: 10,
    protocolVersion: 'h2',
    notificationCallbacks: null,
    listener,
    setNewListener(l) { const previous = this.listener; this.listener = l; return previous; },
  }, extra);
  return c;
}

// A request as the engine meets it: the channel reaches http-on-modify-request, then its response starts (the start is told).
function started(observer, c) {
  observer._onRequest(c);
  const request = observer._channelToRequest.get(c);
  request.onStartRequest(c);
  return request;
}

const ends = (events, requestId) => events.filter(([event, payload]) =>
  (event === Events.RequestFinished || event === Events.RequestFailed) && payload.requestId === requestId);
const kinds = list => list.map(([event]) => event === Events.RequestFinished ? 'finished' : event === Events.RequestFailed ? 'failed' : 'other');

test('S1: the channel a redirect arrives on dies before it is adopted: the request failed, and the page listener is told', () => {
  const { events, observer, listener, calls } = world();
  const c1 = channel(1, listener);
  const c2 = channel(2, undefined);
  const request = started(observer, c1);
  observer._onRedirect(c1, c2, 0);                 // a redirect; the new channel inherits the listener, which is `request`
  c2.listener = request;
  request.onStopRequest(c2, Cr.NS_BINDING_ABORTED);   // it never reached http-on-modify-request
  const mine = ends(events, '1');
  assert.deepEqual(kinds(mine), ['failed'], 'one failed for the old id');
  assert.equal(mine[0][1].errorCode, 'NS_BINDING_ABORTED');
  assert.deepEqual(calls.filter(call => call[0] === 'stop').map(call => [call[1], call[2]]), [[2, Cr.NS_BINDING_ABORTED]],
      'the page listener is told, as the chain would');
  assert.equal(observer._expectedRedirect.size, 0, 'and the redirect that was expected is forgotten');
});

test('S2: a redirect to a channel that is not HTTP: what it says reaches the page listener, and its clean stop finishes the request', () => {
  const { events, observer, listener, calls } = world();
  const c1 = channel(1, listener);
  const request = started(observer, c1);
  const data = { channelId: 'data:' };             // not an nsIHttpChannel
  const stream = { stream: true };
  observer._onRedirect(c1, data, 0);
  request.onStartRequest(data);
  request.onDataAvailable(data, stream, 0, 3);
  request.onStopRequest(data, 0);
  assert.deepEqual(calls.map(call => call[0]), ['start', 'start', 'data', 'stop'], 'start of the page request, then the three calls for the new channel');
  assert.equal(calls[2][2], stream, 'the stream is handed over as it came');
  const mine = ends(events, '1');
  assert.deepEqual(kinds(mine), ['finished'], 'one finished for the old id');
});

test('S2b: a redirect to a channel that is not HTTP that fails: the request failed', () => {
  const { events, observer, listener } = world();
  const c1 = channel(1, listener);
  const request = started(observer, c1);
  const data = { channelId: 'data:' };
  observer._onRedirect(c1, data, 0);
  request.onStopRequest(data, Cr.NS_ERROR_NET_RESET);
  assert.deepEqual(kinds(ends(events, '1')), ['failed']);
});

test('S4: the end does not depend on responseEndTime: not a number is 0', () => {
  for (const responseEndTime of [undefined, null, NaN, 'x']) {
    const { events, observer, listener } = world();
    const c1 = channel(1, listener, { responseEndTime });
    const request = started(observer, c1);
    request.onStopRequest(c1, 0);
    const mine = ends(events, '1');
    assert.deepEqual(kinds(mine), ['finished'], String(responseEndTime));
    assert.equal(mine[0][1].responseEndTime, 0, String(responseEndTime));
  }
});

test('S3: the channel an internal redirect replaced is stopped while the replacement has not started, with no resume expected: failed', () => {
  const { events, observer, listener, calls } = world();
  const c1 = channel(1, listener);
  const c3 = channel(3, undefined);
  const request = started(observer, c1);
  assert.equal(request._expectingResumedRequest, undefined, 'nothing resumed this request');
  observer._onRedirect(c1, c3, Ci.nsIChannelEventSink.REDIRECT_INTERNAL);   // a service worker, say
  request.onStopRequest(c1, Cr.NS_BINDING_ABORTED);                          // the document went away
  assert.deepEqual(kinds(ends(events, '1')), ['failed']);
  assert.deepEqual(calls.filter(call => call[0] === 'stop').map(call => call[1]), [1], 'the page listener is told');
});

test('S3b: the replacement started: the stop of the replaced channel does not end the request', () => {
  const { events, observer, listener, calls } = world();
  const c1 = channel(1, listener);
  const c3 = channel(3, undefined);
  const request = started(observer, c1);
  observer._onRedirect(c1, c3, Ci.nsIChannelEventSink.REDIRECT_INTERNAL);
  observer._onRequest(c3);                          // the replacement reached http-on-modify-request
  request.onStopRequest(c1, Cr.NS_BINDING_ABORTED);
  assert.deepEqual(ends(events, '1'), [], 'the request goes on with the new channel');
  request.onStopRequest(c3, 0);
  assert.deepEqual(kinds(ends(events, '1')), ['finished']);
  assert.equal(calls.filter(call => call[0] === 'stop').length, 2, 'each stop reached the listener once');
});

test('guard: a request that was announced ends once, whatever stops come after its end', () => {
  const { events, observer, listener } = world();
  const c1 = channel(1, listener);
  const request = started(observer, c1);
  request.onStopRequest(c1, 0);
  request.onStopRequest(c1, 0);                     // a second stop
  request.onStopRequest(c1, Cr.NS_BINDING_ABORTED); // and a failed one
  assert.deepEqual(kinds(ends(events, '1')), ['finished']);
});

test('guard: a hop ends the request it left, and a stop that comes for it after does not end it again', () => {
  const { events, observer, listener } = world();
  const c1 = channel(1, listener);
  const c2 = channel(2, undefined);
  const request = started(observer, c1);
  observer._onRedirect(c1, c2, 0);
  c2.listener = request;
  observer._onRequest(c2);                          // adopted: the old request finished (a hop), the new one is announced
  assert.deepEqual(kinds(ends(events, '1')), ['finished']);
  request.onStopRequest(c1, 0);
  request.onStopRequest(c2, 0);                     // the old request is not its channel's listener any more
  assert.deepEqual(kinds(ends(events, '1')), ['finished'], 'still once');
  assert.deepEqual(ends(events, '2-redirect1'), [], 'and the request that went on is not ended by it');
});

test('guard: a request whose start was never told does not end', () => {
  const { events, observer, listener } = world();
  const c1 = channel(1, listener);
  observer._onRequest(c1);                          // created, never started
  const request = observer._channelToRequest.get(c1);
  request.onStopRequest(c1, Cr.NS_BINDING_ABORTED);
  assert.deepEqual(events, [], 'an end with no start is not told');
  assert.equal(observer._channelToRequest.has(c1), false, 'but the request is let go');
});

test('guard: a channel the request does not own, and does not follow, is not forwarded and does not end it', () => {
  const { events, observer, listener, calls } = world();
  const c1 = channel(1, listener);
  const request = started(observer, c1);
  const stranger = channel(9, undefined);
  request.onStopRequest(stranger, 0);
  assert.deepEqual(ends(events, '1'), []);
  assert.deepEqual(calls.filter(call => call[0] === 'stop'), []);
});

test('the trace says what the engine did: announce, redirect, stop with its channel, finish-mute', () => {
  const { observer, listener } = world();
  const c1 = channel(1, listener, { responseEndTime: undefined });
  const c2 = channel(2, undefined);
  const request = started(observer, c1);
  observer._onRedirect(c1, c2, 0);
  c2.listener = request;
  request.onStopRequest(c2, Cr.NS_BINDING_ABORTED);                    // hop
  request.onStopRequest(channel(9, undefined), 0);                     // foreign
  assert.ok(traced.every(line => line.where === 'network'), JSON.stringify(traced));
  const whats = traced.map(line => line.what);
  assert.ok(whats.includes('announce'), whats.join());
  assert.ok(whats.includes('redirect'), whats.join());
  assert.deepEqual(traced.filter(line => line.what === 'stop').map(line => line.detail.which), ['hop', 'foreign']);

  const second = world();
  const c5 = channel(5, second.listener, { responseEndTime: undefined });
  const r5 = started(second.observer, c5);
  r5.onStopRequest(c5, 0);
  const lines = traced.map(line => line.what);
  assert.ok(lines.includes('finish-mute'), lines.join());
  assert.deepEqual(traced.filter(line => line.what === 'stop').map(line => line.detail.which), ['current']);
});
