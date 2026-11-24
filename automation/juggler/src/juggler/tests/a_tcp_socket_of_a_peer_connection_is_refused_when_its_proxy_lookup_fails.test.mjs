/// A TCP socket of a PeerConnection (TURN over TCP) is opened plain (DIRECT) only when its context has no proxy. Upstream's
// WebrtcTCPSocket::OnProxyAvailable opens it plain at the end of the function for every other outcome too: a lookup that failed (a PAC
// thread cancelled or shut down answers a failure status, which skips the proxy filters), a null info with a failed status, or an info of
// a type it does not know. The socket then leaves from the host's own address while the context has a proxy. The UDP twin
// (PcUdpProxy::KindFor) already reads a failed lookup as "proxy not known: nothing goes out".
//
// The hook is one guard before that end, StealthTcpSocketRefusesDirect (own file StealthWebrtcTcpSocket.h), which asks
// StealthTcpDirectRefused (own file StealthIceResolverContext.cpp, declared in nr_stealth_network.h) and closes the socket. The
// two hooks of OpenWithoutHttpProxy that sat before the bind (the context of the name lookup, the bind address) are one call,
// StealthTcpSocketBorn. The file lists its entries here; the presence of each hook is the series' list of hooks.
// Behaviour of the functions: dom/media/webrtc/transport/test/gtest/TestStealthTcpProxyRoad.cpp.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const T = 'dom/media/webrtc/transport/';
const TCP = T + 'ipc/WebrtcTCPSocket.cpp';
const OWN = T + 'ipc/StealthWebrtcTcpSocket.h';

const HOOK = '  if (StealthTcpSocketRefusesDirect(this, aResult, aProxyinfo)) return NS_OK;  // STEALTH-HOOK(network/proxy-udp)\n';

function onProxyAvailable() {
  const text = read(TCP);
  const start = text.indexOf('NS_IMETHODIMP WebrtcTCPSocket::OnProxyAvailable(');
  assert.ok(start > 0);
  return text.slice(start, text.indexOf('\n}\n', start) + 3);
}

test('the only plain open at the end of OnProxyAvailable is below the refusal of a socket whose lookup failed or answered an unknown proxy', () => {
  const body = onProxyAvailable();
  assert.ok(body.includes(HOOK), 'no refusal before the plain open');
  const plain = body.indexOf('OpenWithoutHttpProxy(nullptr);');
  assert.ok(plain > 0);
  assert.ok(body.indexOf(HOOK) < plain, 'the refusal comes after the plain open');
  assert.equal(body.match(/OpenWithoutHttpProxy\(nullptr\)/g).length, 1, 'a second plain open that the refusal does not guard');
  // The known types are decided before: the refusal sees only what is left.
  assert.ok(body.indexOf('OpenWithHttpProxy()') < body.indexOf(HOOK));
  assert.ok(body.indexOf('OpenWithoutHttpProxy(aProxyinfo);') < body.indexOf(HOOK));
});

test('the rule is the one of UDP: only "no proxy" (lookup succeeded, no info) opens the socket plain', () => {
  const own = read(T + 'StealthIceResolverContext.cpp');
  const fn = own.match(/bool StealthTcpDirectRefused\([\s\S]*?\n}\n/)[0];
  assert.match(fn, /return aHasProxyConfig && \(aLookupFailed \|\| aInfo != nullptr\);/);
  assert.match(read('netwerk/socket/StealthPcUdpProxy.cpp'), /Kind kind = NS_SUCCEEDED\(aStatus\) \? Kind::Direct : Kind::Blocked;/);
});

