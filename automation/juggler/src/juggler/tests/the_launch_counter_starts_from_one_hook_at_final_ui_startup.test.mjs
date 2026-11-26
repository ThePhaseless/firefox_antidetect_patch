// The launch counter is started from one place: the one line in BrowserGlue._beforeUIStartup, which the final-ui-startup observer calls, before any tab
// exists. The line imports the loader of ours (StealthLaunchCounterLoader, which imports nothing at its top) and calls it, as the first statement: one
// call, and nothing else. An error of the counter never skips SessionStartup.init(): the guarded import of the counter module is inside the loader, which
// catches any failure (the module does not load, its fire() throws) and logs it (console.error); fire() itself swallows a throw of fetch and a rejection
// of its promise. The runs of both modules below hold that.
// It was held by an xpcshell task that read BrowserGlue.sys.mjs through resource:/// (the packaged omni.ja does not serve the source
// text), so it is held here, on the source. The behaviour of the module (one plain GET to the fixed address, no pref) stays in the xpcshell file
// browser/components/tests/unit/test_stealth_launch_counter.js.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const GLUE = 'browser/components/BrowserGlue.sys.mjs';
const HOOK = '    ChromeUtils.importESModule("resource:///modules/StealthLaunchCounterLoader.sys.mjs").StealthLaunchCounterLoader.fire();  // STEALTH-HOOK(platform/launch-counter)';
const HEAD = '  _beforeUIStartup: function BG__beforeUIStartup() {\n';

