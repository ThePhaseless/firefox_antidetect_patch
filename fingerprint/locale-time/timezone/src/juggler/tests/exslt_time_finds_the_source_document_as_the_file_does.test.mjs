// EXSLT's date:date-time() explodes the time in the zone of the document the stylesheet is transforming
// (StealthExplodeTime). The hook passes the evaluation context, a parameter of Mozilla's function, and
// dom/xslt/xslt/StealthExsltTime.h finds the document from it. This test pins that it finds the SAME document as the file's
// own getSourceDocument (the source document of the transformation's execution state, also when the transformation was
// reached through a stylesheet that imports or includes another one: the execution state is one per transformation), so the
// zone is the one the page declares for that document, as before the hook took the context.
//
// It reads both texts and compares the lookup step by step; the control changes ours to look somewhere else and must fail.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = f => fs.readFileSync(path.join(TREE, f), 'utf8');
const squeeze = s => s.replace(/\s+/g, ' ').trim();

// The steps of Mozilla's lookup, from the file's own getSourceDocument.
function mozillaSteps(text) {
  const start = text.indexOf('static Document* getSourceDocument(txIEvalContext* aContext) {');
  assert.ok(start > 0, 'getSourceDocument is gone from txEXSLTFunctions.cpp');
  const body = squeeze(text.slice(start, text.indexOf('\n}\n', start)));
  return {
    state: /static_cast<txExecutionState\*>\( ?aContext->getPrivateContext\(\) ?\)/.test(body),
    document: /es->getSourceDocument\(\)/.test(body),
    native: /txXPathNativeNode::getDocument\(/.test(body),
  };
}

function ourSteps(text) {
  const start = text.indexOf('inline void StealthExplodeTime(txIEvalContext* aContext');
  assert.ok(start > 0, 'the overload for the evaluation context is gone');
  const body = squeeze(text.slice(start, text.indexOf('\n}\n', start)));
  return {
    state: /static_cast<txExecutionState\*>\( ?aContext->getPrivateContext\(\) ?\)/.test(body),
    document: /es->getSourceDocument\(\)/.test(body),
    native: /txXPathNativeNode::getDocument\(/.test(body),
    explodes: /StealthExplodeTime\(sourceDoc, aTime, aParams, aExploded\)/.test(body),
    fallsBack: /PR_ExplodeTime\(aTime, aParams, aExploded\)/.test(body),
  };
}

test('the hook passes the evaluation context and nothing local', () => {
  const text = read('dom/xslt/xslt/txEXSLTFunctions.cpp');
  const lines = text.split('\n').filter(l => /StealthExplodeTime\(/.test(l));
  assert.deepEqual(lines.map(l => l.trim()),
    ['StealthExplodeTime(aContext, time, timezone, &prtime);  // STEALTH-HOOK(fingerprint/locale-time/timezone)']);
});

test('ours finds the source document the way getSourceDocument does, and explodes in its zone', () => {
  const mine = ourSteps(read('dom/xslt/xslt/StealthExsltTime.h'));
  assert.deepEqual({ state: mine.state, document: mine.document, native: mine.native },
    mozillaSteps(read('dom/xslt/xslt/txEXSLTFunctions.cpp')));
  assert.ok(mine.state && mine.document && mine.native, 'a step of the lookup is missing');
  assert.ok(mine.explodes, 'the zone of the source document is not the one used');
  assert.ok(mine.fallsBack, 'with no document the time is not exploded as Mozilla does');
});

test('negative control: a lookup that goes elsewhere is not the file\'s', () => {
  const ours = read('dom/xslt/xslt/StealthExsltTime.h');
  const elsewhere = ours.replace('es->getSourceDocument()', 'es->getEvalContext()');
  assert.notEqual(elsewhere, ours, 'the mutation did not apply');
  assert.notDeepEqual(
    (({ state, document, native }) => ({ state, document, native }))(ourSteps(elsewhere)),
    mozillaSteps(read('dom/xslt/xslt/txEXSLTFunctions.cpp')));
});

test('the case that reaches the hook has already refused a context with no source document', () => {
  const text = read('dom/xslt/xslt/txEXSLTFunctions.cpp');
  const at = text.indexOf('case txEXSLTType::DATE_TIME: {');
  const region = text.slice(at, text.indexOf('StealthExplodeTime(', at));
  assert.match(region, /Document\* sourceDoc = getSourceDocument\(aContext\);\s*NS_ENSURE_STATE\(sourceDoc\);/);
});
