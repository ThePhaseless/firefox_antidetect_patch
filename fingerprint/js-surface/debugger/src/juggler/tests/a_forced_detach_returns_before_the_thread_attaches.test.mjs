// zoom.stealth.debugger.force_detach: with the pref true ThreadActor.attach
// returns before any statement of Mozilla's attach() runs (nothing of the
// actor is read, so the thread never attaches through this path); with the pref
// false Mozilla's code is reached. The test runs the attach() method of
// devtools/server/actors/thread.js itself, with a recording `this` and a stub
// of Services.prefs.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const source = fs.readFileSync(path.join(ROOT, 'devtools', 'server', 'actors', 'thread.js'), 'utf8');

const PREF = 'zoom.stealth.debugger.force_detach';

function attachWith(prefValue) {
  const m = source.match(/\n  (attach\(options\) \{[\s\S]*?\n  \})\n/);
  assert.ok(m, 'ThreadActor.attach is gone from thread.js');
  const reads = [];
  const Services = {
    prefs: {
      getBoolPref(name, fallback) {
        reads.push([name, fallback]);
        return name === PREF ? prefValue : fallback;
      },
    },
  };
  const attach = new Function('Services', `return function ${m[1]};`)(Services);
  const touched = [];
  const actor = new Proxy({}, {
    get(_, prop) {
      touched.push(String(prop));
      return prop === 'alreadyAttached' ? true : undefined;
    },
    set(_, prop) {
      touched.push(`set ${String(prop)}`);
      return true;
    },
  });
  const result = attach.call(actor, {});
  return { result, touched, reads };
}

test('with the pref true attach() returns before it reads anything of the actor', () => {
  const { result, touched, reads } = attachWith(true);
  assert.equal(result, undefined);
  assert.deepEqual(reads, [[PREF, false]]);
  assert.deepEqual(touched, []);
});

test('with the pref false Mozilla\'s attach() is reached (negative control)', () => {
  const { result, touched, reads } = attachWith(false);
  assert.equal(result, undefined);
  assert.deepEqual(reads, [[PREF, false]]);
  assert.ok(touched.includes('alreadyAttached'), 'Mozilla\'s first check did not run: ' + touched);
});