test('BrowserGlue starts the launch counter from one line, the first statement of _beforeUIStartup, and from nowhere else', () => {
  const text = read(GLUE);
  assert.equal(text.split('\n').filter(l => l.includes('StealthLaunchCounter')).length, 1, 'more or less than one line of BrowserGlue names the counter');
  assert.equal(text.match(/StealthLaunchCounterLoader\.fire\(/g).length, 1, 'the counter is started from more or less than one place');
  assert.equal(text.split('\n').filter(l => l.includes('STEALTH-HOOK(platform/launch-counter)')).length, 1, 'one tagged line');
  const start = text.indexOf(HEAD);
  assert.ok(start > 0, '_beforeUIStartup is not where it was');
  assert.equal(text.slice(start, text.indexOf('lazy.SessionStartup.init();', start)), HEAD + HOOK + '\n    ',
    'the hook is not the line of the contract, or not the first thing _beforeUIStartup does');
});

test('the counter is not a lazy getter of BrowserGlue: the hook line is its only import', () => {
  const text = read(GLUE);
  assert.doesNotMatch(text, /lazy\.StealthLaunchCounter/);
  assert.doesNotMatch(text, /\n\s*StealthLaunchCounter(Loader)?: "resource:/);
  assert.doesNotMatch(text, /StealthLaunchCounter\.sys\.mjs/, 'BrowserGlue imports the counter module itself, not through the loader');
});

test('the final-ui-startup observer is what reaches _beforeUIStartup, and nothing else calls it', () => {
  const text = read(GLUE);
  assert.match(text, /case "final-ui-startup":\n        this\._beforeUIStartup\(\);\n/);
  assert.equal(text.match(/this\._beforeUIStartup\(/g).length, 1, 'another caller of _beforeUIStartup');
  assert.match(text, /\n      "final-ui-startup",\n/, 'the observer no longer listens to final-ui-startup');
});

test('the module and its loader are one tagged line of moz.build', () => {
  const build = read('browser/components/moz.build');
  assert.equal(build.match(/StealthLaunchCounter/g).length, 2);
  assert.match(build, /\nEXTRA_JS_MODULES \+= \["StealthLaunchCounter\.sys\.mjs", "StealthLaunchCounterLoader\.sys\.mjs"\]  # STEALTH-HOOK\(platform\/launch-counter\)\n/);
  assert.doesNotMatch(read('browser/components/StealthLaunchCounterLoader.sys.mjs'), /^import\s|\bimport\s*\(/m, 'the loader imports something at its top');
});

// A real run of the module: fire() never throws, whatever fetch does, so a failing counter cannot skip what comes after the hook line.
const { StealthLaunchCounter } = await import(pathToFileURL(path.join(TREE, 'browser/components/StealthLaunchCounter.sys.mjs')).href);

test('fire() makes one plain GET and swallows a throw of fetch and a rejection of its promise', async () => {
  const realFetch = globalThis.fetch;
  try {
    const calls = [];
    globalThis.fetch = (url, options) => { calls.push({ url, options }); return Promise.resolve({}); };
    StealthLaunchCounter.fire();
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /^https:\/\/github\.com\/oss-invisible\/firefox_antidetect_patch\/releases\/download\/usage-counter\/launch\.txt$/);
    assert.deepEqual(calls[0].options, { method: 'GET', credentials: 'omit', cache: 'no-store' });

    globalThis.fetch = () => { throw new Error('fetch is not available'); };
    assert.doesNotThrow(() => StealthLaunchCounter.fire());

    globalThis.fetch = () => Promise.reject(new Error('offline'));
    assert.doesNotThrow(() => StealthLaunchCounter.fire());
    await new Promise(resolve => setTimeout(resolve, 0));    // an unhandled rejection would have failed the run by now
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('negative control: a counter without its own try/catch would let a throw of fetch reach the hook line', () => {
  const source = read('browser/components/StealthLaunchCounter.sys.mjs');
  const bare = source.replace(/try \{\n      fetch\(/, '{\n      fetch(').replace(/\n    \} catch \(e\) \{\}\n/, '\n    }\n');
  assert.notEqual(bare, source, 'the negative control did not change the module');
  const data = 'data:text/javascript;base64,' + Buffer.from(bare).toString('base64');
  return import(data).then(({ StealthLaunchCounter: bareCounter }) => {
    const realFetch = globalThis.fetch;
    try {
      globalThis.fetch = () => { throw new Error('fetch is not available'); };
      assert.throws(() => bareCounter.fire());
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});

// A real run of the loader with a stand-in for ChromeUtils and console: a failure of the import of the counter (the module does not load) or
// of its fire() reaches nobody and is logged once, and a counter that works is fired once.
const { StealthLaunchCounterLoader } = await import(pathToFileURL(path.join(TREE, 'browser/components/StealthLaunchCounterLoader.sys.mjs')).href);

function runLoader(loader, importESModule) {
  const realChromeUtils = globalThis.ChromeUtils, realError = console.error;
  const logged = [];
  globalThis.ChromeUtils = { importESModule };
  console.error = (...args) => logged.push(args);
  try {
    loader.fire();
  } finally {
    globalThis.ChromeUtils = realChromeUtils;
    console.error = realError;
  }
  return logged;
}

test('the loader fires a counter that loads, once, and logs nothing', () => {
  const asked = [];
  let fired = 0;
  const logged = runLoader(StealthLaunchCounterLoader, url => { asked.push(url); return { StealthLaunchCounter: { fire() { fired++; } } }; });
  assert.deepEqual(asked, ['resource:///modules/StealthLaunchCounter.sys.mjs']);
  assert.equal(fired, 1);
  assert.deepEqual(logged, []);
});

test('a counter module that does not load stops in the loader and is logged', () => {
  const defect = new Error('NS_ERROR_FILE_NOT_FOUND: the module is not in the package');
  const logged = runLoader(StealthLaunchCounterLoader, () => { throw defect; });   // nothing propagates: runLoader would throw
  assert.equal(logged.length, 1, 'the failure is logged once');
  assert.match(String(logged[0][0]), /launch counter could not be started/);
  assert.equal(logged[0][1], defect);
});

test('a fire() that throws stops in the loader and is logged', () => {
  const logged = runLoader(StealthLaunchCounterLoader, () => ({ StealthLaunchCounter: { fire() { throw new Error('boom'); } } }));
  assert.equal(logged.length, 1);
});

test('negative control: a loader without its try/catch lets a load failure reach the hook line, and logs nothing', async () => {
  const source = read('browser/components/StealthLaunchCounterLoader.sys.mjs');
  const bare = source.replace(/try \{\n/, '{\n').replace(/\n    \} catch \(e\) \{\n      console\.error\([^\n]*\n    \}\n/, '\n    }\n');
  assert.notEqual(bare, source, 'the negative control did not change the loader');
  assert.doesNotMatch(bare, /catch/);
  const { StealthLaunchCounterLoader: bareLoader } = await import('data:text/javascript;base64,' + Buffer.from(bare).toString('base64'));
  const realChromeUtils = globalThis.ChromeUtils, realError = console.error;
  const logged = [];
  globalThis.ChromeUtils = { importESModule() { throw new Error('the module does not load'); } };
  console.error = (...args) => logged.push(args);
  try {
    assert.throws(() => bareLoader.fire());
  } finally {
    globalThis.ChromeUtils = realChromeUtils;
    console.error = realError;
  }
  assert.deepEqual(logged, []);
});
