// A DNS-over-HTTPS request leaves by the proxy of the browser context whose
// lookup caused it. The context (userContextId of the origin attributes of the
// lookup's record) travels TRR -> the channel's load info -> the proxy lookup
// (PProxyConfigLookup in the socket process case) -> the stand-in channel, and
// Juggler's channel filter answers per userContextId of that channel's load info.
//
// Source guards: the C++ cannot run here. The behaviour is in
// netwerk/test/gtest/TestStealthTRRContext.cpp.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const HOOK = 'STEALTH-HOOK(network/doh)';

test('the filter answers per userContextId of the load info of the channel', () => {
  const text = read('juggler/TargetRegistry.js');
  assert.match(text, /const originAttributes = channel\.loadInfo && channel\.loadInfo\.originAttributes;/);
  assert.match(text, /originAttributes \? originAttributes\.userContextId : undefined/);
});

test('the context of the lookup travels in a message of ours; the message of Mozilla keeps its parameters', () => {
  const ipdl = read('netwerk/ipc/PSocketProcess.ipdl');
  assert.match(ipdl, /async PProxyConfigLookup\(nullable nsIURI aUri, uint32_t aFlags,\n\s+bool aIsTRRServiceChannel\);\n/);
  assert.match(ipdl,
      /\n  async StealthProxyLookupOrigin\(OriginAttributes\? aOriginAttributes\);  \/\/ STEALTH-HOOK\(network\/doh\)\n/);
});

