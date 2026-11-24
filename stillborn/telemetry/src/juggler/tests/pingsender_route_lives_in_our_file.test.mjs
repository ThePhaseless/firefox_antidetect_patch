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
  // StealthRoutedProcess(process).runAsync, with Mozilla's own arguments: a
  // second `.runAsync(` that Mozilla adds to a new version would start a child
  // with no road in its environment.
  const starts = text.split('\n').filter(l => /\.runAsync\(/.test(l));
  assert.deepEqual(starts.map(l => l.trim()),
    [`StealthRoutedProcess(process).runAsync(params, params.length, observer); // ${HOOK}`]);
  // Near-miss guard: the call exists.
  assert.ok(starts.length === 1, 'the start of the pingsender moved');
});

test('Mozilla chooses its program and never starts it: the only start is the routed one', () => {
  const text = fs.readFileSync(path.join(APP, 'TelemetrySend.sys.mjs'), 'utf8');
  // Mozilla's choice of the program (`exeName`, `params`) stays as Mozilla wrote
  // it, with no override of ours after it; what starts is the routed child.
  assert.ok(!text.includes('StealthPingsender.invocation'), "an override of Mozilla's program is back");
  const uses = [...text.matchAll(/exe\.append\(exeName\)/g)];
  assert.equal(uses.length, 1, 'a second place builds a program');
  assert.ok(text.includes('StealthRoutedProcess(process).runAsync('), 'the routed start is gone');
});

// Load the own file on stubs: the one import is replaced by a stub object and
// `export` is dropped.
function load(platform, globals, mutate = s => s) {
  let src = mutate(fs.readFileSync(path.join(APP, 'StealthPingsender.sys.mjs'), 'utf8'));
  src = src.replace(/^import \{ AppConstants \}.*$/m, 'const AppConstants = __AppConstants;');
  src = src.replace(/^export /gm, '');
  src += '\nmodule.exports = { PINGSENDER_ROUTE_ENV, attachCallbacks, invocation, StealthRoutedProcess };\n';
  const sandbox = {
    __AppConstants: { MOZ_APP_NAME: 'firefox', platform },
    module: { exports: {} },
    Ci: { nsIFile: 'nsIFile', nsIProcess: 'nsIProcess' },
    ...globals,
  };
  vm.runInNewContext(src, sandbox);
  return sandbox.module.exports;
}

