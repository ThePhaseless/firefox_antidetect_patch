// The DoH request of a process that is not the socket process.
//
// DNS (and with it TRR) runs in the socket process when there is one, and in the
// parent when there is none (nsDNSService2.cpp GetSingleton asserts exactly that:
// MOZ_DISABLE_SOCKET_PROCESS, too many socket process crashes, or the pref off).
// There TRR::SendHTTPRequest runs on the TRR thread, where
// DNSUtils::CreateChannelHelper makes a TRRServiceChannel, and on the MAIN thread
// after a proxy 401/407 (TRRService::DontUseTRRThread), where it makes a real
// nsHttpChannel. That channel's own OnProxyAvailable failed over to DIRECT when
// the proxy lookup failed: the name would leave from the host's address. The
// channel TRR.cpp marks as a TRR service channel now fails closed there too, as
// TRRServiceChannel does. Ordinary channels keep upstream's behaviour.
//
// Behaviour of the predicate: netwerk/test/gtest/TestStealthTRRContext.cpp.
// Here the hooks sit where they must, and the premises of that analysis are
// pinned: if one changes, this fails and the analysis is redone.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const section = (text, start, length = 6000) => text.slice(text.indexOf(start), text.indexOf(start) + length);

test('nsHttpChannel::OnProxyAvailable ends a TRR service channel whose proxy lookup failed', () => {
  const text = read('netwerk/protocol/http/nsHttpChannel.cpp');
  const body = section(text, 'nsHttpChannel::OnProxyAvailable(');
  const hook = body.indexOf('if (StealthChannelOnProxyAnswer(this, status, pi)) return NS_OK;  // STEALTH-HOOK(network/doh)\n');
  const used = body.indexOf('if (NS_SUCCEEDED(status)) {\n    mProxyInfo = pi;');
  assert.ok(hook > 0, 'no fail-closed rule in OnProxyAvailable');
  assert.ok(used > hook, 'the status is used before the rule');
  // The rule of the template: the answer, the kind of channel, the proxy of the context, the cancellation.
  const fn = read('netwerk/ipc/StealthTRRContext.h').match(/bool StealthChannelOnProxyAnswer\([\s\S]*?\n}\n/)[0];
  assert.match(fn, /return StealthTRRFailClosed\(\s*aChannel, StealthTRRProxyAnswer\(aStatus, aProxyInfo, isTRR\),\s*StealthProxyIsMandatory\(isTRR, loadInfo\.get\(\)\), canceled\);/);
});

test('nsHttpChannel: a proxy lookup that cannot start ends a TRR service channel too', () => {
  const text = read('netwerk/protocol/http/nsHttpChannel.cpp');
  const body = section(text, 'void nsHttpChannel::MaybeResolveProxyAndBeginConnect()', 2500);
  const lookup = body.indexOf('NS_SUCCEEDED(StealthChannelProxyLookup(this, ResolveProxy()))');
  const direct = body.indexOf('rv = BeginConnect();');
  assert.ok(lookup > 0, 'the lookup is not given to the rule');
  assert.equal(body.slice(0, body.indexOf('\n}\n')).split('ResolveProxy()').length - 1, 1, 'a second, bare call of ResolveProxy');
  assert.ok(direct > lookup, 'the DIRECT road is taken before the rule');
  // The rule of the template: the status of the lookup, the proxy of the context, the cancellation; then close and abort.
  const fn = read('netwerk/ipc/StealthTRRContext.h').match(/nsresult StealthChannelProxyLookup\([\s\S]*?\n}\n/)[0];
  assert.ok(fn.includes('{\n  if (NS_SUCCEEDED(aLookup)) return aLookup;\n'), 'a lookup that went well reads nothing');
  assert.match(fn, /StealthTRRFailClosed\(aChannel, aLookup,\s+StealthProxyIsMandatory\(isTRR, loadInfo\.get\(\)\),\s+canceled\)\s+\? NS_OK\s+: aLookup;/);
});

