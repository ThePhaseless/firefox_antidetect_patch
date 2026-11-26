// Marionette's module of Selenium atoms (remote/marionette/atom.sys.mjs) keeps its table of source texts (ATOMS) to itself.
// PageAgent._elementAtom runs those sources through Xrays in its own sandbox, so it needs the table: the last line of the
// module hands it to our module (stealthRegisterAtoms) when the module is evaluated, and our module gives it back
// (stealthAtomSources) after making sure the module has been evaluated. The module is as Mozilla wrote it otherwise: no
// export of ours, nothing before that line.
//
// A real run of our module with a stand-in for ChromeUtils, and source guards for the two lines of Mozilla's and Juggler's
// files. The page-level run is the wrapper test tests/test_page_element_atoms_run_in_a_sandbox_e2e.py.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const ATOM = 'remote/marionette/atom.sys.mjs';
const OURS = 'juggler/StealthAtoms.sys.mjs';
const TAG = 'STEALTH-HOOK(automation/element-atoms)';
const URL_OURS = 'resource://gre/modules/juggler/StealthAtoms.sys.mjs';
const URL_ATOM = 'chrome://remote/content/marionette/atom.sys.mjs';

test('the last line of Marionette\'s module hands the table to our module, and nothing of ours is above it', () => {
  const text = read(ATOM);
  const hook = 'ChromeUtils.importESModule("' + URL_OURS + '").stealthRegisterAtoms(ATOMS);  // ' + TAG;
  const last = text.replace(/\s+$/, '').split('\n').pop();
  assert.equal(last, hook, 'the registration is not the last line of the module');
  assert.equal(text.split(TAG).length - 1, 1, 'another line of the module is ours');
  assert.doesNotMatch(text, /ATOM_SOURCES/, 'the module still exports the table itself');
  assert.match(text, /\nconst ATOMS = \{\n/, 'the table is not the const of Mozilla\'s');
});

// An import of Marionette's module: an importESModule / ChromeUtils.import call or a static import whose specifier names
// marionette/atom.sys.mjs. A comment that names the file is no import.
function importsMarionettesAtomModule(text) {
  const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  return /(?:importESModule|ChromeUtils\.import)\s*\(\s*['"][^'"]*marionette\/atom\.sys\.mjs['"]/.test(code)
    || /^\s*import\b[^;]*['"][^'"]*marionette\/atom\.sys\.mjs['"]/m.test(code);
}

test('PageAgent takes the table from our module and no longer from Marionette\'s exports', () => {
  const text = read('juggler/content/PageAgent.js');
  assert.ok(text.includes("ChromeUtils.importESModule(\n        '" + URL_OURS + "').stealthAtomSources();"), 'PageAgent does not ask our module');
  assert.doesNotMatch(text, /\{ATOM_SOURCES\}/);
  assert.equal(importsMarionettesAtomModule(text), false, 'PageAgent imports Marionette\'s module itself');
  assert.match(read('juggler/moz.build'), /\n    "StealthAtoms\.sys\.mjs",\n/, 'our module is not packaged');
});

// A real run of our module: ChromeUtils.importESModule is a stand-in that evaluates "Marionette's module" (the one line it
// ends with) when it is asked for the atom URL, and records what it was asked.
const asked = [];
let evaluateAtomModule = () => {};
globalThis.ChromeUtils = {
  importESModule(url) {
    asked.push(url);
    if (url === URL_ATOM) evaluateAtomModule();
    return {};
  },
};
const ours = await import(pathToFileURL(path.join(TREE, OURS)).href);

test('the table comes back as the same object, after the module that registers it has been evaluated', () => {
  const ATOMS = { getVisibleText: 'function(){}', isElementDisplayed: 'function(){}' };
  evaluateAtomModule = () => ours.stealthRegisterAtoms(ATOMS);
  asked.length = 0;
  assert.equal(ours.stealthAtomSources(), ATOMS);
  assert.deepEqual(asked, [URL_ATOM], 'the module of the atoms was not evaluated by the ask');
});

test('negative control: with no registration the answer is no table', () => {
  evaluateAtomModule = () => {};
  ours.stealthRegisterAtoms(null);
  assert.equal(ours.stealthAtomSources(), null);
});

test('negative control: a PageAgent that still imports Marionette\'s module is seen, and a comment that names the file is not', () => {
  const page = read('juggler/content/PageAgent.js');
  assert.match(page, /atom\.sys\.mjs/, 'no comment names the file any more: the control proves nothing');
  assert.equal(importsMarionettesAtomModule(page), false);
  const before = "ChromeUtils.importESModule(\n        'resource://gre/modules/juggler/StealthAtoms.sys.mjs').stealthAtomSources();";
  assert.ok(page.includes(before));
  const old = page.replace(before, "ChromeUtils.importESModule(\n        'chrome://remote/content/marionette/atom.sys.mjs').ATOM_SOURCES;");
  assert.equal(importsMarionettesAtomModule(old), true);
  assert.equal(importsMarionettesAtomModule("const {ATOM_SOURCES} = ChromeUtils.importESModule('chrome://remote/content/marionette/atom.sys.mjs');"), true);
  assert.equal(importsMarionettesAtomModule("import { atom } from 'chrome://remote/content/marionette/atom.sys.mjs';"), true);
});
