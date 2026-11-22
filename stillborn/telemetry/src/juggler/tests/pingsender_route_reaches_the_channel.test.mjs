// The proxy-auth callbacks of the pingsender background task reach the channel
// of the ping, and only there (B266).
//
// The background task (BackgroundTask_pingsender.sys.mjs) takes the session's
// road from its environment, and a ping sent to a host the session's proxy
// governs must carry the callbacks that answer that proxy's 407: a background
// request gets no prompt, so without them the ping would fail at the proxy.
// This test runs the REAL text of the task, of sendStandalonePing and of both
// own files together on stubs of the platform, so it holds however the hooks
// are written: the callbacks must be on the channel when the request goes out.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');

const TELEMETRY_SEND = 'toolkit/components/telemetry/app/TelemetrySend.sys.mjs';
const OWN_FILE = 'toolkit/components/telemetry/app/StealthPingsender.sys.mjs';
const ROUTE_FILE = 'toolkit/components/telemetry/pings/StealthPingsenderRoute.sys.mjs';
const TASK_FILE = 'toolkit/components/telemetry/pings/BackgroundTask_pingsender.sys.mjs';

const URL_OF = {
  'resource://gre/modules/TelemetrySend.sys.mjs': 'telemetrySend',
  'resource://gre/modules/StealthPingsender.sys.mjs': 'pingsender',
  'resource://gre/modules/AppConstants.sys.mjs': 'appConstants',
  'resource://gre/modules/backgroundtasks/StealthPingsenderRoute.sys.mjs': 'route',
};

// The text of a module turned into a function body: imports become lookups in
// `modules`, `export` is dropped, the exported names are returned.
function moduleFunction(text, ctx) {
  const names = [...text.matchAll(/^export (?:async )?(?:function|const|let|var) (\w+)/gm)].map(m => m[1]);
  const body = text
    .replace(/^import \* as (\w+) from "([^"]+)";.*$/gm, 'const $1 = __module("$2");')
    .replace(/^import \{([^}]*)\} from "([^"]+)";.*$/gm, 'const {$1} = __module("$2");')
    .replace(/^export \{[^}]*\} from "[^"]+";.*$/gm, '')
    .replace(/^export /gm, '');
  return vm.runInContext(`(function (__module) {\n${body}\nreturn { ${names.join(', ')} };\n})`, ctx);
}

// sendStandalonePing, as written in TelemetrySend.sys.mjs, on its own.
function sendStandalonePingText({ dropHooks = false } = {}) {
  const text = read(TELEMETRY_SEND);
  const start = text.indexOf('export function sendStandalonePing(');
  assert.ok(start > 0, 'sendStandalonePing is gone from TelemetrySend.sys.mjs');
  const end = text.indexOf('\n}\n', start);
  let fn = text.slice(start, end + 3);
  if (dropHooks) {
    fn = fn.split('\n').filter(l => !/StealthPingsender\.attach/.test(l)).join('\n');
  }
  return fn;
}

// A browser's worth of stubs, and the modules loaded on them. `env` is what
// the task finds in its environment.
function world({ env, dropHooks } = {}) {
  const requests = [];
  const filters = [];
  class ServiceRequest {
    constructor() { this.headers = {}; requests.push(this); }
    open(method, url) { this.url = url; this.channel = {}; }
    overrideMimeType() {}
    setRequestHeader(k, v) { this.headers[k] = v; }
    sendInputStream() {
      // XMLHttpRequest takes the channel's callbacks when it sends.
      this.callbacksAtSend = this.channel.notificationCallbacks;
      queueMicrotask(() => { this.status = 200; this.onload({}); });
    }
  }
  const removed = [];
  const sessionRoute = {
    newProxyInfoFor: record => ({ info: record }),
    proxyAuthCallbacks: record => ({ answers407For: record }),
    proxyForHost: (record, host) =>
      !record || record.bypass.some(h => h === host) ? null : record,
  };
  const globals = {
    ServiceRequest,
    STANDALONE_PING_TIMEOUT: 30000,
    gzipCompressString: s => s,
    arrayToString: a => String(a),
    TextEncoder,
    URL,
    console: { log() {} },
    Ci: { nsIFile: 'nsIFile', nsIStringInputStream: 'nsIStringInputStream', nsIProtocolProxyService: 'nsIProtocolProxyService', nsIProtocolProxyChannelFilter: 'filter' },
    Cc: {
      '@mozilla.org/file/local;1': { createInstance: () => ({ initWithPath() {} }) },
      '@mozilla.org/network/protocol-proxy-service;1': {
        getService: () => ({ registerChannelFilter: (f, p) => filters.push([f, p]) }),
      },
      '@mozilla.org/io/string-input-stream;1': { createInstance: () => ({ setByteStringData() {} }) },
    },
    ChromeUtils: {
      importESModule: url => {
        assert.match(url, /juggler\/SessionRoute\.js$/);
        return sessionRoute;
      },
      generateQI: () => () => null,
    },
    Services: {
      env: { get: () => env ?? '', set() {} },
      prefs: { readUserPrefsFromFile() {} },
    },
    IOUtils: { readUTF8: async () => '{}', remove: async p => { removed.push(p); } },
  };
  const ctx = vm.createContext(globals);

  const modules = {};
  const resolve = url => {
    const key = URL_OF[url];
    assert.ok(key && modules[key], `a module the test does not know: ${url}`);
    return modules[key];
  };
  modules.appConstants = { AppConstants: { MOZ_APP_NAME: 'firefox', platform: 'win' } };
  modules.pingsender = moduleFunction(read(OWN_FILE), ctx)(resolve);
  // Mozilla's function, with our module where TelemetrySend imports it.
  globals.StealthPingsender = modules.pingsender;
  const standalone = vm.runInContext(
    `(function () {\n${sendStandalonePingText({ dropHooks }).replace(/^export /, '')}\nreturn sendStandalonePing;\n})`, ctx)();
  // The module that the task imports sendStandalonePing from (and, before the
  // route moved into our file, PINGSENDER_ROUTE_ENV).
  modules.telemetrySend = { sendStandalonePing: standalone, PINGSENDER_ROUTE_ENV: modules.pingsender.PINGSENDER_ROUTE_ENV };
  modules.route = moduleFunction(read(ROUTE_FILE), ctx)(resolve);
  const task = moduleFunction(read(TASK_FILE), ctx)(resolve);
  return {
    requests, filters, removed, standalone,
    runTask: endpoint => task.runBackgroundTask({ length: 2, getArgument: i => (i === 0 ? endpoint : '/pings/p1') }),
  };
}

