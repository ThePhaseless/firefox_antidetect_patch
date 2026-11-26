// The Safe Browsing completion ("gethash") of a page load is requested in the browser context of
// that page, so it leaves by that context's proxy and has the name of the provider resolved by that
// context's resolver. Upstream creates its channel in the default context (userContextId 0,
// UrlClassifierHashCompleter.sys.mjs, openChannel) and puts the completions of every caller of one
// tick into one request per gethash URL, so the context of the page is lost twice: where the
// completer is called (nsUrlClassifierHashCompleterBase calls complete() with a prefix, a URL, a
// table and a callback, no context) and where the channel is born.
//
// The context is known where the lookup starts: nsUrlClassifierDBService::Classify gets the page's
// principal (made from the load info of the channel, userContextId included). A scope opened there
// is read by the completion callback made inside it, which gives it to the completer
// (nsIUrlClassifierHashCompleterCallback.userContextId). The JS completer keeps one HashCompleter
// per context: its batch, back-off and in-flight requests are its own, and its channel carries the
// context. The default context takes upstream's code unchanged.
//
// Source guards for the hooks and the C++ (which cannot run here), and a real run of the JS helper
// with stand-ins for the completer and the channel. The C++ behaviour is in
// netwerk/test/gtest/TestStealthTRRContext.cpp, the request level in
// toolkit/components/url-classifier/tests/unit/test_stealth_hashcompleter_context.js.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const DIR = 'toolkit/components/url-classifier/';
const DB = DIR + 'nsUrlClassifierDBService.cpp';
const IDL = DIR + 'nsIUrlClassifierHashCompleter.idl';
const COMPLETER = DIR + 'UrlClassifierHashCompleter.sys.mjs';
const HELPER = DIR + 'StealthHashCompleterContext.sys.mjs';
const TAG = 'STEALTH-HOOK(network/doh)';
const count = (text, needle) => text.split(needle).length - 1;
const lines = text => text.split(/\r?\n/);

test('the interface of the completion callback gives the context, one line beside the lines of Mozilla', () => {
  const text = read(IDL);
  const hook = '  readonly attribute uint32_t userContextId;  // ' + TAG + '\n';
  assert.equal(count(text, hook), 1);
  const callback = text.match(/interface nsIUrlClassifierHashCompleterCallback : nsISupports\n\{[\s\S]*?\n\};\n/)[0];
  assert.ok(callback.includes(hook), 'the attribute is not in the callback interface');
  // After an existing member of Mozilla's (the last statement of completionV4), not the last line of the interface.
  assert.ok(callback.includes('in nsIArray fullHashes);\n' + hook), 'the line is not right after completionV4');
  assert.ok(callback.indexOf(hook) < callback.indexOf('void completionFinished(in nsresult status);\n'), 'the line is the last of the interface');
  assert.ok(/\[scriptable, uuid\(da16de40-df26-414d-bde7-c4faf4504868\)\]\ninterface nsIUrlClassifierHashCompleterCallback/.test(text), 'Mozilla\'s interface line was rewritten');
});

