// StealthNavigationLoad is built in nsDocShell::InternalLoad right before DoURILoad and takes only the docshell and the
// load state: it is a javascript: URL (the scheme of the load state's URI) that it does not notify for. A same-document
// navigation must never reach it, and InternalLoad's own text is what keeps it away: `sameDocument` is declared once,
// is written only by HandleSameDocumentNavigation (by reference) in the `if (sameDocument)` block, and that block returns
// when it is still true. This reads the text of InternalLoad and proves that, so a Mozilla change that lets a same-document
// load go on to DoURILoad turns this red instead of notifying a navigation that never leaves the document.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SOURCE = fs.readFileSync(path.join(TREE, 'docshell/base/nsDocShell.cpp'), 'utf8');

function internalLoad(text) {
  const start = text.indexOf('nsresult nsDocShell::InternalLoad(nsDocShellLoadState* aLoadState,');
  assert.ok(start > 0, 'InternalLoad is gone from nsDocShell.cpp');
  return text.slice(start, text.indexOf('\n}\n', start));
}

// The reasons `sameDocument` is false at the hook, as a list of what is wrong (empty: it is proved).
function whatIsNotProved(body) {
  const wrong = [];
  const lines = body.split('\n');
  const writes = lines.filter(l => /\bsameDocument\s*=(?!=)/.test(l));
  if (writes.length !== 1 || !/\bbool sameDocument =/.test(writes[0])) wrong.push('sameDocument is written outside its declaration');
  const byRef = [...body.matchAll(/HandleSameDocumentNavigation\(\s*aLoadState, sameDocumentNavigationState, sameDocument\)/g)];
  if (byRef.length !== 1) wrong.push('HandleSameDocumentNavigation is not the one place that takes sameDocument by reference');
  const outer = body.indexOf('  if (sameDocument) {\n');
  const inner = body.indexOf('    if (sameDocument) {\n', outer);
  const ret = body.indexOf('      return rv;\n', inner);
  const hook = body.indexOf('StealthNavigationLoad stealthLoad(this, aLoadState);');
  if (outer < 0 || inner < outer || ret < inner) wrong.push('the block does not return while sameDocument is still true');
  else if (body.indexOf('    }\n', ret) < ret || body.slice(inner, ret).includes('\n    }\n')) wrong.push('the return is not inside the inner if');
  if (hook < 0 || hook < ret) wrong.push('the hook is not after the same-document block');
  return wrong;
}

test('InternalLoad returns before the hook whenever sameDocument is still true, and nothing writes it after', () => {
  assert.deepEqual(whatIsNotProved(internalLoad(SOURCE)), []);
});

test('negative control: a block that does not return, or a later write of sameDocument, is not proved', () => {
  const body = internalLoad(SOURCE);
  const noReturn = body.replace('      return rv;\n', '      rv = rv;\n');
  assert.notDeepEqual(whatIsNotProved(noReturn), []);
  const lateWrite = body.replace('  const bool isJavaScript =', '  sameDocument = true;\n  const bool isJavaScript =');
  assert.notEqual(lateWrite, body, 'the mutation did not apply');
  assert.notDeepEqual(whatIsNotProved(lateWrite), []);
});

test('the hook takes the docshell and the load state only', () => {
  const body = internalLoad(SOURCE);
  assert.equal([...body.matchAll(/StealthNavigationLoad stealthLoad\(this, aLoadState\);/g)].length, 1);
});