test('the refusal closes the socket with NS_ERROR_FAILURE and is the only caller of the rule in the files of the socket', () => {
  const own = read(OWN);
  const fn = own.match(/static bool TcpSocketRefusesDirect\([\s\S]*?\n  }\n/)[0];
  assert.match(fn, /StealthTcpDirectRefused\(aSocket->mProxyConfig\.isSome\(\), NS_FAILED\(aResult\), aProxyInfo\)/);
  assert.match(fn, /aSocket->CloseWithReason\(NS_ERROR_FAILURE\);\n    return true;/);
  const calls = [TCP, OWN].map(f => (read(f).match(/StealthTcpDirectRefused\(/g) || []).length);
  assert.deepEqual(calls, [0, 1], 'the rule is asked from Mozilla\'s file, or from a second place');
  // The function is declared in the header our file includes; the file of Mozilla has one include of ours.
  assert.match(read(T + 'nr_stealth_network.h'), /\nbool StealthTcpDirectRefused\(bool aHasProxyConfig, bool aLookupFailed, nsIProxyInfo\* aInfo\);\n/);
  assert.match(own, /#include "transport\/nr_stealth_network\.h"/);
  const text = read(TCP);
  assert.match(text, /\n#include "StealthWebrtcTcpSocket\.h"  \/\/ STEALTH-HOOK\(network\/proxy-udp\)\n/);
  assert.doesNotMatch(text, /StealthIceResolverContext\.h/);
  assert.equal(text.match(/\n#include [^\n]*STEALTH-HOOK/g).length, 1, 'a second tagged include');
});

test('the name context and the bind address of the transport come from one call, StealthTcpSocketBorn: the only entry of both', () => {
  const text = read(TCP);
  assert.doesNotMatch(text, /StealthTcpNameContext\(/);
  assert.doesNotMatch(text, /StealthTcpBindAddress\(/);
  assert.equal(text.match(/StealthTcpSocketBorn\(/g).length, 1);
  assert.match(read(T + 'nr_stealth_network.h'),
    /\nbool StealthTcpSocketBorn\(nsISocketTransport\* aTransport, const net::WebrtcProxyConfig\* aConfig, const char\* aDeclaredAddress,\n\s+uint16_t aNicerPort, union PRNetAddr\* aOut\);\n/);
  // Of the files of the engine outside the tests, only our file and the function of the context call the two.
  const own = read(OWN);
  assert.match(own, /mozilla::StealthTcpSocketBorn\(aSocket->mTransport, aSocket->mProxyConfig\.ptrOr\(nullptr\),\n\s+aSocket->mLocalAddress\.get\(\), aSocket->mLocalPort, aAddr\);/);
  // The ceiling of the series (tools/hook-budget.json). Skipped where the release tag is not in the checkout.
  let diff = null;
  try {
    diff = execFileSync('git', ['diff', '-U0', 'FIREFOX_159_0_RELEASE', '--', TCP],
      { cwd: TREE, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  } catch (e) {
    diff = null;
  }
  if (diff) {
    const added = diff.split('\n').filter(l => l.startsWith('+') && !l.startsWith('+++')).length;
    assert.ok(added <= 17, `${added} lines of ours in WebrtcTCPSocket.cpp, the ceiling is 17`);
  }
});

test('the channel of the proxy lookup that the swap drops is never opened, and both lookups swap through one function', () => {
  // The behaviour is in netwerk/test/gtest/TestStealthLookupLoadInfo.cpp (TheChannelTheSwapDropsIsNeverOpened, with its control).
  // Here: the lookup of this socket, between the channel Mozilla makes and the proxy service, opens nothing.
  const text = read(TCP);
  const start = text.indexOf('nsresult WebrtcTCPSocket::DoProxyConfigLookup() {');
  assert.ok(start > 0);
  const body = text.slice(start, text.indexOf('\n}\n', start) + 3);
  assert.doesNotMatch(body, /AsyncOpen|\bOpen\(|Open2|OpenWith/);
  assert.match(body, /\n  if \(StealthSwapTcpLookupChannel\(this, channel, &rv\)\) return rv;  \/\/ STEALTH-HOOK\(network\/proxy-udp\)\n/);
  assert.ok(body.indexOf('NS_NewChannel(') < body.indexOf('StealthSwapTcpLookupChannel(') && body.indexOf('StealthSwapTcpLookupChannel(') < body.indexOf('pps->AsyncResolve(channel'));
  // The swap of the socket and the one of ProxyConfigLookup are the same function, which only makes the new channel.
  assert.match(read(OWN), /return StealthSwapChannelOfLoadInfo\(aSocket->mURI, flags, aSocket->mProxyConfig->loadInfoArgs\(\), aChannel, aRv\);/);
  const doc = read('netwerk/ipc/StealthDocumentChannel.cpp');
  assert.match(doc, /  return StealthSwapChannelOfLoadInfo\(aURI, aProxyResolveFlags, loadInfo\.ref\(\),\s+aChannel, aRv\);/);
  const core = doc.slice(doc.indexOf('bool StealthSwapChannelOfLoadInfo('));
  const fn = core.slice(0, core.indexOf('\n}\n') + 3);
  assert.doesNotMatch(fn, /AsyncOpen|\bOpen\(|Open2/);
});

test('the gtest of the rule is built', () => {
  assert.match(read(T + 'test/gtest/moz.build'), /\nSOURCES \+= \["TestStealthTcpProxyRoad\.cpp"\]\n/);
  const test = read(T + 'test/gtest/TestStealthTcpProxyRoad.cpp');
  assert.match(test, /StealthTcpDirectRefused\(true, true, nullptr\)/);
  assert.match(test, /StealthTcpDirectRefused\(true, false, nullptr\)/);
});