const PROXY = { type: 'http', host: 'gw', port: 3128, bypass: ['localhost'] };
const ENV_WITH_PROXY = JSON.stringify({ proxy: PROXY, prefs: 'P/prefs.js' });
const ENV_NO_PROXY = JSON.stringify({ proxy: null, prefs: 'P/prefs.js' });

test('a ping to a host the proxy governs carries the answer to its 407', async () => {
  const w = world({ env: ENV_WITH_PROXY });
  await w.runTask('https://incoming.telemetry.mozilla.org/submit/x');
  assert.equal(w.requests.length, 1);
  // JSON round trip: the task's objects come from another realm.
  assert.deepEqual(JSON.parse(JSON.stringify(w.requests[0].callbacksAtSend)), { answers407For: PROXY });
  assert.equal(w.requests[0].headers['User-Agent'], 'pingsender/2.0');
  assert.deepEqual(w.removed, ['/pings/p1'], 'the ping file goes once it is sent');
});

test('a ping to a host in the proxy\'s bypass list carries no callbacks', async () => {
  const w = world({ env: ENV_WITH_PROXY });
  await w.runTask('http://localhost:8123/submit/x');
  assert.equal(w.requests.length, 1);
  assert.equal(w.requests[0].callbacksAtSend, undefined);
  assert.equal('notificationCallbacks' in w.requests[0].channel, false);
});

test('a session decided as no proxy: no callbacks', async () => {
  const w = world({ env: ENV_NO_PROXY });
  await w.runTask('https://incoming.telemetry.mozilla.org/submit/x');
  assert.equal(w.requests.length, 1);
  assert.equal('notificationCallbacks' in w.requests[0].channel, false);
});

test('without the road in the environment nothing is sent (it fails closed)', async () => {
  const w = world({ env: '' });
  await assert.rejects(
    w.runTask('https://incoming.telemetry.mozilla.org/submit/x'),
    /not sending/);
  assert.equal(w.requests.length, 0, 'no request');
  assert.equal(w.filters.length, 0, 'no proxy filter registered either');
  assert.deepEqual(w.removed, [], 'the ping stays on disk');
});

test('the road is registered as a channel filter at priority 0', async () => {
  const w = world({ env: ENV_WITH_PROXY });
  await w.runTask('https://incoming.telemetry.mozilla.org/submit/x');
  assert.equal(w.filters.length, 1);
  assert.equal(w.filters[0][1], 0);
});

test('a ping sent by a process that took no road (the browser itself) carries no callbacks', async () => {
  const w = world({ env: ENV_WITH_PROXY });
  const p = w.standalone('https://incoming.telemetry.mozilla.org/submit/x', '{}', {});
  await p;
  assert.equal(w.requests.length, 1);
  assert.equal('notificationCallbacks' in w.requests[0].channel, false);
});

// Negative control: the same run with the hook lines of sendStandalonePing
// cut out must lose the callbacks, so the first test above fails without them.
test('negative control: without the hook lines the callbacks do not reach the channel', async () => {
  const w = world({ env: ENV_WITH_PROXY, dropHooks: true });
  await w.runTask('https://incoming.telemetry.mozilla.org/submit/x');
  assert.equal(w.requests.length, 1);
  assert.equal('notificationCallbacks' in w.requests[0].channel, false);
});
