// The name of an ICE server (stun:stun-a.test, turn:...) is resolved in the browser
// context of the page that made the PeerConnection. Upstream resolves it with default
// origin attributes (NrIceResolver::resolve: `OriginAttributes attrs;`), so the
// DNS-over-HTTPS request of the lookup leaves in the default user context (userContextId
// 0), by the proxy of the browser, not by the proxy of the context. A retail Firefox
// resolves the name and loses the datagrams; ours got a negative answer and failed at
// once.
//
// The attributes travel: WebrtcProxyConfig.loadInfoArgs().originAttributes() (already
// sent to the process that gathers, before the gather) -> NrIceResolver::mAttrs (set on
// the STS thread by MediaTransportImplNicer::SetProxyConfig) -> AsyncResolveNative.
// The names of the UDP candidates (STUN, TURN over UDP) go through the one NrIceResolver. A TURN
// server given by name over TCP (turn:name:port?transport=tcp) does not: in the process that
// gathers, NR_ICE_REG_USE_NR_RESOLVER_FOR_TCP is set only in the parent process, so the name
// reaches NrTcpSocket::connect -> WebrtcTCPSocket::OpenWithoutHttpProxy, which creates an
// nsSocketTransport whose origin attributes are the default ones. nsSocketTransport::ResolveHost
// then asks the DNS service for userContextId 0, which is in no context's DoH list
// (network.trr.stealth.contexts): the name is resolved by the machine's resolver. The same
// attributes are therefore given to that transport, before it is bound (it refuses them once its
// socket exists), whenever the socket has a proxy config (the config carries the load info of the
// PeerConnection).
//
// Source guards: the C++ cannot run here. The behaviour is in
// dom/media/webrtc/transport/test/gtest/TestStealthIceResolverContext.cpp.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const T = 'dom/media/webrtc/transport/';
const TCP = T + 'ipc/WebrtcTCPSocket.cpp';

test('the resolver looks the name up with the attributes it was given, never with a bare default', () => {
  const text = read(T + 'nriceresolver.cpp');
  // Mozilla's declaration and its argument stay; one line of ours fills the attributes right after the declaration.
  assert.match(text, /\n\s*OriginAttributes attrs;\n  StealthIceResolverLookupAttributes\(this, &attrs\);  \/\/ STEALTH-HOOK\(network\/doh\)\n/);
  assert.match(text, /sts_thread_, attrs, getter_AddRefs\(pr->request_\)/);
  assert.equal(text.match(/AsyncResolveNative/g).length, 1, 'one lookup path in the class');
  const code = read(T + 'StealthIceResolverContext.cpp');
  assert.match(code, /void StealthIceResolverLookupAttributes\(const NrIceResolver\* aResolver,\s+OriginAttributes\* aAttrs\) \{\n  if \(aResolver\) \{\n    \*aAttrs = aResolver->GetOriginAttributes\(\);\n  \}\n\}/);
});

