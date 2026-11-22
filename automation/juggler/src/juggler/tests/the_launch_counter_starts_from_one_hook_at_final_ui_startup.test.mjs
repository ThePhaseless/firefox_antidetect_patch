// The launch counter is started from one place: the one line in BrowserGlue._beforeUIStartup, which the final-ui-startup observer calls, before any tab
// exists. The line imports the module itself and fires it inside a try/catch, as the first statement, so an error of the counter never skips
// SessionStartup.init(). It was held by an xpcshell task that read BrowserGlue.sys.mjs through resource:/// (the packaged omni.ja does not serve the source
// text), so it is held here, on the source. The behaviour of the module (one plain GET to the fixed address, no pref) stays in the xpcshell file
// browser/components/tests/unit/test_stealth_launch_counter.js.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const GLUE = 'browser/components/BrowserGlue.sys.mjs';
const HOOK = '    try { ChromeUtils.importESModule("resource:///modules/StealthLaunchCounter.sys.mjs").StealthLaunchCounter.fire(); } catch {}  // STEALTH-HOOK(platform/launch-counter)';
const HEAD = '  _beforeUIStartup: function BG__beforeUIStartup() {\n';

test('BrowserGlue starts the launch counter from one line, the first statement of _beforeUIStartup, and from nowhere else', () => {
  const text = read(GLUE);
  assert.equal(text.split('\n').filter(l => l.includes('StealthLaunchCounter')).length, 1, 'more or less than one line of BrowserGlue names the counter');
  assert.equal(text.match(/StealthLaunchCounter\.fire\(/g).length, 1, 'the counter is started from more or less than one place');
  assert.equal(text.split('\n').filter(l => l.includes('STEALTH-HOOK(platform/launch-counter)')).length, 1, 'one tagged line');
  const start = text.indexOf(HEAD);
  assert.ok(start > 0, '_beforeUIStartup is not where it was');
  assert.equal(text.slice(start, text.indexOf('lazy.SessionStartup.init();', start)), HEAD + HOOK + '\n    ',
    'the hook is not the line of the contract, or not the first thing _beforeUIStartup does');
});

test('the counter is not a lazy getter of BrowserGlue: the hook line is its only import', () => {
  const text = read(GLUE);
  assert.doesNotMatch(text, /lazy\.StealthLaunchCounter/);
  assert.doesNotMatch(text, /\n\s*StealthLaunchCounter: "resource:/);
});

test('the final-ui-startup observer is what reaches _beforeUIStartup, and nothing else calls it', () => {
  const text = read(GLUE);
  assert.match(text, /case "final-ui-startup":\n        this\._beforeUIStartup\(\);\n/);
  assert.equal(text.match(/this\._beforeUIStartup\(/g).length, 1, 'another caller of _beforeUIStartup');
  assert.match(text, /\n      "final-ui-startup",\n/, 'the observer no longer listens to final-ui-startup');
});

test('the module is one tagged line of moz.build', () => {
  const build = read('browser/components/moz.build');
  assert.equal(build.match(/StealthLaunchCounter/g).length, 1);
  assert.match(build, /\nEXTRA_JS_MODULES \+= \["StealthLaunchCounter\.sys\.mjs"\]  # STEALTH-HOOK\(platform\/launch-counter\)\n/);
});