function stubs({ loaded = false, registry = null, log = [], throwOnStart = false } = {}) {
  // The child the routed start makes: a process of its own, logged.
  const child = {
    init(file) { log.push(['init', file.appended]); },
    runAsync(args, n, obs) {
      if (throwOnStart) throw new Error('no start');
      log.push(['run', JSON.stringify(args), n, obs]);
    },
  };
  return {
    log,
    globals: {
      Cc: { '@mozilla.org/process/util;1': { createInstance: () => child } },
      Services: {
        env: { set: (k, v) => log.push(['env', k, v]), get: () => '' },
        dirsvc: { get: () => ({ append(n) { this.appended = n; }, path: 'P/prefs.js' }) },
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

test("the child is firefox --backgroundtask pingsender with Mozilla's parameters, and Mozilla's own process is never started", () => {
  const s = stubs();
  const m = load('win', s.globals);
  const observer = {};
  // Mozilla's process: the program it chose (pingsender), init'd and never run.
  const proc = { runAsync() { s.log.push(['mozilla-process-started']); } };
  m.StealthRoutedProcess(proc).runAsync(['u', 'p'], 2, observer);
  // Control: taking the routing away (calling Mozilla's process) is what this
  // would see instead.
  assert.ok(!s.log.some(e => e[0] === 'mozilla-process-started'), "Mozilla's own program was started");
  const runs = s.log.filter(e => e[0] === 'run');
  assert.equal(runs.length, 1);
  assert.deepEqual(s.log.find(e => e[0] === 'init'), ['init', 'firefox.exe']);
  assert.equal(runs[0][1], '["--backgroundtask","pingsender","u","p"]');
  assert.equal(runs[0][2], 4);
  assert.equal(runs[0][3], observer);
});

test('the road is in the environment only around the start of the child', () => {
  const s = stubs();
  const m = load('win', s.globals);
  m.StealthRoutedProcess({ runAsync() {} }).runAsync(['a'], 1, {});
  const env = s.log.filter(e => e[0] === 'env');
  assert.equal(env.length, 2);
  assert.equal(env[0][1], 'STEALTHFOX_PINGSENDER_ROUTE');
  assert.equal(env[0][2], JSON.stringify({ proxy: null, prefs: 'P/prefs.js' }));
  assert.deepEqual(env[1], ['env', 'STEALTHFOX_PINGSENDER_ROUTE', '']);
  const at = k => s.log.findIndex(e => e[0] === k);
  assert.ok(s.log.indexOf(env[0]) < at('run') && at('run') < s.log.indexOf(env[1]));
});

test('the environment is reset when the child cannot be started', () => {
  const s = stubs({ throwOnStart: true });
  const m = load('win', s.globals);
  const proc = { runAsync() {} };
  assert.throws(() => m.StealthRoutedProcess(proc).runAsync([], 0, {}), /no start/);
  assert.deepEqual(s.log.at(-1), ['env', 'STEALTHFOX_PINGSENDER_ROUTE', '']);
});

test('the proxy record comes from the target registry when Juggler loaded it', () => {
  const run = registry => {
    const s = stubs({ loaded: true, registry });
    load('win', s.globals).StealthRoutedProcess({ runAsync() {} }).runAsync([], 0, {});
    return JSON.parse(s.log.find(e => e[0] === 'env')[2]).proxy;
  };
  const road = proxy => ({ roadOfSession: id => ({ decided: true, proxy: proxy && { id } }) });
  assert.deepEqual(run(road(true)), { id: 0 });
  assert.equal(run(road(null)), null);
});

// ---- Mozilla's own process is never run ----
// Mozilla's runPingSender initialises `process` on its own program (pingsender[.exe], or the background task when a Nimbus
// variable says so) and the hook hands it to StealthRoutedProcess, which starts a child of its own. No run of Mozilla's
// process may follow its init: not run, runAsync, runw nor runwAsync, in TelemetrySend.sys.mjs or in our file.

const RUNS = /\bprocess\.(run|runAsync|runw|runwAsync)\(/g;
const runsOfMozillasProcess = text => [...text.matchAll(RUNS)].map(m => m[0]);

test("no run of Mozilla's process follows its init, in TelemetrySend.sys.mjs or in our file", () => {
  const send = fs.readFileSync(path.join(APP, 'TelemetrySend.sys.mjs'), 'utf8');
  const ours = fs.readFileSync(path.join(APP, 'StealthPingsender.sys.mjs'), 'utf8');
  assert.deepEqual(runsOfMozillasProcess(send), []);
  assert.deepEqual(runsOfMozillasProcess(ours), []);
  // The init is there (Mozilla's own line), so the rule is about something.
  assert.ok(/process\.init\(exe\)/.test(send), "Mozilla's init of the process is gone");
});

test("negative control: a run of Mozilla's process is found in either file", () => {
  const send = fs.readFileSync(path.join(APP, 'TelemetrySend.sys.mjs'), 'utf8');
  const ours = fs.readFileSync(path.join(APP, 'StealthPingsender.sys.mjs'), 'utf8');
  const unhooked = send.replace('StealthRoutedProcess(process).runAsync(', 'process.runAsync(');
  assert.notEqual(unhooked, send);
  assert.deepEqual(runsOfMozillasProcess(unhooked), ['process.runAsync(']);
  const routedToMozilla = ours.replace('child.runAsync(args, args.length, observer);', 'process.runAsync(params, count, observer);');
  assert.notEqual(routedToMozilla, ours);
  assert.deepEqual(runsOfMozillasProcess(routedToMozilla), ['process.runAsync(']);
});

test("the routed start never calls Mozilla's process, whatever the road", () => {
  for (const loaded of [false, true]) {
    const s = stubs({ loaded, registry: loaded ? { roadOfSession: () => ({ decided: true, proxy: null }) } : null });
    const m = load('win', s.globals);
    const ran = [];
    const mozilla = Object.fromEntries(['run', 'runAsync', 'runw', 'runwAsync'].map(k => [k, () => ran.push(k)]));
    m.StealthRoutedProcess(mozilla).runAsync(['u', 'p'], 2, {});
    assert.deepEqual(ran, [], "Mozilla's process was run");
    assert.equal(s.log.filter(e => e[0] === 'run').length, 1, 'only the routed child runs');
  }
});

test("negative control: a start that goes back to Mozilla's process is seen by the behaviour test", () => {
  const s = stubs();
  const m = load('win', s.globals, src => src.replace('child.runAsync(args, args.length, observer);', 'process.runAsync(params, count, observer);'));
  const ran = [];
  m.StealthRoutedProcess({ runAsync: () => ran.push('runAsync') }).runAsync(['u', 'p'], 2, {});
  assert.deepEqual(ran, ['runAsync']);
});