test('the completion callbacks of a lookup read the context the lookup was made in, beside Mozilla\'s lines', () => {
  const text = read(DB);
  assert.ok(text.includes('#include "nsToolkitCompsCID.h"\n\n#include "mozilla/net/StealthTRRContext.h"  // ' + TAG + '\n\nnamespace mozilla {\nnamespace safebrowsing {'), 'the include is missing');
  // The only reader of the lookup context of the thread is the member of the completer base class.
  assert.equal(count(text, 'StealthCurrentLookupContext('), 1, 'the context is read outside the callback that is made in the lookup');

  const base = text.match(/class nsUrlClassifierHashCompleterBase\n[\s\S]*?\n\};\n/)[0];
  const member = '  uint32_t mStealthUserContextId = mozilla::net::StealthCurrentLookupContext();  // ' + TAG + '\n';
  assert.ok(base.includes(member), 'the context is not read where the callback is made');
  assert.ok(base.indexOf('  nsCOMPtr<nsIUrlClassifierCallback> mCallback;\n' + member) > 0, 'the member is not right after one of Mozilla\'s members');
  assert.ok(base.indexOf(member) < base.indexOf('  uint32_t mPendingCompletions = 0;\n'), 'the member is the last of the class');
  assert.ok(base.includes('  NS_DECL_NSIURLCLASSIFIERHASHCOMPLETERCALLBACK\n'));

  // The getter of the attribute is defined in a file of ours, included right after Mozilla's NS_IMPL_ISUPPORTS (the class is
  // only visible in this file).
  const include = '#include "StealthHashCompleterContext.inc.h"  // ' + TAG + '\n';
  assert.equal(count(text, include), 1, 'the file with the getter of the attribute is not included');
  assert.doesNotMatch(text, /GetUserContextId/, 'the getter is defined in Mozilla\'s file');
  assert.ok(text.indexOf('NS_IMPL_ISUPPORTS(nsUrlClassifierHashCompleterBase,\n                  nsIUrlClassifierHashCompleterCallback)\n' + include) > 0, 'the include is not right after Mozilla\'s NS_IMPL_ISUPPORTS');
  const getter = read(DIR + 'StealthHashCompleterContext.inc.h');
  assert.match(getter, /NS_IMETHODIMP nsUrlClassifierHashCompleterBase::GetUserContextId\(uint32_t\* aId\) \{\n  return mozilla::net::StealthLookupContextOut\(mStealthUserContextId, aId\);\n\}\n/);
});

test('Classify opens the scope with the page\'s principal as its first statement, before any callback is made, and only there', () => {
  const text = read(DB);
  const hook = '  mozilla::net::StealthLookupContextScope stealthScope(aPrincipal);  // ' + TAG + '\n';
  assert.equal(count(text, hook), 1);
  assert.equal(count(text, 'StealthLookupContextScope'), 1, 'a scope is opened outside Classify');
  const classify = text.match(/nsUrlClassifierDBService::Classify\(nsIPrincipal\* aPrincipal,[\s\S]*?\n\}\n/)[0];
  const at = classify.indexOf(hook);
  assert.ok(at > 0, 'the scope is not in Classify');
  // The first statement of the function: the scope only sets and restores the thread's context, and nothing that runs before the
  // lookups (the checks of the arguments, the early returns, the IPC of a content process, the permission test) reads it, so it
  // does not have to wait for the lookups to start.
  assert.equal(classify.indexOf('{\n' + hook) + 2, at, 'the scope is not the first statement of Classify');
  assert.ok(at < classify.indexOf('NS_ENSURE_ARG(aPrincipal);'), 'the scope is opened after the arguments are checked');
  assert.ok(at < classify.indexOf('new (fallible) nsUrlClassifierRealTimeLookupHandler('), 'the real-time handler is made before the scope');
  assert.ok(at < classify.indexOf('rv = LookupURI(key, holder, callback);'), 'the lookup callback is made before the scope');
  // Nothing before the lookups reads the context of the thread (the only reader is the member of the completer base class).
  assert.doesNotMatch(classify, /StealthCurrentLookupContext/);
  // Lookup() (download reputation) is outside this change: its callbacks are made with no scope.
  const lookup = text.match(/nsUrlClassifierDBService::Lookup\(nsIPrincipal\* aPrincipal,[\s\S]*?\n\}\n/)[0];
  assert.doesNotMatch(lookup, /Stealth/);
});