test('no signature of Mozilla carries the context: it is set, taken, sent, parked and taken again, one line of ours each', () => {
  // The signatures of the lookup are Mozilla's text: no parameter of ours in them.
  for (const file of ['netwerk/ipc/ProxyConfigLookup.h', 'netwerk/ipc/ProxyConfigLookup.cpp',
    'netwerk/ipc/ProxyConfigLookupChild.h', 'netwerk/ipc/ProxyConfigLookupChild.cpp',
    'netwerk/ipc/ProxyConfigLookupParent.h', 'netwerk/ipc/ProxyConfigLookupParent.cpp'])
    assert.doesNotMatch(read(file), /OriginAttributes/, file);
  // The caller sets it on the statement before Create; nothing is passed to Create.
  // The first statement of Create takes it.
  const create = read('netwerk/ipc/ProxyConfigLookup.cpp');
  assert.match(create, /\nnsresult ProxyConfigLookup::Create\(\n[^{]*\) \{\n  StealthEnterLookupLoadInfo\(\);  \/\/ STEALTH-HOOK\(network\/proxy-udp\)\n  StealthEnterTRRLookupContext\(\);  \/\/ STEALTH-HOOK\(network\/doh\)\n  MOZ_ASSERT\(NS_IsMainThread\(\)\);\n/);
  // The socket process sends it on the one path that sends the constructor, the line right before it.
  assert.match(read('netwerk/ipc/ProxyConfigLookupChild.cpp'),
      /\n  StealthSendLookupLoadInfo\(socketChild\);  \/\/ STEALTH-HOOK\(network\/proxy-udp\)\n  StealthSendTRRLookupContext\(socketChild\);  \/\/ STEALTH-HOOK\(network\/doh\)\n  return socketChild->SendPProxyConfigLookupConstructor\(\n      child, aURI, aProxyResolveFlags, aIsTRRServiceChannel\);\n/);
  const senders = [];
  const walk = dir => {
    for (const entry of fs.readdirSync(path.join(TREE, dir), { withFileTypes: true })) {
      const rel = dir + '/' + entry.name;
      if (entry.isDirectory()) { if (entry.name !== 'gtest') walk(rel); }  // a gtest names the function in its own stand-in actor
      else if (/\.(cpp|h)$/.test(entry.name) && read(rel).includes('SendPProxyConfigLookupConstructor(')) senders.push(rel);
    }
  };
  for (const dir of ['netwerk', 'dom/media/webrtc']) walk(dir);
  assert.deepEqual(senders, ['netwerk/ipc/ProxyConfigLookupChild.cpp'], 'every constructor has its message: one sender');
  // The parent keeps what arrives (our file) and the constructor takes it, as its first statement.
  assert.match(read('netwerk/ipc/SocketProcessParent.h'),
      /\n  mozilla::ipc::IPCResult RecvStealthProxyLookupOrigin\(const Maybe<OriginAttributes>& aOriginAttributes\);  \/\/ STEALTH-HOOK\(network\/doh\)\n/);
  assert.match(read('netwerk/ipc/SocketProcessParent.cpp'),
      /RecvPProxyConfigLookupConstructor\(\n    PProxyConfigLookupParent\* aActor, nsIURI\* aURI,\n    const uint32_t& aProxyResolveFlags, const bool& aIsTRRServiceChannel\) \{\n  StealthTakeParkedLookupLoadInfo\(this\);  \/\/ STEALTH-HOOK\(network\/proxy-udp\)\n  StealthTakeParkedTRRLookupContext\(this\);  \/\/ STEALTH-HOOK\(network\/doh\)\n  mozilla::ipc::ActorCast<ProxyConfigLookupParent>\(aActor\)->DoProxyLookup\(\);\n/);
  const own = read('netwerk/ipc/StealthTRRContext.cpp');
  assert.match(own, /IPCResult SocketProcessParent::RecvStealthProxyLookupOrigin\(\n    const Maybe<OriginAttributes>& aOriginAttributes\) \{\n  StealthParkTRRLookupContext\(this, aOriginAttributes\);\n  return IPC_OK\(\);/);
});

test('the stand-in channel of the lookup is given the context before the proxy is asked', () => {
  const text = read('netwerk/ipc/ProxyConfigLookup.cpp');
  // The hook sits after upstream's check of the status of the statement that makes the stand-in, which stays as Mozilla
  // wrote it.
  const apply = text.indexOf('if (StealthApplyTRRLookupContext(channel, &rv)) return rv;  // STEALTH-HOOK(network/doh)');
  const ask = text.indexOf('pps2->AsyncResolve2(channel');
  assert.ok(apply > 0, 'the stand-in does not get the context');
  assert.ok(ask > apply, 'the proxy is asked before the stand-in has its context');
});

test('the TRR request takes the context of its lookup, right after its channel is made', () => {
  const text = read('netwerk/dns/TRR.cpp');
  const made = text.indexOf('rv = DNSUtils::CreateChannelHelper(dnsURI, getter_AddRefs(channel));');
  // The hook sits right after the check of the channel Mozilla makes, which stays as Mozilla wrote it.
  const apply = text.indexOf('if (StealthTRRApplyContext(mOriginSuffix, channel, &rv)) return rv;  // STEALTH-HOOK(network/doh)');
  const open = text.indexOf('rv = httpChannel->AsyncOpen(this);');
  assert.ok(made > 0 && apply > made, 'the context is not applied after the channel is made');
  assert.ok(open > apply, 'the channel is opened before it has its context');
  assert.equal(text.split('StealthApplyTRRContextToChannel(').length - 1, 0, 'the context is given by the one function of ours');
});

test('the cached connection info of the default context never serves another context', () => {
  const text = read('netwerk/dns/TRR.cpp');
  assert.match(text, /  if \(UseDefaultServer\(\) && !useOHTTP &&\n      StealthTRRConnInfoUsable\(mOriginSuffix, StaticPrefs::network_trr_async_connInfo\(\)\)\) \{  \/\/ STEALTH-HOOK\(network\/doh\)/);
  // The pref is read by that condition alone in TRR.cpp.
  assert.equal(text.split('async_connInfo()').length - 1, 1);
});

test('the file of the two TRR.cpp functions is registered next to the resolver\'s, and TRR.cpp reaches it through one include of ours after Mozilla\'s', () => {
  assert.match(read('netwerk/dns/moz.build'), /\]\nUNIFIED_SOURCES \+= \["StealthSessionResolver\.cpp", "StealthTRRRequest\.cpp"\]  # STEALTH-HOOK\(network\/doh\)\n/);
  assert.match(read('netwerk/dns/TRR.cpp'), /\n#include "mozilla\/glean\/NetwerkMetrics\.h"\n\n#include "StealthTRRRequest\.h"  \/\/ STEALTH-HOOK\(network\/doh\)\n\nnamespace mozilla \{/);
  const code = read('netwerk/dns/StealthTRRRequest.cpp');
  assert.match(code, /StealthApplyTRRContextToChannel\(\s*aChannel, StealthTRRContextOfSuffix\(aOriginSuffix\)\)/);
  assert.match(code, /return aPrefValue && StealthTRRContextOfSuffix\(aOriginSuffix\)\.isNothing\(\);/);
});

test('the TRR channel sets the context of its load info on the statement before the lookup, and passes nothing to it', () => {
  const text = read('netwerk/protocol/http/TRRServiceChannel.cpp');
  const resolve = text.slice(text.indexOf('nsresult TRRServiceChannel::ResolveProxy()'));
  assert.match(resolve.slice(0, 1200),
      /  nsCOMPtr<nsICancelable> proxyRequest;\n  StealthSetTRRLookupContext\(this\);  \/\/ STEALTH-HOOK\(network\/doh\)\n  nsresult rv = ProxyConfigLookup::Create\(\n      \[self\]\(nsIProxyInfo\* aProxyInfo, nsresult aStatus\) \{\n        self->OnProxyAvailable\(nullptr, nullptr, aProxyInfo, aStatus\);\n      \},\n      mURI, mProxyResolveFlags, LoadIsTRRServiceChannel\(\),\n      getter_AddRefs\(proxyRequest\)\);\n/);
});

test('a TRR load info keeps the context, and its clone (a redirect) too', () => {
  const text = read('netwerk/base/TRRLoadInfo.cpp');
  const set = text.slice(text.indexOf('nsresult TRRLoadInfo::SetOriginAttributes('));
  // The setter is answered by the guard at its top; Mozilla's refusal stays below it, as in the tag.
  assert.match(set.slice(0, set.indexOf('\n}\n') + 3),
      /\{\n  if \(nsresult rv; StealthTRRSetOriginAttributes\(mOriginAttributes, aOriginAttributes, &rv\)\) return rv;  \/\/ STEALTH-HOOK\(network\/doh\)\n  return NS_ERROR_NOT_IMPLEMENTED;\n\}\n/);
  const clone = text.slice(text.indexOf('TRRLoadInfo::Clone()'), text.indexOf('TRRLoadInfo::GetLoadingPrincipal'));
  assert.match(clone, /->mOriginAttributes = mOriginAttributes;  \/\/ STEALTH-HOOK\(network\/doh\)/);
});

test('our file and its gtest are registered', () => {
  assert.match(read('netwerk/ipc/moz.build'), /EXPORTS\.mozilla\.net \+= \["StealthTRRContext\.h"\]  # STEALTH-HOOK\(network\/doh\)/);
  assert.match(read('netwerk/ipc/moz.build'), /UNIFIED_SOURCES \+= \["StealthTRRContext\.cpp"\]  # STEALTH-HOOK\(network\/doh\)/);
  // The gtests of the network line are listed in stealth.build, which Mozilla's moz.build includes with one line.
  assert.match(read('netwerk/test/gtest/moz.build'), /include\("stealth\.build"\)  # STEALTH-HOOK\(network\/socks\)/);
  assert.match(read('netwerk/test/gtest/stealth.build'), /SOURCES \+= \[[^\]]*"TestStealthTRRContext\.cpp",/);
});