test('the resolver holds the attributes and gives them back', () => {
  const text = read(T + 'nriceresolver.h');
  assert.match(text, /#include "StealthIceResolverContext\.h"  \/\/ STEALTH-HOOK\(network\/doh\)/);
  assert.match(text, /void SetOriginAttributes\(const OriginAttributes& aAttrs\);  \/\/ STEALTH-HOOK\(network\/doh\)/);
  assert.match(text, /const OriginAttributes& GetOriginAttributes\(\) const;  \/\/ STEALTH-HOOK\(network\/doh\)/);
  assert.match(text, /nr_resolver_vtbl\* vtbl_;\n  OriginAttributes mAttrs;  \/\/ STEALTH-HOOK\(network\/doh\)/);
  // The class of Mozilla holds no body of ours: the two methods are defined in our file.
  assert.doesNotMatch(text, /\{ mAttrs = aAttrs; \}|\{ return mAttrs; \}/);
  const code = read(T + 'StealthIceResolverContext.cpp');
  assert.match(code, /void NrIceResolver::SetOriginAttributes\(const OriginAttributes& aAttrs\) \{\n  mAttrs = aAttrs;\n\}/);
  assert.match(code, /const OriginAttributes& NrIceResolver::GetOriginAttributes\(\) const \{\n  return mAttrs;\n\}/);
});

test('SetProxyConfig gives the resolver the attributes of the PeerConnection before the config is moved away', () => {
  const text = read('dom/media/webrtc/jsapi/MediaTransportHandler.cpp');
  assert.match(text, /\n#include "transport\/runnable_utils\.h"\n\n#include "transport\/StealthIceResolverContext\.h"  \/\/ STEALTH-HOOK\(network\/doh\)\n\n/);
  const body = text.match(/void MediaTransportImplNicer::SetProxyConfig\([\s\S]*?\n}\n/)[0];
  const set = body.indexOf('StealthIceResolverSetContext(mDNSResolver, aProxyConfig);  // STEALTH-HOOK(network/doh)');
  assert.ok(set > 0, 'the resolver is not given the attributes');
  assert.ok(set > body.indexOf('if (!mIceCtx) {'), 'the call runs on the closing road, before Mozilla\'s check of the ICE context');
  assert.ok(set < body.indexOf('std::move(aProxyConfig)'), 'the config is read after it was moved');
  // The only entry that gives the resolver of a PeerConnection its attributes.
  assert.equal(text.match(/SetOriginAttributes\(/g), null, 'a resolver given its attributes outside our function');
  const code = read(T + 'StealthIceResolverContext.cpp');
  assert.match(code, /void StealthIceResolverSetContext\(const RefPtr<NrIceResolver>& aResolver,\s+const NrSocketProxyConfig& aConfig\) \{\n  StealthIceResolverSetContext\(\s+aResolver, aConfig\.GetConfig\(\)\.loadInfoArgs\(\)\.originAttributes\(\)\);\n\}/);
  assert.match(code, /if \(aResolver\) \{\n    aResolver->SetOriginAttributes\(\s+StealthIceResolverAttributes\(aPeerConnection\)\);\n  \}/);
});

test('our function reads the attributes of the load info of the config and keeps the user context alone', () => {
  const header = read(T + 'StealthIceResolverContext.h');
  const code = read(T + 'StealthIceResolverContext.cpp');
  assert.match(header, /OriginAttributes StealthIceResolverAttributes\(\s*const OriginAttributes& aPeerConnection\)/);
  assert.match(header, /OriginAttributes StealthIceResolverAttributes\(\s*const NrSocketProxyConfig& aConfig\)/);
  assert.match(code, /aConfig\.GetConfig\(\)\.loadInfoArgs\(\)\.originAttributes\(\)/);
  assert.match(code, /attrs\.mUserContextId = aPeerConnection\.mUserContextId;/);
});

test('a TURN server given by name over TCP is resolved in the context of the PeerConnection: no query reaches the system resolver', () => {
  const text = read(TCP);
  const body = text.match(/void WebrtcTCPSocket::OpenWithoutHttpProxy\([\s\S]*?\n}\n/)[0];
  // One call gives the transport its context and the family of its bind address (StealthTcpSocketBorn), after Mozilla parsed the
  // local address and before the bind: the transport refuses its attributes once its socket exists.
  const hook = '\n  StealthTcpSocketBorn(this, &prAddr);  // STEALTH-HOOK(fingerprint/webrtc/declared-network)\n';
  assert.ok(body.includes(hook), 'the transport of the TCP socket is not given the attributes of the PeerConnection');
  assert.equal(text.match(/StealthTcpSocketBorn\(/g).length, 1, 'the only entry of the context is this call');
  assert.doesNotMatch(text, /StealthTcpNameContext\(/, 'the context has its own line again');
  const at = body.indexOf(hook);
  const created = body.indexOf('sts->CreateTransport(');
  assert.ok(created > 0 && created < at, 'the attributes are set on a transport that does not exist yet');
  assert.ok(body.indexOf('PR_StringToNetAddr(mLocalAddress.get(), &prAddr)') < at, 'the address is parsed by Mozilla first');
  assert.ok(at < body.indexOf('mTransport->Bind('), 'the transport refuses its attributes once it is bound');
  assert.ok(at < body.indexOf('OpenInputStream('), 'the lookup starts when the streams open');
  assert.ok(body.indexOf('CloseWithReason(rv);', created) < at, 'a transport that was not created is not used');
  // Our access: the transport and the config of the socket, handed to the one function that sets the attributes.
  const access = read(T + 'ipc/StealthWebrtcTcpSocket.h');
  assert.match(access, /mozilla::StealthTcpSocketBorn\(aSocket->mTransport, aSocket->mProxyConfig\.ptrOr\(nullptr\),\n\s+aSocket->mLocalAddress\.get\(\), aSocket->mLocalPort, aAddr\);/);
  // The function itself: the attributes the resolver of the UDP names uses, taken from the load info of the config.
  const own = read(T + 'StealthIceResolverContext.cpp');
  const fn = own.match(/void StealthTcpNameContext\([\s\S]*?\n}\n/)[0];
  assert.match(fn, /if \(aTransport && aConfig\) \{/);
  assert.match(fn, /aTransport->SetOriginAttributes\(StealthIceResolverAttributes\(\s*aConfig->loadInfoArgs\(\)\.originAttributes\(\)\)\);/);
  // The merged call: the context first, then the bind address, both in the file that holds them.
  const born = own.match(/bool StealthTcpSocketBorn\([\s\S]*?\n}\n/)[0];
  assert.ok(born.includes('StealthTcpNameContext(aTransport, aConfig);'));
  assert.ok(born.indexOf('StealthTcpNameContext(') < born.indexOf('return StealthTcpBindAddress('), 'the bind address is decided before the context is given');
});

test('a TURN name over TCP does not go through NrIceResolver in the process that gathers, so the transport is the only place to carry the context', () => {
  const nricectx = read(T + 'nricectx.cpp');
  assert.match(nricectx, /NR_ICE_REG_USE_NR_RESOLVER_FOR_TCP/);
  assert.match(nricectx, /XRE_IsParentProcess\(\)/);
  assert.equal(read(TCP).match(/CreateTransport\(/g).length, 1, 'a second transport of the TCP socket would need the same attributes');
});

test('the functions are declared in the header our file of the TCP socket includes, so Mozilla\'s file has one include of ours', () => {
  assert.match(read(T + 'nr_stealth_network.h'), /\nvoid StealthTcpNameContext\(nsISocketTransport\* aTransport, const net::WebrtcProxyConfig\* aConfig\);\n/);
  assert.match(read(T + 'ipc/StealthWebrtcTcpSocket.h'), /#include "transport\/nr_stealth_network\.h"/);
  const text = read(TCP);
  assert.match(text, /\n#include "StealthWebrtcTcpSocket\.h"  \/\/ STEALTH-HOOK\(network\/proxy-udp\)\n/);
  assert.doesNotMatch(text, /StealthIceResolverContext\.h/);
  assert.doesNotMatch(read(T + 'build/moz.build'), /StealthIceResolverContext/);
});

test('the files are built', () => {
  assert.match(read(T + 'common.build'), /\ntransport_lcppsrcs \+= \["StealthIceResolverContext\.cpp"\]  # STEALTH-HOOK\(network\/doh\)\n/);
  assert.match(read(T + 'test/gtest/moz.build'), /SOURCES \+= \["TestStealthIceResolverContext\.cpp"\]  # STEALTH-HOOK\(network\/doh\)/);
});

test('the gtest covers the default, the context and the function', () => {
  const text = read(T + 'test/gtest/TestStealthIceResolverContext.cpp');
  assert.match(text, /TEST\(StealthIceResolverContext, /);
  assert.match(text, /ContextWithUser\(6\)/);
  assert.match(text, /GetOriginAttributes\(\)\.mUserContextId/);
  assert.match(text, /NrIceResolver/);
});