test('the JS completer hands a completion to the completer of its context, and its channel carries the context', () => {
  const text = read(COMPLETER);

  const imp = '\nimport { stealthApplyContext, stealthCompleteInContext } from "resource://gre/modules/StealthHashCompleterContext.sys.mjs";  // ' + TAG + '\n';
  assert.ok(text.includes('import { NetUtil } from "resource://gre/modules/NetUtil.sys.mjs";\n' + imp + '\nconst lazy = {};'), 'the import is not right after Mozilla\'s imports, on one line');
  assert.equal(count(text, 'StealthHashCompleterContext.sys.mjs'), 1, 'the module is imported twice');

  const handOver = '    if (stealthCompleteInContext(this, aPartialHash, aGethashUrl, aTableName, aCallback)) { return; }  // ' + TAG + '\n';
  assert.ok(text.includes('  complete(aPartialHash, aGethashUrl, aTableName, aCallback) {\n' + handOver + '    if (!aGethashUrl) {\n'), 'the hand-over is not the first line of complete()');
  assert.equal(count(text, 'stealthCompleteInContext('), 1, 'a second entry hands a completion over');

  const channel = '        "safebrowsing.86868755-6b82-4842-b301-72671a0db32e.mozilla",\n    };\n    stealthApplyContext(channel, this);  // ' + TAG + '\n';
  assert.ok(text.includes(channel), 'the channel does not get the context right after Mozilla\'s attributes');
  assert.equal(count(text, 'NetUtil.newChannel('), 1, 'a second channel of the completer would need the same context');
  const open = text.match(/  openChannel\(\) \{[\s\S]*?\n  \}\n/)[0];
  assert.ok(open.indexOf('stealthApplyContext(channel, this);') < open.indexOf('channel.asyncOpen(this);'), 'the context is given after the channel is opened');
  assert.ok(open.indexOf('loadUsingSystemPrincipal: true,') < open.indexOf('stealthApplyContext'));
  assert.doesNotMatch(text, /userContextId/, 'the logic is in our file, not in Mozilla\'s');
});

test('the helper module is registered beside Mozilla\'s modules', () => {
  const text = read(DIR + 'moz.build');
  assert.ok(text.includes('    "UrlClassifierRemoteSettingsService.sys.mjs",\n]\nEXTRA_JS_MODULES += ["StealthHashCompleterContext.sys.mjs"]  # ' + TAG + '\n'), 'the registration is not right after the list of Mozilla\'s modules');
  assert.equal(count(text, 'StealthHashCompleterContext.sys.mjs'), 1, 'the module is registered twice');
});

