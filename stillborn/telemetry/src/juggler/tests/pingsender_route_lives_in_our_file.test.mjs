// The road of the pingsender background task (B266) lives in our own file,
// toolkit/components/telemetry/app/StealthPingsender.sys.mjs, and
// TelemetrySend.sys.mjs only calls it from marked one-line hooks.
//
// Two halves: the entry guards (the only start of the child, the only use of
// the program, both below our hooks), and a behaviour check of the moved
// functions on stubs, so the move cannot change what the child gets (the
// program and its arguments, the environment variable around the start of the
// one child, the proxy record).
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const APP = path.join(TREE, 'toolkit/components/telemetry/app');
const HOOK = 'STEALTH-HOOK(stillborn/telemetry)';

test('the only child the pingsender road starts is started by our runAsync', () => {
  const text = fs.readFileSync(path.join(APP, 'TelemetrySend.sys.mjs'), 'utf8');
  // The only start of the pingsender in TelemetrySend.sys.mjs goes through
  // StealthPingsender.runAsync: a second `.runAsync(` that Mozilla adds to a
  // new version would start a child with no road in its environment.
  const starts = text.split('\n').filter(l => /\.runAsync\(/.test(l));
  assert.deepEqual(starts.map(l => l.trim()),
    [`StealthPingsender.runAsync(process, params, observer); // ${HOOK}`]);
  // Near-miss guard: the call exists.
  assert.ok(starts.length === 1, 'the start of the pingsender moved');
});

test('the program is chosen by our invocation() before it is used', () => {
  const text = fs.readFileSync(path.join(APP, 'TelemetrySend.sys.mjs'), 'utf8');
  // The only place `exeName` is turned into a file to start comes after the
  // override that makes it `firefox --backgroundtask pingsender`: a second use
  // of it before the override (a program of Mozilla's choice) fails here.
  const override = text.indexOf('({ exeName, params } = StealthPingsender.invocation());');
  assert.ok(override > 0, 'the override of the program is gone');
  const uses = [...text.matchAll(/exe\.append\(exeName\)/g)].map(m => m.index);
  assert.equal(uses.length, 1, 'a second place starts a program');
  assert.ok(uses[0] > override, 'the program is used before our override');
});

// Load the own file on stubs: the one import is replaced by a stub object and
// `export` is dropped.
function load(platform, globals) {
  let src = fs.readFileSync(path.join(APP, 'StealthPingsender.sys.mjs'), 'utf8');
  src = src.replace(/^import \{ AppConstants \}.*$/m, 'const AppConstants = __AppConstants;');
  src = src.replace(/^export /gm, '');
  src += '\nmodule.exports = { PINGSENDER_ROUTE_ENV, attachCallbacks, invocation, runAsync };\n';
  const sandbox = {
    __AppConstants: { MOZ_APP_NAME: 'firefox', platform },
    module: { exports: {} },
    Ci: { nsIFile: 'nsIFile' },
    ...globals,
  };
  vm.runInNewContext(src, sandbox);
  return sandbox.module.exports;
}

function stubs({ loaded = false, registry = null, log = [] } = {}) {
  return {
    log,
    globals: {
      Services: {
        env: { set: (k, v) => log.push(['env', k, v]), get: () => '' },
        dirsvc: { get: () => ({ append() {}, path: 'P/prefs.js' }) },
      },
      Cu: { isESModuleLoaded: () => loaded },
      ChromeUtils: { importESModule: () => ({ TargetRegistry: registry }) },
    },
  };
}

test('the program and its arguments', () => {
  const win = load('win', stubs().globals);
  const a = win.invocation();
  assert.equal(a.exeName, 'firefox.exe');
  assert.equal(JSON.stringify(a.params), '["--backgroundtask","pingsender"]');
  assert.notEqual(win.invocation().params, a.params, 'params must be a fresh array');
  assert.equal(load('linux', stubs().globals).invocation().exeName, 'firefox');
  assert.equal(win.PINGSENDER_ROUTE_ENV, 'STEALTHFOX_PINGSENDER_ROUTE');
});

test('the callbacks reach the channel only when given', () => {
  const m = load('win', stubs().globals);
  const bare = { channel: {} };
  m.attachCallbacks(bare, null);
  assert.equal('notificationCallbacks' in bare.channel, false);
  const cb = {};
  const req = { channel: {} };
  m.attachCallbacks(req, cb);
  assert.equal(req.channel.notificationCallbacks, cb);
});

test('the road is in the environment only around the start of the child', () => {
  const s = stubs();
  const m = load('win', s.globals);
  const observer = {};
  const proc = {
    runAsync(params, n, obs) {
      s.log.push(['run', JSON.stringify(params), n, obs === observer]);
    },
  };
  m.runAsync(proc, ['a'], observer);
  assert.equal(s.log.length, 3);
  assert.equal(s.log[0][0], 'env');
  assert.equal(s.log[0][1], 'STEALTHFOX_PINGSENDER_ROUTE');
  assert.equal(s.log[0][2], JSON.stringify({ proxy: null, prefs: 'P/prefs.js' }));
  assert.deepEqual(s.log[1], ['run', '["a"]', 1, true]);
  assert.deepEqual(s.log[2], ['env', 'STEALTHFOX_PINGSENDER_ROUTE', '']);
});

test('the environment is reset when the child cannot be started', () => {
  const s = stubs();
  const m = load('win', s.globals);
  const proc = { runAsync() { throw new Error('no start'); } };
  assert.throws(() => m.runAsync(proc, [], {}), /no start/);
  assert.deepEqual(s.log.at(-1), ['env', 'STEALTHFOX_PINGSENDER_ROUTE', '']);
});

test('the proxy record comes from the target registry when Juggler loaded it', () => {
  const run = registry => {
    const s = stubs({ loaded: true, registry });
    load('win', s.globals).runAsync({ runAsync() {} }, [], {});
    return JSON.parse(s.log[0][2]).proxy;
  };
  const road = proxy => ({ roadOfSession: id => ({ decided: true, proxy: proxy && { id } }) });
  assert.deepEqual(run(road(true)), { id: 0 });
  assert.equal(run(road(null)), null);
});
