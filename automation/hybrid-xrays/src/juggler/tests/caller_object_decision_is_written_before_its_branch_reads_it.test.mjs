// The page is handed a caller's object by the decision of an anchor (StealthNoteCallerObject, right after `sameOrigin`):
// the web-object case of WrapperFactory::Rewrap steps aside for it (its first term goes through StealthNotCallerObject, which
// only looks) and the regular case at the end of the chain takes it (StealthSelectedWrapper, which clears it). For the
// look never to see the decision of an earlier call, no path may reach the web-object case without passing the anchor: Rewrap
// must not return, jump or throw between the start of the function and the anchor, nor between the anchor and the take that
// follows the look. This reads the text of Rewrap and checks that; the unit half (the decision, its state, the look and the
// clearing read) is the gtest StealthCallerObject.*.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SOURCE = fs.readFileSync(path.join(TREE, 'js/xpconnect/wrappers/WrapperFactory.cpp'), 'utf8');

const ANCHOR = 'mozilla::StealthNoteCallerObject(origin, target, targetIsChrome, targetSubsumesOrigin);';
const BRANCH = 'else if (mozilla::StealthNotCallerObject(originSubsumesTarget == targetSubsumesOrigin) &&';
const TAKE = 'wrapper = mozilla::StealthSelectedWrapper(cx, SelectWrapper(';
const JUMPS = /\b(return|goto|throw|MOZ_TRY|NS_ENSURE_[A-Z_]+|MOZ_CRASH)\b/;

// What stands between the start of Rewrap and the anchor, and between the anchor and the branch, as a list of what is wrong.
function whatIsNotProved(text) {
  const wrong = [];
  const start = text.indexOf('JSObject* WrapperFactory::Rewrap(');
  const anchor = text.indexOf(ANCHOR, start);
  const branch = text.indexOf(BRANCH, anchor);
  const take = text.indexOf(TAKE, branch);
  if (start < 0 || anchor < start) wrong.push('the anchor is not in Rewrap');
  else if (branch < anchor) wrong.push('the look does not come after the anchor');
  else if (take < branch) wrong.push('the take does not come after the look');
  else {
    const before = text.slice(text.indexOf('{', start), anchor).replace(/\/\/.*$/gm, '');
    const between = text.slice(anchor, take).replace(/\/\/.*$/gm, '');
    if (JUMPS.test(before)) wrong.push('a path can leave Rewrap before the anchor');
    if (JUMPS.test(between)) wrong.push('a path can leave Rewrap between the anchor and the take');
    if ((text.slice(start, take + TAKE.length).match(/mozilla::StealthNotCallerObject\(/g) || []).length !== 1) wrong.push('the decision is looked at more than once');
    if (/mozilla::StealthCallerObjectApplies\(\)/.test(text.slice(start, take + TAKE.length))) wrong.push('Rewrap reads the decision itself');
  }
  return wrong;
}

test('no path reaches the branch without passing the anchor, and the anchor writes before the branch reads', () => {
  assert.deepEqual(whatIsNotProved(SOURCE), []);
});

test('negative control: a return before the anchor or between the anchor and the branch is not proved', () => {
  const early = SOURCE.replace('  bool sameOrigin = targetSubsumesOrigin && originSubsumesTarget;\n',
    '  if (!origin) return nullptr;\n  bool sameOrigin = targetSubsumesOrigin && originSubsumesTarget;\n');
  assert.notEqual(early, SOURCE);
  assert.notDeepEqual(whatIsNotProved(early), []);
  const late = SOURCE.replace('  const Wrapper* wrapper;\n', '  if (!target) return nullptr;\n  const Wrapper* wrapper;\n');
  assert.notEqual(late, SOURCE);
  assert.notDeepEqual(whatIsNotProved(late), []);
});