test('the xpcshell test is registered and asks for one request per context', () => {
  const toml = read(DIR + 'tests/unit/xpcshell.toml');
  assert.ok(toml.includes('["test_stealth_hashcompleter_context.js"]  # ' + TAG + '\n'));
  const test = read(DIR + 'tests/unit/test_stealth_hashcompleter_context.js');
  assert.match(test, /Assert\.deepEqual\(\s*ids,\s*\[0, 3, 7\]/);
  assert.match(test, /"http-on-modify-request"/);
  assert.match(test, /channel\.loadInfo\.originAttributes/);
});

test('our C++ keeps the lookup context per thread, in the file of the context', () => {
  const header = read('netwerk/ipc/StealthTRRContext.h');
  const code = read('netwerk/ipc/StealthTRRContext.cpp');
  assert.match(header, /\nuint32_t StealthCurrentLookupContext\(\);\n/);
  assert.match(header, /class StealthLookupContextScope final \{/);
  assert.match(header, /explicit StealthLookupContextScope\(uint32_t aUserContextId\);/);
  assert.match(header, /explicit StealthLookupContextScope\(nsIPrincipal\* aPrincipal\);/);
  assert.match(header, /nsresult StealthLookupContextOut\(uint32_t aContext, uint32_t\* aOut\);/);
  assert.match(header, /\nclass nsIPrincipal;\n/);
  assert.match(header, /#include <cstdint>\n/);
  assert.match(code, /static thread_local uint32_t sStealthLookupContext =\s*kStealthDefaultUserContextId;/);
  assert.match(code, /aPrincipal->OriginAttributesRef\(\)\.mUserContextId/);
  assert.match(code, /#include "nsIPrincipal\.h"/, 'the implementation uses nsIPrincipal and includes it');
  const dtor = code.match(/StealthLookupContextScope::~StealthLookupContextScope\(\) \{[\s\S]*?\n\}\n/)[0];
  assert.match(dtor, /sStealthLookupContext = mPrevious;/, 'the scope does not restore the previous context');
  const out = code.match(/nsresult StealthLookupContextOut\([\s\S]*?\n\}\n/)[0];
  assert.match(out, /NS_ENSURE_ARG_POINTER\(aOut\);/);
});

test('the gtest covers the principal, the nesting, the default context and the getter', () => {
  const text = read('netwerk/test/gtest/TestStealthTRRContext.cpp');
  assert.match(text, /TEST\(TestStealthTRRContext, ALookupScopeCarriesTheContextOfThePrincipalAndRestores\)/);
  assert.match(text, /attrs\.mUserContextId = 7;/);
  assert.match(text, /EXPECT_EQ\(StealthCurrentLookupContext\(\), 7u\);/);
  assert.match(text, /EXPECT_EQ\(StealthCurrentLookupContext\(\), 3u\);/);
  assert.match(text, /TEST\(TestStealthTRRContext, TheLookupContextGetterGivesTheContextAndRefusesNull\)/);
  assert.match(text, /#include "mozilla\/BasePrincipal\.h"/);
});

// A real run of the helper. The completer is a stand-in with the one thing the helper needs from
// it (its constructor makes a new completer, `complete` records the call).
const { stealthCompleteInContext, stealthApplyContext } =
    await import(pathToFileURL(path.join(TREE, HELPER)).href);

class FakeCompleter {
  constructor() { this.calls = []; }
  complete(...args) {
    if (stealthCompleteInContext(this, ...args)) return;
    this.calls.push(args);
  }
}

test('a completion of the default context, or of a callback with no context, stays in upstream\'s completer', () => {
  const completer = new FakeCompleter();
  completer.complete('1111', 'u', 't', { userContextId: 0 });
  completer.complete('2222', 'u', 't', {});
  completer.complete('3333', 'u', 't', null);
  completer.complete('4444', 'u', 't', { userContextId: -1 });
  completer.complete('5555', 'u', 't', { userContextId: 'x' });
  assert.equal(completer.calls.length, 5);
});

test('a completion of another context goes to a completer of that context, one per context, never mixed', () => {
  const completer = new FakeCompleter();
  const a = { userContextId: 41 };
  const b = { userContextId: 42 };
  completer.complete('1111', 'u', 't', a);
  completer.complete('2222', 'u', 't', b);
  completer.complete('3333', 'u', 't', a);
  completer.complete('4444', 'u', 't', {});
  assert.equal(completer.calls.length, 1, 'only the default context stays in upstream\'s completer');
  assert.equal(completer.calls[0][0], '4444');
});

test('the completer of a context runs upstream\'s code, and is the same one for the same context', () => {
  const created = [];
  class Completer {
    constructor() { created.push(this); this.calls = []; }
    complete(...args) {
      if (stealthCompleteInContext(this, ...args)) return;
      this.calls.push(args);
    }
  }
  const root = new Completer();
  const a = { userContextId: 51 };
  const b = { userContextId: 52 };
  root.complete('1111', 'u', 't', a);
  root.complete('2222', 'u', 't', b);
  root.complete('3333', 'u', 't', a);
  assert.equal(root.calls.length, 0);
  assert.equal(created.length, 3, 'one completer per context');
  const [, forA, forB] = created;
  assert.equal(forA.stealthUserContextId, 51);
  assert.equal(forB.stealthUserContextId, 52);
  assert.deepEqual(forA.calls.map(c => c[0]), ['1111', '3333']);
  assert.deepEqual(forB.calls.map(c => c[0]), ['2222']);
  assert.equal(root.stealthUserContextId, undefined, 'the root keeps the default context');
});

test('the channel of a completer of a context carries the context and keeps the first party domain', () => {
  const channel = { loadInfo: { originAttributes: { firstPartyDomain: 'safebrowsing.x.mozilla', userContextId: 0 } } };
  stealthApplyContext(channel, { completer: { stealthUserContextId: 7 } });
  assert.deepEqual(channel.loadInfo.originAttributes, { firstPartyDomain: 'safebrowsing.x.mozilla', userContextId: 7 });
});

test('the channel of the default completer is left as upstream made it', () => {
  const original = { firstPartyDomain: 'safebrowsing.x.mozilla' };
  const channel = { loadInfo: { originAttributes: original } };
  stealthApplyContext(channel, { completer: {} });
  assert.equal(channel.loadInfo.originAttributes, original);
});

test('a channel that refuses the context fails the request, it is not swallowed', () => {
  const channel = { loadInfo: { get originAttributes() { return { firstPartyDomain: 'f' }; }, set originAttributes(v) { throw new Error('refused'); } } };
  assert.throws(() => stealthApplyContext(channel, { completer: { stealthUserContextId: 7 } }), /refused/);
});