test('the rule is in our file, takes only the TRR flag, and nsHttpChannel reaches it through the templates alone', () => {
  const header = read('netwerk/ipc/StealthTRRContext.h');
  assert.match(header, /bool StealthFailClosedOnProxyFailure\(nsresult aProxyStatus,\s+bool aIsTRRServiceChannel,\s+bool aCanceled\);/);
  const source = read('netwerk/ipc/StealthTRRContext.cpp');
  assert.match(source, /bool StealthFailClosedOnProxyFailure\([^)]*\) \{\n\s+return NS_FAILED\(aProxyStatus\) && aIsTRRServiceChannel && !aCanceled;\n\}/);
  // The nsHttpChannel version closes the cache entry and ends the channel, as
  // upstream does when BeginConnect fails; both are public members.
  assert.match(header, /bool StealthTRRFailClosed\(ChannelT\* aChannel, nsresult aProxyStatus,\s+bool aIsTRRServiceChannel, bool aCanceled\) \{\n  if \(!StealthFailClosedOnProxyFailure\(aProxyStatus, aIsTRRServiceChannel,\s+aCanceled\)\) \{\n    return false;\n  \}\n  aChannel->CloseCacheEntry\(false\);\n  \(void\)aChannel->AsyncAbort\(StealthTRRProxyFailure\(aProxyStatus\)\);\n  return true;\n\}/);
  const channel = read('netwerk/protocol/http/nsHttpChannel.cpp');
  assert.match(channel, /#include "mozilla\/net\/StealthTRRContext\.h"  \/\/ STEALTH-HOOK\(network\/doh\)/);
  assert.doesNotMatch(channel, /StealthTRRFailClosed\(|StealthFailClosedOnProxyFailure\(/);
  assert.match(channel, /StealthChannelProxyLookup\(this, ResolveProxy\(\)\)/);
  assert.match(channel, /StealthChannelOnProxyAnswer\(this, status, pi\)/);
});

test('premise: TRR.cpp marks the channel it sends as a TRR service channel, OHTTP or not', () => {
  const text = read('netwerk/dns/TRR.cpp');
  const send = section(text, 'nsresult TRR::SendHTTPRequest()', 9000);
  assert.ok(send.includes('internalChannel->SetIsTRRServiceChannel(true);'));
  assert.ok(send.indexOf('SetIsTRRServiceChannel(true)') > send.indexOf('CreateChannelHelper'));
});

test('premise: only the main thread of a process that is not the socket process gets a real nsHttpChannel', () => {
  const text = read('netwerk/dns/DNSUtils.cpp');
  const body = section(text, 'nsresult DNSUtils::CreateChannelHelper(', 1400);
  assert.match(body, /if \(NS_IsMainThread\(\) && !XRE_IsSocketProcess\(\)\) \{[\s\S]*NS_NewChannel\(/);
  assert.match(body, /new TRRLoadInfo\(/);
  assert.match(body, /CreateTRRServiceChannel\(/);
});

test('premise: DNS runs in the socket process whenever there is one', () => {
  const text = read('netwerk/dns/nsDNSService2.cpp');
  assert.match(text, /MOZ_ASSERT_IF\(nsIOService::UseSocketProcess\(\), XRE_IsSocketProcess\(\)\);\n\s+MOZ_ASSERT_IF\(!nsIOService::UseSocketProcess\(\), XRE_IsParentProcess\(\)\);/);
  const service = read('netwerk/dns/TRRService.cpp');
  assert.match(service, /if \(XRE_IsSocketProcess\(\) \|\| mDontUseTRRThread\) \{\n\s+nsCOMPtr<nsIEventTarget> mainThread = do_GetMainThread\(\);/);
});

test('premise: the callers of CreateChannelHelper are known (a new one needs the same analysis)', () => {
  const callers = [];
  const walk = dir => {
    for (const entry of fs.readdirSync(path.join(TREE, dir), { withFileTypes: true })) {
      const rel = dir + '/' + entry.name;
      if (entry.isDirectory())
        walk(rel);
      else if (/\.(cpp|h|mm)$/.test(entry.name) && read(rel).includes('CreateChannelHelper(') && !rel.endsWith('/DNSUtils.cpp') && !rel.endsWith('/DNSUtils.h'))
        callers.push(rel);
    }
  };
  walk('netwerk');
  assert.deepEqual(callers.sort(), [
    'netwerk/base/NetworkConnectivityService.cpp',  // only under XRE_IsSocketProcess(): the parent uses NS_NewChannel
    'netwerk/dns/TRR.cpp',
    'netwerk/protocol/http/ObliviousHttpService.cpp',  // network.trr.use_ohttp, off by default
  ]);
  const connectivity = read('netwerk/base/NetworkConnectivityService.cpp');
  assert.match(connectivity, /if \(XRE_IsSocketProcess\(\)\) \{\n\s+rv = DNSUtils::CreateChannelHelper\(uri, getter_AddRefs\(channel\)\);/);
  const prefs = read('modules/libpref/init/StaticPrefList.yaml');
  assert.match(prefs, /- name: network\.trr\.use_ohttp\n\s+type: RelaxedAtomicBool\n\s+value: false/);
});
