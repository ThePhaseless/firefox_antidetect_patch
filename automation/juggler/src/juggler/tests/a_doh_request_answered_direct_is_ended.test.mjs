// A DoH request exists only because a context has a proxy, so an answer of its proxy lookup that leaves it DIRECT
// (no proxy info, or a "direct" one) ends the request: it is not connected. The filter of the session answers "no
// proxy" for a request of a context that is gone or whose bypass list matches the DoH host, and the fail-closed rule
// only fired on a FAILED lookup, so such a request went to the DoH server from the host's own address.
//
// Behaviour of the two pure functions: netwerk/test/gtest/TestStealthSessionResolver.cpp. Here the hooks sit where
// they must, on the existing tagged lines (no new Mozilla line), and the functions are where the files include them.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const TAG = '  // STEALTH-HOOK(network/doh)';

test('TRRServiceChannel::OnProxyAvailable hands the answer, not only the status, to the fail-closed rule', () => {
  const text = read('netwerk/protocol/http/TRRServiceChannel.cpp');
  const body = text.slice(text.indexOf('TRRServiceChannel::OnProxyAvailable('));
  const line = 'if (StealthTRRServiceOnProxyAnswer(this, status, pi)) return NS_OK;' + TAG;
  const hook = body.indexOf(line);
  assert.ok(hook > 0, 'the hook does not read the answer');
  assert.ok(body.indexOf('if (NS_SUCCEEDED(status)) mProxyInfo = pi;') > hook, 'the answer is used before the rule');
  assert.ok(body.indexOf('rv = BeginConnect();') > hook, 'the connection begins before the rule');
  // The answer is turned into a status by one call, in the template, for a channel that is a DoH one by construction.
  const header = read('netwerk/ipc/StealthTRRContext.h');
  const fn = header.match(/bool StealthTRRServiceOnProxyAnswer\([\s\S]*?\n}\n/)[0];
  assert.match(fn, /StealthTRRProxyAnswer\(aStatus, aProxyInfo, true\)/);
});

test('nsHttpChannel::OnProxyAvailable does the same for the DoH channel, and for it alone', () => {
  const text = read('netwerk/protocol/http/nsHttpChannel.cpp');
  const body = text.slice(text.indexOf('nsHttpChannel::OnProxyAvailable('));
  const line = 'if (StealthChannelOnProxyAnswer(this, status, pi)) return NS_OK;' + TAG;
  const hook = body.indexOf(line);
  assert.ok(hook > 0, 'the hook does not read the answer');
  assert.ok(body.indexOf('if (NS_SUCCEEDED(status)) {\n    mProxyInfo = pi;') > hook, 'the answer is used before the rule');
  // The DIRECT answer of a page channel is legitimate (a bypass list): the template passes the kind of channel it is.
  assert.doesNotMatch(text, /StealthTRRProxyAnswer\(/);
  const header = read('netwerk/ipc/StealthTRRContext.h');
  const fn = header.match(/bool StealthChannelOnProxyAnswer\([\s\S]*?\n}\n/)[0];
  assert.match(fn, /StealthTRRProxyAnswer\(aStatus, aProxyInfo, isTRR\)/);
  assert.doesNotMatch(fn, /aProxyInfo, true\)/);
});

test('the answer of a proxy lookup is read by the templates of our header alone, never by a call in the two Mozilla files', () => {
  // The only callers of StealthTRRProxyAnswer are the two templates that hand a channel's answer to the rule.
  for (const file of ['netwerk/protocol/http/TRRServiceChannel.cpp', 'netwerk/protocol/http/nsHttpChannel.cpp'])
    assert.doesNotMatch(read(file), /StealthTRRProxyAnswer\(/, file);
  const header = read('netwerk/ipc/StealthTRRContext.h');
  assert.equal(header.split(/StealthTRRProxyAnswer\(aStatus/).length - 1, 2);
});

test('the two functions are declared where the Mozilla files include them and defined with the resolver', () => {
  const header = read('netwerk/ipc/StealthTRRContext.h');
  assert.match(header, /\nclass nsIProxyInfo;\n/);
  assert.match(header, /\nbool StealthTRRProxyAnswerRefused\(nsIProxyInfo\* aProxyInfo\);\n/);
  assert.match(header, /\nnsresult StealthTRRProxyAnswer\(nsresult aStatus, nsIProxyInfo\* aProxyInfo,\n\s+bool aIsTRRServiceChannel\);\n/);
  const source = read('netwerk/dns/StealthSessionResolver.cpp');
  assert.match(source, /#include "nsIProxyInfo\.h"\n/);
  const refused = source.slice(source.indexOf('bool StealthTRRProxyAnswerRefused('), source.indexOf('nsresult StealthTRRProxyAnswer('));
  assert.match(refused, /if \(!aProxyInfo\) \{\n    return true;\n  \}/, 'no proxy info is a DIRECT answer');
  assert.match(refused, /GetType\(type\)\) \|\| type\.EqualsLiteral\("direct"\)/, 'a "direct" proxy info is one too');
  const answer = source.slice(source.indexOf('nsresult StealthTRRProxyAnswer('));
  assert.match(answer, /NS_SUCCEEDED\(aStatus\) && aIsTRRServiceChannel &&\s+StealthTRRProxyAnswerRefused\(aProxyInfo\)/);
  assert.match(answer, /return NS_ERROR_PROXY_CONNECTION_REFUSED;\n  \}\n  return aStatus;/, 'a failed lookup keeps its status');
});

test('the refusal ends the request the way a failed lookup does: the template reads it as a failure', () => {
  // StealthTRRProxyFailure turns a failure into the refusal; a cancellation keeps its own code. The refusal is a failure.
  const context = read('netwerk/ipc/StealthTRRContext.cpp');
  assert.match(context, /return NS_ERROR_PROXY_CONNECTION_REFUSED;/);
  assert.match(context, /return NS_FAILED\(aProxyStatus\) && aIsTRRServiceChannel && !aCanceled;/);
});

test('the gtest of the two functions is in the suite the candidate runs', () => {
  const text = read('netwerk/test/gtest/TestStealthSessionResolver.cpp');
  for (const name of ['AnAnswerWithNoProxyInfoIsRefusedForADoHRequest', 'ADirectProxyInfoIsRefusedForADoHRequest',
      'AProxyAnswerThatIsAProxyIsLeftAlone', 'OnlyADoHRequestIsRefusedAndAFailureKeepsItsStatus'])
    assert.match(text, new RegExp(`TEST\\(TestStealthSessionResolver, ${name}\\)`), name);
  for (const include of ['nsIProtocolProxyService.h', 'nsIProxyInfo.h', 'nsNetCID.h', 'nsServiceManagerUtils.h'])
    assert.ok(text.includes(`#include "${include}"`), include);
});
